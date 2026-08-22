from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, to_ms, from_ms, date_key, today_key

router = APIRouter(prefix="/cycle", tags=["cycle"])

PHASE_INFO = {
    "menstruelle": {
        "label": "Règles",
        "description": "La muqueuse utérine s’évacue — œstrogène et progestérone au plus bas. Fatigue et crampes sont fréquentes ces jours-là.",
    },
    "folliculaire": {
        "label": "Phase folliculaire",
        "description": "L’œstrogène remonte progressivement, les follicules ovariens se développent. Énergie et humeur tendent à s’améliorer.",
    },
    "ovulation": {
        "label": "Ovulation",
        "description": "Pic de LH déclenchant la libération d’un ovule — fenêtre de fertilité la plus élevée du cycle.",
    },
    "luteale": {
        "label": "Phase lutéale",
        "description": "La progestérone domine après l’ovulation. Symptômes prémenstruels (SPM) possibles en fin de phase si pas de grossesse.",
    },
}


class CycleSettingsUpdate(BaseModel):
    enabled: bool | None = None
    avgCycleLengthDays: int | None = None
    avgPeriodLengthDays: int | None = None


class PeriodDateBody(BaseModel):
    dateMs: int | None = None


class FlowIntensityBody(BaseModel):
    dateMs: int
    intensity: str


class ContraceptionUpdate(BaseModel):
    enabled: bool | None = None
    method: str | None = None
    reminderTime: str | None = None


def _get_or_create_settings(db: Session, user: models.User) -> models.CycleSettings:
    settings = db.query(models.CycleSettings).filter(models.CycleSettings.user_id == user.id).first()
    if not settings:
        settings = models.CycleSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _phase_for_date(date_dt: datetime, settings: models.CycleSettings, logs: list[models.CycleLog]) -> str | None:
    if not logs:
        return None
    sorted_logs = sorted(logs, key=lambda l: l.start_date)
    ref_log = None
    for log in sorted_logs:
        start = log.start_date if log.start_date.tzinfo else log.start_date.replace(tzinfo=timezone.utc)
        if start <= date_dt:
            ref_log = log
        else:
            break
    if not ref_log:
        return None

    start = ref_log.start_date if ref_log.start_date.tzinfo else ref_log.start_date.replace(tzinfo=timezone.utc)
    days_since_start = (date_dt - start).days + 1
    day_of_cycle = ((days_since_start - 1) % settings.avg_cycle_length_days) + 1
    ovulation_day = max(1, settings.avg_cycle_length_days - 14)

    if day_of_cycle <= settings.avg_period_length_days:
        return "menstruelle"
    if day_of_cycle < ovulation_day - 1:
        return "folliculaire"
    if day_of_cycle <= ovulation_day + 1:
        return "ovulation"
    return "luteale"


def _serialize_overview(db: Session, user: models.User, settings: models.CycleSettings) -> dict:
    if not settings.enabled:
        return {"enabled": False}

    logs = db.query(models.CycleLog).filter(models.CycleLog.user_id == user.id).order_by(models.CycleLog.start_date.desc()).all()
    last_log = logs[0] if logs else None
    now = now_utc()

    day_of_cycle = None
    phase = None
    predicted_next_period = None
    fertile_window_start = None
    fertile_window_end = None

    if last_log:
        start = last_log.start_date if last_log.start_date.tzinfo else last_log.start_date.replace(tzinfo=timezone.utc)
        days_since_start = (now - start).days + 1
        day_of_cycle = ((days_since_start - 1) % settings.avg_cycle_length_days) + 1

        ovulation_day = max(1, settings.avg_cycle_length_days - 14)
        if day_of_cycle <= settings.avg_period_length_days:
            phase = "menstruelle"
        elif day_of_cycle < ovulation_day - 1:
            phase = "folliculaire"
        elif day_of_cycle <= ovulation_day + 1:
            phase = "ovulation"
        else:
            phase = "luteale"

        predicted_next_period = start + timedelta(days=settings.avg_cycle_length_days)
        ovulation_date = start + timedelta(days=ovulation_day)
        fertile_window_start = ovulation_date - timedelta(days=5)
        fertile_window_end = ovulation_date + timedelta(days=1)

    today = today_key()
    flow_today = (
        db.query(models.CycleFlowEntry)
        .filter(models.CycleFlowEntry.user_id == user.id, models.CycleFlowEntry.date_key == today)
        .first()
    )

    recent_logs = []
    for l in logs[:6]:
        start = l.start_date if l.start_date.tzinfo else l.start_date.replace(tzinfo=timezone.utc)
        end = l.end_date
        if end and not end.tzinfo:
            end = end.replace(tzinfo=timezone.utc)
        recent_logs.append({
            "id": l.id,
            "start_date": to_ms(start),
            "end_date": to_ms(end),
            "duration_days": ((end - start).days + 1) if end else None,
        })

    return {
        "enabled": True,
        "avg_cycle_length_days": settings.avg_cycle_length_days,
        "avg_period_length_days": settings.avg_period_length_days,
        "current_log_open": bool(last_log and not last_log.end_date),
        "day_of_cycle": day_of_cycle,
        "phase": phase,
        "phase_info": PHASE_INFO.get(phase) if phase else None,
        "flow_today": flow_today.intensity if flow_today else None,
        "contraception": {
            "enabled": settings.contraception_enabled,
            "method": settings.contraception_method or "",
            "reminderTime": settings.contraception_reminder_time or "",
        },
        "predicted_next_period": to_ms(predicted_next_period),
        "fertile_window_start": to_ms(fertile_window_start),
        "fertile_window_end": to_ms(fertile_window_end),
        "recent_logs": recent_logs,
    }


