from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, is_same_day, today_key

router = APIRouter(prefix="/habits", tags=["habits"])


class HabitCreate(BaseModel):
    label: str
    target: str | None = None
    weekly_target: int = 7
    linked_activity: str | None = None
    scheduled_time: str | None = None
    notifications_enabled: bool = False


class HabitOut(BaseModel):
    id: str
    label: str
    target: str | None
    percent: int
    progressive: bool
    linked_activity: str | None


def _week_start(now: datetime) -> datetime:
    # Lundi 00:00 — même convention que le front (voir buildCycleCalendar /
    # dateKey dans mockData.js : "lundi = 0").
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _serialize(db: Session, habit: models.Habit) -> HabitOut:
    week_start = _week_start(datetime.now(timezone.utc))
    done_this_week = (
        db.query(models.HabitLog)
        .filter(models.HabitLog.habit_id == habit.id, models.HabitLog.occurred_at >= week_start)
        .count()
    )
    target = habit.weekly_target or 7
    percent = min(100, round(100 * done_this_week / target)) if target else 0

    return HabitOut(
        id=habit.id,
        label=habit.label,
        target=habit.target,
        percent=percent,
        # Les habitudes "progressives" (palier qui évolue dans le temps,
        # voir effectiveHabitTarget côté mock) ne sont pas encore modélisées
        # côté serveur — toujours False ici pour l'instant.
        progressive=False,
        linked_activity=habit.linked_activity,
    )


@router.get("", response_model=list[HabitOut])
def list_habits(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    habits = (
        db.query(models.Habit)
        .filter(models.Habit.user_id == user.id, models.Habit.active.is_(True))
        .all()
    )
    return [_serialize(db, h) for h in habits]


@router.post("", status_code=201, response_model=HabitOut)
def create_habit(
    payload: HabitCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    habit = models.Habit(
        user_id=user.id,
        key=payload.label.lower().replace(" ", "_"),
        label=payload.label,
        target=payload.target,
        weekly_target=payload.weekly_target,
        linked_activity=payload.linked_activity,
        scheduled_time=payload.scheduled_time,
        notifications_enabled=payload.notifications_enabled,
    )
    db.add(habit)
    db.commit()
    db.refresh(habit)
    return _serialize(db, habit)


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


@router.delete("/{habit_id}", status_code=204)
def delete_habit(
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

    # cascade="all, delete-orphan" sur Habit.logs supprime automatiquement
    # les HabitLog associés.
    db.delete(habit)
    db.commit()


class SkipReasonCreate(BaseModel):
    reason: str


class RescheduleCreate(BaseModel):
    newTime: str


@router.delete("/{habit_id}/log", status_code=204)
def unlog_habit(
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
    if habit.linked_activity:
        raise HTTPException(status_code=400, detail="Cette habitude se met à jour automatiquement, elle ne se décoche pas à la main.")

    today_log = (
        db.query(models.HabitLog)
        .filter(models.HabitLog.habit_id == habit.id)
        .all()
    )
    now = now_utc()
    for log in today_log:
        if is_same_day(log.occurred_at, now):
            db.delete(log)
            break
    db.commit()


@router.get("/reminders/pending")
def get_pending_reminders(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    current_minutes = now.hour * 60 + now.minute
    today = today_key(now)

    habits = (
        db.query(models.Habit)
        .filter(models.Habit.user_id == user.id, models.Habit.active.is_(True), models.Habit.notifications_enabled.is_(True))
        .filter(models.Habit.scheduled_time.isnot(None))
        .all()
    )

    reschedules = {
        r.habit_id for r in db.query(models.HabitReschedule).filter(models.HabitReschedule.date_key == today).all()
    }
    skips = {
        s.habit_id for s in db.query(models.HabitSkipReason).filter(models.HabitSkipReason.date_key == today).all()
    }

    pending = []
    for h in habits:
        hh, mm = (int(x) for x in h.scheduled_time.split(":"))
        if hh * 60 + mm > current_minutes:
            continue
        done_today = any(is_same_day(l.occurred_at, now) for l in h.logs)
        if done_today or h.id in reschedules or h.id in skips:
            continue
        pending.append({"id": h.id, "label": h.label, "scheduled_time": h.scheduled_time})

    return pending


@router.post("/{habit_id}/reminders/reschedule")
def reschedule_habit_reminder(
    habit_id: str,
    payload: RescheduleCreate,
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

    today = today_key()
    db.query(models.HabitReschedule).filter(
        models.HabitReschedule.habit_id == habit_id, models.HabitReschedule.date_key == today,
    ).delete()
    db.add(models.HabitReschedule(habit_id=habit_id, date_key=today, new_time=payload.newTime))
    db.commit()
    return {"ok": True}


@router.post("/{habit_id}/reminders/skip")
def log_habit_skip_reason(
    habit_id: str,
    payload: SkipReasonCreate,
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

    today = today_key()
    db.query(models.HabitSkipReason).filter(
        models.HabitSkipReason.habit_id == habit_id, models.HabitSkipReason.date_key == today,
    ).delete()
    db.add(models.HabitSkipReason(habit_id=habit_id, date_key=today, reason=payload.reason, occurred_at=now_utc()))
    db.commit()
    return {"ok": True}
