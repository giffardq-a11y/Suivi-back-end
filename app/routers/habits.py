from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/habits", tags=["habits"])


@router.post("/{habit_id}/log", status_code=201)
def log_habit(
    habit_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    habit = (
        db.query(models.Habit)
        .filter(models.Habit.id == habit_id, models.Habit.user_id == user.id)
        .first()
    )
    if not habit:
        raise HTTPException(status_code=404, detail="Habitude introuvable")

    log = models.HabitLog(habit_id=habit.id, occurred_at=datetime.now(timezone.utc))
    db.add(log)
    db.commit()
    return {"ok": True, "habit_id": habit.id, "logged_at": log.occurred_at}