@router.get("")
def get_cycle_overview(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    settings = _get_or_create_settings(db, user)
    return _serialize_overview(db, user, settings)


@router.put("/settings")
def update_cycle_settings(
    payload: CycleSettingsUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    settings = _get_or_create_settings(db, user)
    patch = payload.model_dump(exclude_unset=True)
    if "enabled" in patch:
        settings.enabled = patch["enabled"]
    if "avgCycleLengthDays" in patch:
        settings.avg_cycle_length_days = patch["avgCycleLengthDays"]
    if "avgPeriodLengthDays" in patch:
        settings.avg_period_length_days = patch["avgPeriodLengthDays"]
    db.commit()
    return _serialize_overview(db, user, settings)


@router.post("/period/start")
def log_period_start(
    payload: PeriodDateBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    settings = _get_or_create_settings(db, user)
    start = from_ms(payload.dateMs) if payload.dateMs else now_utc()
    db.add(models.CycleLog(user_id=user.id, start_date=start, end_date=None))
    db.commit()
    return _serialize_overview(db, user, settings)


@router.post("/period/end")
def log_period_end(
    payload: PeriodDateBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    settings = _get_or_create_settings(db, user)
    open_log = (
        db.query(models.CycleLog)
        .filter(models.CycleLog.user_id == user.id, models.CycleLog.end_date.is_(None))
        .order_by(models.CycleLog.start_date.desc())
        .first()
    )
    if open_log:
        open_log.end_date = from_ms(payload.dateMs) if payload.dateMs else now_utc()
        db.commit()
    return _serialize_overview(db, user, settings)


@router.get("/calendar")
def get_cycle_calendar(
    monthOffset: int = 0,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    settings = _get_or_create_settings(db, user)
    logs = db.query(models.CycleLog).filter(models.CycleLog.user_id == user.id).all()
    if not settings.enabled or not logs:
        return {"days": [], "monthLabel": "", "hasData": False}

    now = datetime.now(timezone.utc)
    target_month = now.month - 1 + monthOffset
    year = now.year + target_month // 12
    month = target_month % 12 + 1
    first_of_month = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        days_in_month = (datetime(year + 1, 1, 1, tzinfo=timezone.utc) - first_of_month).days
    else:
        days_in_month = (datetime(year, month + 1, 1, tzinfo=timezone.utc) - first_of_month).days
    first_weekday = first_of_month.weekday()  # lundi = 0

    flow_entries = {
        f.date_key: f.intensity
        for f in db.query(models.CycleFlowEntry).filter(models.CycleFlowEntry.user_id == user.id).all()
    }

    days = [None] * first_weekday
    for d in range(1, days_in_month + 1):
        date_dt = datetime(year, month, d, tzinfo=timezone.utc)
        key = date_key(date_dt)
        days.append({
            "day": d,
            "dateMs": to_ms(date_dt),
            "phase": _phase_for_date(date_dt, settings, logs),
            "flowIntensity": flow_entries.get(key),
        })

    month_label = first_of_month.strftime("%B %Y")
    return {"days": days, "monthLabel": month_label, "hasData": True}


@router.post("/flow")
def log_flow_intensity(
    payload: FlowIntensityBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    settings = _get_or_create_settings(db, user)
    key = date_key(from_ms(payload.dateMs))
    existing = (
        db.query(models.CycleFlowEntry)
        .filter(models.CycleFlowEntry.user_id == user.id, models.CycleFlowEntry.date_key == key)
        .first()
    )
    if existing:
        existing.intensity = payload.intensity
    else:
        db.add(models.CycleFlowEntry(user_id=user.id, date_key=key, intensity=payload.intensity))
    db.commit()
    return _serialize_overview(db, user, settings)


@router.put("/contraception")
def update_contraception_reminder(
    payload: ContraceptionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    settings = _get_or_create_settings(db, user)
    patch = payload.model_dump(exclude_unset=True)
    if "enabled" in patch:
        settings.contraception_enabled = patch["enabled"]
    if "method" in patch:
        settings.contraception_method = patch["method"]
    if "reminderTime" in patch:
        settings.contraception_reminder_time = patch["reminderTime"]
    db.commit()
    return _serialize_overview(db, user, settings)
