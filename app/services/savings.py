from datetime import datetime, timezone
from typing import Tuple

from sqlalchemy.orm import Session

from .. import models
from .streaks import current_streak_days, _days_between


def _substance_savings(db: Session, substance: models.Substance, now: datetime, days_back: int = 0) -> float:
    """economies = unit_cost * jours_sans_consommation * frequence_habituelle,
    évalué 'days_back' jours dans le passé pour permettre le delta hebdo
    (spec §3.3). On ne descend jamais sous 0 jour clampé au streak actuel."""
    days = current_streak_days(db, substance, now=now)
    days = max(0, days - days_back)
    return substance.unit_cost * days * substance.usual_frequency_per_day


def compute_savings(db: Session, user: models.User, now: datetime = None) -> Tuple[float, float]:
    """Retourne (total, delta_de_la_semaine) en devise de l'utilisateur
    (on suppose une devise unique pour simplifier l'agrégation, cf. currency
    par substance dans le modèle pour le multi-devise à affiner plus tard)."""
    now = now or datetime.now(timezone.utc)

    total = 0.0
    total_week_ago = 0.0
    for substance in user.substances:
        total += _substance_savings(db, substance, now, days_back=0)
        total_week_ago += _substance_savings(db, substance, now, days_back=7)

    return round(total, 2), round(total - total_week_ago, 2)
