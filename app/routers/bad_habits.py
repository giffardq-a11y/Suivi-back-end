from fastapi import APIRouter, Depends
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
