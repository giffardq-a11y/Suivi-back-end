from datetime import date, datetime, timezone
from typing import List

from sqlalchemy.orm import Session

from .. import models
from .common import debut_suivi


def _days_between(a: datetime, b: datetime) -> int:
    """Jours pleins entre deux datetimes (b - a), toujours >= 0."""
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    delta = b - a
    return max(0, delta.days)


def reference_sans_consommation(substance: models.Substance) -> datetime:
    """Point de départ d'une série quand aucune consommation n'est enregistrée.

    La date d'arrêt déclarée prime : elle passe avant le début du suivi, sinon
    quelqu'un qui a arrêté six mois avant d'installer l'app repartirait de
    zéro. Sans date d'arrêt valable, on compte depuis le début du suivi
    (création du compte, ou dernière remise à zéro de la progression)."""
    if substance.quit_date:
        try:
            jour = date.fromisoformat(substance.quit_date)
            return datetime(jour.year, jour.month, jour.day, tzinfo=timezone.utc)
        except ValueError:
            pass
    return debut_suivi(substance.user)


def current_streak_days(db: Session, substance: models.Substance, now: datetime = None) -> int:
    """Nombre de jours pleins depuis la dernière ConsumptionEntry de type
    'consumption' pour cette substance. S'il n'y a jamais eu de consommation
    enregistrée, on compte depuis la date d'arrêt, à défaut depuis le début du
    suivi (voir reference_sans_consommation)."""
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
    reference = last_entry.occurred_at if last_entry else reference_sans_consommation(substance)
    return _days_between(reference, now)


def personal_best_days(db: Session, substance: models.Substance, now: datetime = None) -> int:
    """Le plus long intervalle jamais tenu entre deux consommations
    successives (ou avant la première / depuis la dernière), en jours.

    Sans consommation, le record est la série en cours (même référence : la
    date d'arrêt si elle est valable, sinon le début du suivi) : après une
    remise à zéro, il n'affiche donc plus l'ancienneté du compte.

    Avec des consommations, tout l'historique compte. Le premier intervalle
    part de la date d'arrêt si elle précède la première consommation (arrêt
    déclaré avant d'installer l'app, ou jour de la remise à zéro), sinon du
    début du suivi : déclarer une nouvelle date d'arrêt après une rechute ne
    doit pas effacer un ancien record."""
    now = now or datetime.now(timezone.utc)

    def _aware(d: datetime) -> datetime:
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    entries = (
        db.query(models.ConsumptionEntry)
        .filter(
            models.ConsumptionEntry.substance_id == substance.id,
            models.ConsumptionEntry.type == models.EntryType.CONSUMPTION,
        )
        .order_by(models.ConsumptionEntry.occurred_at.asc())
        .all()
    )
    instants = sorted(_aware(e.occurred_at) for e in entries)
    if not instants:
        return current_streak_days(db, substance, now=now)

    reference = _aware(reference_sans_consommation(substance))
    depart = reference if reference <= instants[0] else min(_aware(debut_suivi(substance.user)), instants[0])

    checkpoints: List[datetime] = [depart] + instants + [now]
    best = 0
    for i in range(1, len(checkpoints)):
        best = max(best, _days_between(checkpoints[i - 1], checkpoints[i]))
    # Jamais en dessous de la série en cours (qui peut partir d'une dernière
    # consommation antérieure à la date d'arrêt).
    return max(best, current_streak_days(db, substance, now=now))
