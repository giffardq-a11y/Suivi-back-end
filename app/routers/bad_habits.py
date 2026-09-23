from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import days_since, now_utc

router = APIRouter(prefix="/bad-habits", tags=["bad-habits"])


class BadHabitCreate(BaseModel):
    label: str
    note: str | None = None


class BadHabitLogOccurrence(BaseModel):
    note: str | None = None


def _serialize(b: models.BadHabit) -> dict:
    return {
        "id": b.id,
        "label": b.label,
        "days_since": days_since(b.last_occurrence_at),
        "note": b.note,
    }


@router.get("")
def list_bad_habits(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    items = db.query(models.BadHabit).filter(models.BadHabit.user_id == user.id).all()
    return [_serialize(b) for b in items]


@router.post("", status_code=201)
def create_bad_habit(
    payload: BadHabitCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    bad = models.BadHabit(
        user_id=user.id, label=payload.label, note=payload.note, last_occurrence_at=now_utc()
    )
    db.add(bad)
    db.commit()
    db.refresh(bad)
    return _serialize(bad)


@router.post("/{bad_habit_id}/log")
def log_occurrence(
    bad_habit_id: str,
    payload: BadHabitLogOccurrence,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    bad = (
        db.query(models.BadHabit)
        .filter(models.BadHabit.id == bad_habit_id, models.BadHabit.user_id == user.id)
        .first()
    )
    if not bad:
        return {"ok": False}
    bad.last_occurrence_at = now_utc()
    if payload.note:
        bad.note = payload.note
    db.commit()
    return {"ok": True}


class BadHabitUpdate(BaseModel):
    label: str | None = None
    note: str | None = None
    # Date de la dernière fois ('YYYY-MM-DD') : sans elle, le compteur part de
    # la création de l'entrée, ce qui est faux pour une habitude qu'on traîne
    # depuis longtemps ou qu'on a arrêtée avant de l'enregistrer ici.
    last_occurrence_date: str | None = None


@router.put("/{bad_habit_id}")
def update_bad_habit(
    bad_habit_id: str,
    payload: BadHabitUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    bad = (
        db.query(models.BadHabit)
        .filter(models.BadHabit.id == bad_habit_id, models.BadHabit.user_id == user.id)
        .first()
    )
    if not bad:
        raise HTTPException(status_code=404, detail="Habitude introuvable")

    if payload.label is not None:
        bad.label = payload.label
    if payload.note is not None:
        bad.note = payload.note
    if payload.last_occurrence_date:
        try:
            jour = date.fromisoformat(payload.last_occurrence_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Date attendue au format AAAA-MM-JJ")
        bad.last_occurrence_at = datetime(jour.year, jour.month, jour.day, tzinfo=timezone.utc)

    db.commit()
    db.refresh(bad)
    return _serialize(bad)


@router.delete("/{bad_habit_id}", status_code=204)
def delete_bad_habit(
    bad_habit_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Supprime une habitude à perdre. Il n'existait aucun moyen de le faire :
    une habitude ajoutée par erreur restait affichée pour toujours."""
    bad = (
        db.query(models.BadHabit)
        .filter(models.BadHabit.id == bad_habit_id, models.BadHabit.user_id == user.id)
        .first()
    )
    if not bad:
        raise HTTPException(status_code=404, detail="Habitude introuvable")
    db.delete(bad)
    db.commit()
    return None
