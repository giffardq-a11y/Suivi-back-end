"""Habitudes "progressives" (paliers évolutifs) — traduction de
effectiveHabitTarget / formatHabitTarget / PROGRESSIVE_RHYTHM_WEEKS côté
mockData.js. Le palier affiché est recalculé à la lecture à partir de la
date de départ, jamais stocké figé — sinon il faudrait une tâche planifiée
pour le tenir à jour.
"""
from datetime import datetime

from .. import models

PROGRESSIVE_RHYTHM_WEEKS = {"lent": 8, "normal": 4, "rapide": 2}


def is_progressive(habit: "models.Habit") -> bool:
    return bool(habit.progressive_rhythm or habit.progressive_weeks)

HABIT_TYPE_FORMATTER = {
    "sport": lambda v: f"{v}x / semaine",
    "meditation": lambda v: f"{v} min / jour",
    "hydratation": lambda v: f"{v}L / jour",
    "sommeil": lambda v: f"{v}h minimum",
}


def format_habit_target(habit_type: str | None, value: float, unit: str | None = None) -> str:
    # Une unité explicite (plan importé : "km / semaine", "pompes / semaine")
    # prime sur le format déduit du type, qui ne connaît que 4 cas.
    if unit:
        return f"{value:g} {unit}"
    fmt = HABIT_TYPE_FORMATTER.get(habit_type or "")
    return fmt(value) if fmt else str(value)


def effective_habit_target(habit: "models.Habit", now: datetime) -> str | None:
    """Cible affichée pour cette habitude : la valeur figée (`habit.target`)
    si elle n'est pas progressive, sinon la valeur du palier courant,
    interpolée entre valeur de départ et valeur cible selon le rythme
    choisi (lent/normal/rapide = 8/4/2 semaines)."""
    if not is_progressive(habit):
        return habit.target

    # Durée explicite (plan hebdomadaire importé) sinon rythme prédéfini.
    total_weeks = habit.progressive_weeks or PROGRESSIVE_RHYTHM_WEEKS.get(
        habit.progressive_rhythm, PROGRESSIVE_RHYTHM_WEEKS["normal"]
    )
    start_date = habit.progressive_start_date
    if start_date and start_date.tzinfo is None:
        from datetime import timezone
        start_date = start_date.replace(tzinfo=timezone.utc)
    weeks_elapsed = max(0.0, (now - start_date).total_seconds() / (7 * 24 * 3600)) if start_date else 0.0
    progress = min(1.0, weeks_elapsed / total_weeks) if total_weeks > 0 else 1.0

    start_value = habit.progressive_start_value or 0
    target_value = habit.progressive_target_value or 0
    raw_value = start_value + (target_value - start_value) * progress
    decimals = habit.habit_type == "hydratation" or (habit.progressive_unit or "").startswith("km")
    rounded = round(raw_value * 10) / 10 if decimals else round(raw_value)
    return format_habit_target(habit.habit_type, rounded, habit.progressive_unit)
