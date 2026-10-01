"""Réduction progressive d'une consommation (tabac/alcool) : la limite du
jour baisse d'un pas fixe chaque semaine complète écoulée depuis la date de
départ, jusqu'à 0. Même principe que effective_habit_target
(habit_progress.py) : recalculée à chaque lecture, jamais stockée figée —
sinon il faudrait une tâche planifiée pour la tenir à jour.

Les jours sont découpés en UTC, comme le reste de l'app (date_key,
today_count du tableau de bord).
"""
import math
from datetime import date, datetime

from .. import models


def _date(valeur) -> date | None:
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    return date.fromisoformat(str(valeur)[:10])


def reduction_configuree(substance: "models.Substance") -> bool:
    return bool(substance.reduction_start_value and substance.reduction_step_per_week)


def semaines_ecoulees(substance: "models.Substance", today: date) -> int:
    """Semaines complètes depuis reduction_start_date (0 sans date, ou si la
    date de départ est dans le futur)."""
    depart = _date(substance.reduction_start_date)
    if depart is None:
        return 0
    return max(0, (today - depart).days // 7)


def paliers_total(substance: "models.Substance") -> int | None:
    """Nombre de paliers jusqu'à 0 : ceil(départ / pas). None sans réduction."""
    if not reduction_configuree(substance):
        return None
    return max(1, math.ceil(substance.reduction_start_value / substance.reduction_step_per_week - 1e-9))


def limite_du_jour(substance: "models.Substance", today: date) -> float | None:
    """max(0, départ − pas × semaines complètes écoulées) ; None sans réduction."""
    if not reduction_configuree(substance):
        return None
    brut = substance.reduction_start_value - substance.reduction_step_per_week * semaines_ecoulees(substance, today)
    return max(0.0, round(brut, 2))


def palier_courant(substance: "models.Substance", today: date) -> int | None:
    """Palier en cours, de 1 (semaine de départ) à paliers_total (borné : il
    ne dépasse pas le dernier palier une fois la limite à 0)."""
    total = paliers_total(substance)
    if total is None:
        return None
    return min(total, semaines_ecoulees(substance, today) + 1)
