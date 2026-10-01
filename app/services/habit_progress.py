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

def jours_actifs(habit) -> list[int] | None:
    """Jours où l'habitude s'applique (0 = lundi), None = tous les jours.

    Partagé par le router habits et le fil de la journée : une habitude qui
    n'est pas prévue aujourd'hui ne doit apparaître ni dans la liste du jour,
    ni dans le fil, sans quoi elle compte comme ratée tous les autres jours."""
    valeur = getattr(habit, "days_of_week", None)
    if not valeur:
        return None
    jours = [int(j) for j in str(valeur).split(",") if j.strip().isdigit()]
    return sorted({j for j in jours if 0 <= j <= 6}) or None


# ---------- Carte d'habitude de l'Accueil : semaine, série, semaine du plan ----------

def _aware(dt: datetime) -> datetime:
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def jours_valides(logs) -> set:
    """Dates (date UTC) où l'habitude a au moins une validation."""
    return {_aware(l.occurred_at).date() for l in logs}


def bande_semaine(habit, jours_faits: set, now: datetime, hebdo: bool) -> list[str]:
    """Les 7 pastilles lundi → dimanche de la semaine en cours.

    'done' : validée ce jour-là ; 'today' : aujourd'hui, pas encore faite ;
    'missed' : jour prévu passé sans validation (seulement pour une habitude
    quotidienne — une habitude visée 2 fois par semaine n'a pas de jour
    « raté ») ; 'off' : jour où elle ne s'applique pas ; 'todo' : à venir, ou
    jour libre d'une habitude hebdomadaire."""
    from datetime import timedelta
    jours = jours_actifs(habit)
    lundi = now.date() - timedelta(days=now.weekday())
    etats = []
    for i in range(7):
        d = lundi + timedelta(days=i)
        if d in jours_faits:
            etats.append("done")
        elif d == now.date():
            etats.append("today")
        elif jours is not None and i not in jours:
            etats.append("off")
        elif d < now.date() and not hebdo:
            etats.append("missed")
        else:
            etats.append("todo")
    return etats


def serie_jours(habit, jours_faits: set, now: datetime) -> int:
    """Jours prévus consécutifs validés, en remontant depuis aujourd'hui.

    Aujourd'hui pas encore fait ne casse pas la série (la journée n'est pas
    finie) ; les jours où l'habitude ne s'applique pas sont sautés sans la
    casser — une natation du mardi et du jeudi garde sa série le mercredi."""
    from datetime import timedelta
    jours = jours_actifs(habit)
    d = now.date()
    if d not in jours_faits:
        d -= timedelta(days=1)
    serie = 0
    for _ in range(3650):
        if jours is not None and d.weekday() not in jours and d not in jours_faits:
            d -= timedelta(days=1)
            continue
        if d not in jours_faits:
            break
        serie += 1
        d -= timedelta(days=1)
    return serie


def serie_semaines(logs, habit, now: datetime) -> int:
    """Semaines consécutives où l'objectif hebdomadaire a été atteint (pour
    une habitude visée moins de 7 fois par semaine ou en volume). La semaine
    en cours compte si elle est déjà atteinte, sinon elle ne casse rien."""
    from datetime import timedelta
    from collections import defaultdict
    par_semaine = defaultdict(float)
    for l in logs:
        d = _aware(l.occurred_at).date()
        lundi = d - timedelta(days=d.weekday())
        if habit.tracking_mode == "volume" and habit.weekly_volume_target:
            par_semaine[lundi] += l.quantity if l.quantity is not None else (habit.session_quantity or 0)
        else:
            par_semaine[lundi] += 1
    cible = (habit.weekly_volume_target if habit.tracking_mode == "volume" and habit.weekly_volume_target
             else (habit.weekly_target or 7))
    semaine = now.date() - timedelta(days=now.weekday())
    if par_semaine.get(semaine, 0) < cible:
        semaine -= timedelta(days=7)
    serie = 0
    while par_semaine.get(semaine, 0) >= cible and serie < 520:
        serie += 1
        semaine -= timedelta(days=7)
    return serie


def semaine_du_plan(habit, now: datetime) -> tuple[int | None, int | None]:
    """(semaine en cours, nombre total) pour une habitude progressive à durée
    explicite (plan importé, ex. « Semaine 3/15 ») ; (None, None) sinon."""
    if not habit.progressive_weeks or not habit.progressive_start_date:
        return None, None
    ecoule = (now - _aware(habit.progressive_start_date)).days
    courante = max(1, ecoule // 7 + 1)
    return min(courante, habit.progressive_weeks), habit.progressive_weeks
