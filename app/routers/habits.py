from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, is_same_day, today_key
from ..services.habit_progress import effective_habit_target, is_progressive

router = APIRouter(prefix="/habits", tags=["habits"])


class ProgressiveIn(BaseModel):
    startValue: float
    targetValue: float
    rhythm: str | None = None  # 'lent' | 'normal' | 'rapide'
    # Durée explicite, prioritaire sur `rhythm` (plan hebdomadaire importé).
    weeks: int | None = None
    unit: str | None = None  # "km / semaine", "pompes / semaine"...


class HabitCreate(BaseModel):
    label: str
    type: str | None = None
    target: str | None = None
    note: str | None = None
    weekly_target: int = 7
    # "0,3" = lundi et jeudi ; None = tous les jours.
    days_of_week: str | None = None
    tracking_mode: str = "sessions"  # 'sessions' | 'volume'
    session_quantity: float | None = None
    weekly_volume_target: float | None = None
    unit: str | None = None
    linked_activity: str | None = None
    progressive: ProgressiveIn | None = None
    scheduled_time: str | None = None
    notifications_enabled: bool = False


class HabitOut(BaseModel):
    id: str
    label: str
    target: str | None
    percent: int
    progressive: bool
    linked_activity: str | None
    # Progression de la semaine : sans ces champs, l'app ne peut afficher
    # qu'un pourcentage sans savoir ce qu'il compte (2 séances sur 3 ? 600 m
    # sur 1000 ?), ni proposer de valider plusieurs fois.
    tracking_mode: str = "sessions"
    weekly_target: int = 7
    done_this_week: int = 0
    weekly_volume_target: float | None = None
    volume_this_week: float | None = None
    session_quantity: float | None = None
    unit: str | None = None
    days_of_week: str | None = None
    scheduled_today: bool = True


def _week_start(now: datetime) -> datetime:
    # Lundi 00:00 — même convention que le front (voir buildCycleCalendar /
    # dateKey dans mockData.js : "lundi = 0").
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def jours_actifs(habit: models.Habit) -> list[int] | None:
    """Jours où l'habitude s'applique (0 = lundi), None = tous les jours."""
    if not habit.days_of_week:
        return None
    jours = [int(j) for j in str(habit.days_of_week).split(",") if j.strip().isdigit()]
    return sorted({j for j in jours if 0 <= j <= 6}) or None


def _serialize(db: Session, habit: models.Habit) -> HabitOut:
    maintenant = datetime.now(timezone.utc)
    week_start = _week_start(maintenant)
    logs_semaine = (
        db.query(models.HabitLog)
        .filter(models.HabitLog.habit_id == habit.id, models.HabitLog.occurred_at >= week_start)
        .all()
    )
    done_this_week = len(logs_semaine)

    if habit.tracking_mode == "volume" and habit.weekly_volume_target:
        # Une validation sans quantité vaut la quantité d'une séance type, à
        # défaut 0 : mieux vaut sous-compter que gonfler la progression.
        volume = sum((log.quantity if log.quantity is not None else (habit.session_quantity or 0))
                     for log in logs_semaine)
        percent = min(100, round(100 * volume / habit.weekly_volume_target))
    else:
        volume = None
        cible = habit.weekly_target or 7
        percent = min(100, round(100 * done_this_week / cible)) if cible else 0

    jours = jours_actifs(habit)
    return HabitOut(
        id=habit.id,
        label=habit.label,
        target=effective_habit_target(habit, maintenant),
        percent=percent,
        progressive=is_progressive(habit),
        linked_activity=habit.linked_activity,
        tracking_mode=habit.tracking_mode or "sessions",
        weekly_target=habit.weekly_target or 7,
        done_this_week=done_this_week,
        weekly_volume_target=habit.weekly_volume_target,
        volume_this_week=round(volume, 1) if volume is not None else None,
        session_quantity=habit.session_quantity,
        unit=habit.unit,
        days_of_week=habit.days_of_week,
        scheduled_today=(jours is None or maintenant.weekday() in jours),
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
        note=payload.note,
        weekly_target=payload.weekly_target,
        linked_activity=payload.linked_activity,
        scheduled_time=payload.scheduled_time,
        notifications_enabled=payload.notifications_enabled,
        days_of_week=payload.days_of_week,
        tracking_mode=payload.tracking_mode or "sessions",
        session_quantity=payload.session_quantity,
        weekly_volume_target=payload.weekly_volume_target,
        unit=payload.unit,
    )
    if payload.progressive:
        habit.habit_type = payload.type
        habit.progressive_rhythm = payload.progressive.rhythm
        habit.progressive_weeks = payload.progressive.weeks
        habit.progressive_unit = payload.progressive.unit
        habit.progressive_start_value = payload.progressive.startValue
        habit.progressive_target_value = payload.progressive.targetValue
        habit.progressive_start_date = now_utc()
        # Au palier 0 (à l'instant de la création), la cible affichée est la
        # valeur de départ formatée — même comportement que effectiveHabitTarget
        # côté mock juste après avoir posé habit.progressive.
        habit.target = effective_habit_target(habit, habit.progressive_start_date)

    db.add(habit)
    db.commit()
    db.refresh(habit)
    return _serialize(db, habit)


class HabitUpdate(BaseModel):
    """Modification d'une habitude existante. Tout est optionnel : un champ
    absent n'est pas touché, ce qui permet de ne régler que les jours ou que
    le volume sans renvoyer toute l'habitude."""
    label: str | None = None
    target: str | None = None
    note: str | None = None
    weekly_target: int | None = None
    days_of_week: str | None = None
    tracking_mode: str | None = None
    session_quantity: float | None = None
    weekly_volume_target: float | None = None
    unit: str | None = None
    scheduled_time: str | None = None
    notifications_enabled: bool | None = None


@router.put("/{habit_id}", response_model=HabitOut)
def update_habit(
    habit_id: str,
    payload: HabitUpdate,
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

    if payload.tracking_mode and payload.tracking_mode not in ("sessions", "volume"):
        raise HTTPException(status_code=422, detail="tracking_mode doit valoir 'sessions' ou 'volume'")

    for champ, valeur in payload.model_dump(exclude_unset=True).items():
        # Une habitude progressive recalcule sa cible toute seule : un
        # `target` saisi à la main l'écraserait jusqu'au prochain palier.
        if champ == "target" and is_progressive(habit):
            continue
        setattr(habit, champ, valeur)

    db.commit()
    db.refresh(habit)
    return _serialize(db, habit)


class HabitLogCreate(BaseModel):
    note: str | None = None
    # Quantité faite (500 m, 20 min...) pour une habitude suivie en volume.
    quantity: float | None = None


@router.post("/{habit_id}/log", status_code=201)
def log_habit(
    habit_id: str,
    payload: HabitLogCreate | None = None,
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

    log = models.HabitLog(
        habit_id=habit.id,
        occurred_at=datetime.now(timezone.utc),
        note=(payload.note or None) if payload else None,
        quantity=(payload.quantity if payload else None),
    )
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
    # les HabitLog associés. Les replanifications et raisons de saut n'ont
    # pas de relationship() : sans ces 2 lignes, Postgres refuse la
    # suppression (clé étrangère) — SQLite, lui, ne vérifie pas.
    db.query(models.HabitReschedule).filter(models.HabitReschedule.habit_id == habit.id).delete()
    db.query(models.HabitSkipReason).filter(models.HabitSkipReason.habit_id == habit.id).delete()
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
