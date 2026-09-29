"""Module Hydratation : verres bus, objectif du jour, rappels.

Les rappels eux-mêmes sont des notifications locales programmées par l'app
(Expo) : le serveur ne garde que leurs réglages, pour les retrouver sur un
autre téléphone.

Les jours sont découpés en UTC (services/common.date_key), comme le reste de
l'app : un verre bu à 1 h du matin heure de Paris compte encore pour la
veille. À reprendre globalement le jour où l'app gérera User.timezone.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import personnage_hooks
from ..services.common import aware, date_key, from_ms, now_utc, to_ms

router = APIRouter(prefix="/hydration", tags=["hydration"])

# Suggestion d'objectif : 33 ml par kg (milieu de la fourchette 30-35 ml/kg
# du cahier), arrondie aux 50 ml. Sans poids connu, 2 litres.
ML_PAR_KG = 33
OBJECTIF_PAR_DEFAUT_ML = 2000
MENTION = "Estimation indicative, pas un conseil médical."


class WaterLogIn(BaseModel):
    amountMl: int = Field(gt=0, le=5000)
    occurredAtMs: int | None = None


class HydrationSettingsIn(BaseModel):
    dailyGoalMl: int | None = Field(default=None, gt=0, le=10000)
    glassSizes: list[int] | None = None
    remindersEnabled: bool | None = None
    reminderStart: str | None = None
    reminderEnd: str | None = None
    reminderIntervalMin: int | None = Field(default=None, ge=15, le=480)

    @field_validator("glassSizes")
    @classmethod
    def _verres(cls, v):
        if v is not None and (not v or len(v) > 6 or any(x <= 0 or x > 5000 for x in v)):
            raise ValueError("1 à 6 tailles de verre, entre 1 et 5000 ml")
        return v

    @field_validator("reminderStart", "reminderEnd")
    @classmethod
    def _heure(cls, v):
        if v is not None:
            h, _, m = v.partition(":")
            if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
                raise ValueError("heure attendue au format HH:MM")
        return v


def _reglages(db: Session, user: models.User) -> models.HydrationSettings:
    ligne = db.query(models.HydrationSettings).filter(models.HydrationSettings.user_id == user.id).first()
    if ligne is None:
        # Deux premières lectures simultanées : la seconde bute sur l'unicité
        # de user_id et relit la ligne créée par la première.
        try:
            ligne = models.HydrationSettings(user_id=user.id)
            db.add(ligne)
            db.commit()
            db.refresh(ligne)
        except IntegrityError:
            db.rollback()
            ligne = db.query(models.HydrationSettings).filter(models.HydrationSettings.user_id == user.id).one()
    return ligne


def _objectif_suggere(db: Session, user: models.User) -> int:
    pesee = (
        db.query(models.WeightEntry)
        .filter(models.WeightEntry.user_id == user.id)
        .order_by(models.WeightEntry.occurred_at.desc())
        .first()
    )
    if pesee is None or not pesee.weight_kg:
        return OBJECTIF_PAR_DEFAUT_ML
    return int(round(pesee.weight_kg * ML_PAR_KG / 50) * 50)


def _objectif(db: Session, user: models.User, reglages: models.HydrationSettings) -> int:
    return reglages.daily_goal_ml or _objectif_suggere(db, user)


def _serialiser_reglages(db: Session, user: models.User, r: models.HydrationSettings) -> dict:
    return {
        "dailyGoalMl": r.daily_goal_ml,
        "suggestedGoalMl": _objectif_suggere(db, user),
        "suggestionNote": MENTION,
        "glassSizes": r.glass_sizes or [250, 330, 500],
        "remindersEnabled": bool(r.reminders_enabled),
        "reminderStart": r.reminder_start,
        "reminderEnd": r.reminder_end,
        "reminderIntervalMin": r.reminder_interval_min,
    }


def _logs(db: Session, user: models.User) -> list[models.WaterLog]:
    return db.query(models.WaterLog).filter(models.WaterLog.user_id == user.id).all()


def _totaux_par_jour(logs: list[models.WaterLog]) -> dict[str, int]:
    totaux: dict[str, int] = {}
    for l in logs:
        cle = date_key(aware(l.occurred_at))
        totaux[cle] = totaux.get(cle, 0) + l.amount_ml
    return totaux


def _serialiser_log(l: models.WaterLog) -> dict:
    return {"id": l.id, "amountMl": l.amount_ml, "occurredAt": to_ms(l.occurred_at)}


@router.get("")
def get_hydration(
    date: str | None = Query(None, description="Jour 'YYYY-MM-DD' (défaut : aujourd'hui)"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    jour = date or date_key(now_utc())
    reglages = _reglages(db, user)
    objectif = _objectif(db, user, reglages)
    du_jour = sorted(
        (l for l in _logs(db, user) if date_key(aware(l.occurred_at)) == jour),
        key=lambda l: aware(l.occurred_at),
    )
    total = sum(l.amount_ml for l in du_jour)
    return {
        "date": jour,
        "totalMl": total,
        "goalMl": objectif,
        "percent": min(100, round(100 * total / objectif)) if objectif else 0,
        "goalReached": total >= objectif,
        "logs": [_serialiser_log(l) for l in du_jour],
        "settings": _serialiser_reglages(db, user, reglages),
    }


@router.post("", status_code=201)
def add_water(
    payload: WaterLogIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    quand = from_ms(payload.occurredAtMs) if payload.occurredAtMs is not None else now_utc()
    jour = date_key(quand)
    objectif = _objectif(db, user, _reglages(db, user))
    avant = _totaux_par_jour(_logs(db, user)).get(jour, 0)

    log = models.WaterLog(user_id=user.id, amount_ml=payload.amountMl, occurred_at=quand)
    db.add(log)
    db.commit()
    db.refresh(log)

    apres = avant + payload.amountMl
    # Seul le verre qui fait franchir l'objectif le signale : les suivants
    # du même jour n'ajoutent rien (le cahier plafonne à 1 par jour).
    resultat = None
    if avant < objectif <= apres:
        resultat = personnage_hooks.evenement(db, user, "hydration_goal", jour, {"totalMl": apres, "goalMl": objectif, "dateKey": jour})
    return {
        **_serialiser_log(log), "dayTotalMl": apres, "goalMl": objectif, "goalReached": apres >= objectif,
        "personnage": personnage_hooks.resumer([resultat]),
    }


@router.delete("/{log_id}", status_code=204)
def delete_water(
    log_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    log = db.query(models.WaterLog).filter(models.WaterLog.id == log_id, models.WaterLog.user_id == user.id).first()
    if log is None:
        raise HTTPException(status_code=404, detail="Verre introuvable")
    jour = date_key(aware(log.occurred_at))
    db.delete(log)
    db.commit()
    # Verre saisi par erreur qui repasse le jour sous l'objectif : le point
    # d'hydratation du jour est retiré (le niveau, lui, reste).
    if _totaux_par_jour(_logs(db, user)).get(jour, 0) < _objectif(db, user, _reglages(db, user)):
        personnage_hooks.retrait(db, user, "hydration_goal", jour)


@router.get("/stats")
def hydration_stats(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Totaux par jour et séries. L'objectif appliqué à tout l'historique est
    l'objectif actuel : on ne garde pas l'historique des réglages, et un
    objectif changé hier n'a pas à rendre rétroactivement « ratée » une
    semaine réussie au sens de l'ancien — ni l'inverse. Approximation
    assumée, à revoir si l'historique d'objectif devient utile."""
    aujourdhui = now_utc()
    objectif = _objectif(db, user, _reglages(db, user))
    totaux = _totaux_par_jour(_logs(db, user))

    jours = [date_key(aujourdhui - timedelta(days=i)) for i in range(days - 1, -1, -1)]
    serie = [{"date": j, "totalMl": totaux.get(j, 0), "goalReached": totaux.get(j, 0) >= objectif} for j in jours]

    # Série en cours : la journée entamée ne la casse pas tant qu'elle n'est
    # pas finie, on part donc d'hier si l'objectif du jour n'est pas encore atteint.
    en_cours = 0
    curseur = aujourdhui if totaux.get(date_key(aujourdhui), 0) >= objectif else aujourdhui - timedelta(days=1)
    while totaux.get(date_key(curseur), 0) >= objectif and en_cours < 3660:
        en_cours += 1
        curseur -= timedelta(days=1)

    meilleure = courante = 0
    for jour in serie:
        courante = courante + 1 if jour["goalReached"] else 0
        meilleure = max(meilleure, courante)

    return {
        "days": days,
        "goalMl": objectif,
        "averageMl": round(sum(j["totalMl"] for j in serie) / days),
        "daysGoalReached": sum(1 for j in serie if j["goalReached"]),
        "currentStreak": en_cours,
        "bestStreak": meilleure,
        "perDay": serie,
    }


@router.put("/settings")
def update_hydration_settings(
    payload: HydrationSettingsIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    r = _reglages(db, user)
    champs = payload.model_dump(exclude_unset=True)
    correspondance = {
        "dailyGoalMl": "daily_goal_ml", "glassSizes": "glass_sizes", "remindersEnabled": "reminders_enabled",
        "reminderStart": "reminder_start", "reminderEnd": "reminder_end", "reminderIntervalMin": "reminder_interval_min",
    }
    for cle, valeur in champs.items():
        # dailyGoalMl explicitement à null = revenir à la suggestion.
        if valeur is None and cle not in ("dailyGoalMl", "reminderStart", "reminderEnd", "reminderIntervalMin"):
            continue
        setattr(r, correspondance[cle], valeur)
    db.commit()
    db.refresh(r)
    return _serialiser_reglages(db, user, r)
