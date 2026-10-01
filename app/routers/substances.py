from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import personnage_hooks
from ..services.common import now_utc
from ..services.substance_progress import (
    limite_du_jour, palier_courant, paliers_total,
)

router = APIRouter(prefix="/substances", tags=["substances"])


class SubstanceCreate(BaseModel):
    label: str
    unit: str | None = None
    unit_cost: float = 0
    note: str | None = None
    # Choisies à la création (écran "Ajouter une consommation") plutôt que de
    # forcer un aller-retour ultérieur dans Paramètres pour recatégoriser et
    # fixer la date d'arrêt : voir _valider_categorie et son usage ci-dessous.
    category: str | None = None
    quit_date: str | None = None
    # Réduction progressive (facultative) : voir services/substance_progress.py.
    reduction_start_value: float | None = Field(default=None, gt=0)
    reduction_step_per_week: float | None = Field(default=None, gt=0)
    reduction_start_date: date | None = None


def _caler_reduction(sub: "models.Substance") -> None:
    """Une réduction a besoin des deux valeurs (départ et pas) : une seule
    des deux → 422. Configurée sans date de départ, elle part d'aujourd'hui ;
    retirée (les deux à null), la date part avec."""
    depart, pas = sub.reduction_start_value, sub.reduction_step_per_week
    if (depart is None) != (pas is None):
        raise HTTPException(
            status_code=422,
            detail="Réduction progressive : la limite de départ et la baisse par semaine vont ensemble")
    if depart is None:
        sub.reduction_start_date = None
    elif sub.reduction_start_date is None:
        sub.reduction_start_date = now_utc().date()


def _valider_categorie(categorie: str | None, user: models.User, substance_id_a_exclure: str | None = None):
    """Catégorie validée (ou OTHER si non fournie) ; lève 422/409 sinon. Au
    plus une consommation par catégorie alcohol/tobacco pour un compte."""
    if categorie is None:
        return models.SubstanceCategory.OTHER
    try:
        validee = models.SubstanceCategory(categorie)
    except ValueError:
        raise HTTPException(status_code=422, detail="Catégorie invalide")
    if validee != models.SubstanceCategory.OTHER:
        doublon = next(
            (s for s in user.substances if s.category == validee and s.id != substance_id_a_exclure), None)
        if doublon:
            raise HTTPException(
                status_code=409,
                detail=f"« {doublon.label} » a déjà la catégorie {validee.value}")
    return validee


def _valider_quit_date(quit_date: str | None) -> None:
    if quit_date:
        try:
            date.fromisoformat(quit_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="quit_date doit être au format AAAA-MM-JJ")


@router.post("", status_code=201)
def create_substance(
    payload: SubstanceCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    categorie = _valider_categorie(payload.category, user)
    _valider_quit_date(payload.quit_date)
    sub = models.Substance(
        user_id=user.id,
        label=payload.label,
        category=categorie,
        unit_cost=payload.unit_cost,
        unit=payload.unit,
        note=payload.note,
        quit_date=payload.quit_date,
        reduction_start_value=payload.reduction_start_value,
        reduction_step_per_week=payload.reduction_step_per_week,
        reduction_start_date=payload.reduction_start_date,
    )
    _caler_reduction(sub)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"ok": True, "id": sub.id}


class SubstanceUpdate(BaseModel):
    """Modification d'une consommation suivie. Tout est optionnel."""
    label: str | None = None
    unit: str | None = None
    unit_cost: float | None = None
    usual_frequency_per_day: float | None = None
    note: str | None = None
    # Date d'arrêt déclarée ('YYYY-MM-DD') : c'est le point de départ du
    # compteur de jours sans consommation, à la place de la date de création
    # du compte (voir services/streaks.py).
    quit_date: str | None = None
    # Recatégoriser une consommation "autre" en alcool/tabac (ou l'inverse) :
    # un compte créé avant la distinction alcohol/tobacco a pu suivre ces
    # deux-là comme des consommations personnalisées (category=other), ce qui
    # les exclut silencieusement des compteurs de streak/économies de
    # l'Accueil (filtrés par catégorie). Au plus une consommation par
    # catégorie alcohol/tobacco : voir la vérification plus bas.
    category: str | None = None
    # Réduction progressive : null retire la réduction (les deux valeurs
    # ensemble, voir _caler_reduction). Valeurs strictement positives.
    reduction_start_value: float | None = Field(default=None, gt=0)
    reduction_step_per_week: float | None = Field(default=None, gt=0)
    reduction_start_date: date | None = None


@router.get("")
def list_substances(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    today = now_utc().date()
    return [
        {
            "id": s.id, "label": s.label, "category": s.category.value, "unit": s.unit,
            "unit_cost": s.unit_cost, "usual_frequency_per_day": s.usual_frequency_per_day,
            "note": s.note, "quit_date": s.quit_date,
            "daily_saving": round((s.unit_cost or 0) * (s.usual_frequency_per_day or 0), 2),
            "reduction_start_value": s.reduction_start_value,
            "reduction_step_per_week": s.reduction_step_per_week,
            "reduction_start_date": s.reduction_start_date.isoformat() if s.reduction_start_date else None,
            # Calculés à la lecture (rien de stocké) ; null sans réduction.
            "limite_du_jour": limite_du_jour(s, today),
            "palier_courant": palier_courant(s, today),
            "paliers_total": paliers_total(s),
        }
        for s in user.substances
    ]


@router.put("/{substance_id}")
def update_substance(
    substance_id: str,
    payload: SubstanceUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    sub = (
        db.query(models.Substance)
        .filter(models.Substance.id == substance_id, models.Substance.user_id == user.id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Consommation introuvable")

    _valider_quit_date(payload.quit_date)
    nouvelle_categorie = (
        _valider_categorie(payload.category, user, substance_id_a_exclure=substance_id)
        if payload.category is not None else None
    )

    for champ, valeur in payload.model_dump(exclude_unset=True, exclude={"category"}).items():
        setattr(sub, champ, valeur)
    if nouvelle_categorie is not None:
        sub.category = nouvelle_categorie
    _caler_reduction(sub)
    db.commit()
    resultats = []
    if "quit_date" in payload.model_fields_set:
        # Paliers de santé déjà atteints depuis la date d'arrêt déclarée.
        resultats = personnage_hooks.constater(db, user)
    return {"ok": True, "personnage": personnage_hooks.resumer(resultats)}


@router.delete("/{substance_id}", status_code=204)
def delete_substance(
    substance_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Supprime une consommation suivie et tout son historique.

    Irréversible : les entrées de consommation partent avec (cascade du
    modèle), donc les séries et les économies calculées dessus aussi."""
    sub = (
        db.query(models.Substance)
        .filter(models.Substance.id == substance_id, models.Substance.user_id == user.id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Consommation introuvable")
    db.delete(sub)
    db.commit()
    return None
