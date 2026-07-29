from datetime import datetime, timezone
from typing import List

from sqlalchemy.orm import Session

from .. import models


def _days_between(a: datetime, b: datetime) -> int:
    """Jours pleins entre deux datetimes (b - a), toujours >= 0."""
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    delta = b - a
    return max(0, delta.days)


def current_streak_days(db: Session, substance: models.Substance, now: datetime = None) -> int:
    """Nombre de jours pleins depuis la dernière ConsumptionEntry de type
    'consumption' pour cette substance. S'il n'y a jamais eu de consommation
    enregistrée, on compte depuis la création du compte (proxy raisonnable
    de 'depuis que je suis sur l'app')."""
    now = now or datetime.now(timezone.utc)

    last_entry = (
        db.query(models.ConsumptionEntry)
        .filter(
            models.ConsumptionEntry.substance_id == substance.id,
            models.ConsumptionEntry.type == models.EntryType.CONSUMPTION,
        )
        .order_by(models.ConsumptionEntry.occurred_at.desc())
        .first()
    )
    reference = last_entry.occurred_at if last_entry else substance.user.created_at
    return _days_between(reference, now)


def personal_best_days(db: Session, substance: models.Substance, now: datetime = None) -> int:
    """Le plus long intervalle jamais tenu entre deux consommations
    successives (ou avant la première / depuis la dernière), en jours."""
    now = now or datetime.now(timezone.utc)

    entries = (
        db.query(models.ConsumptionEntry)
        .filter(
            models.ConsumptionEntry.substance_id == substance.id,
            models.ConsumptionEntry.type == models.EntryType.CONSUMPTION,
        )
        .order_by(models.ConsumptionEntry.occurred_at.asc())
        .all()
    )

    if not entries:
        return _days_between(substance.user.created_at, now)

    checkpoints: List[datetime] = [substance.user.created_at] + [e.occurred_at for e in entries] + [now]
    best = 0
    for i in range(1, len(checkpoints)):
        best = max(best, _days_between(checkpoints[i - 1], checkpoints[i]))
    return best
