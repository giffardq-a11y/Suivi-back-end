from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/substances", tags=["substances"])


class SubstanceCreate(BaseModel):
    label: str
    unit: str | None = None
    unit_cost: float = 0
    note: str | None = None


@router.post("", status_code=201)
def create_substance(
    payload: SubstanceCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    sub = models.Substance(
        user_id=user.id,
        label=payload.label,
        category=models.SubstanceCategory.OTHER,
        unit_cost=payload.unit_cost,
        unit=payload.unit,
        note=payload.note,
    )
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


@router.get("")
def list_substances(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [
        {
            "id": s.id, "label": s.label, "category": s.category.value, "unit": s.unit,
            "unit_cost": s.unit_cost, "usual_frequency_per_day": s.usual_frequency_per_day,
            "note": s.note, "quit_date": s.quit_date,
            "daily_saving": round((s.unit_cost or 0) * (s.usual_frequency_per_day or 0), 2),
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

    if payload.quit_date:
        try:
            date.fromisoformat(payload.quit_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="quit_date doit être au format AAAA-MM-JJ")

    for champ, valeur in payload.model_dump(exclude_unset=True).items():
        setattr(sub, champ, valeur)
    db.commit()
    return {"ok": True}


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
