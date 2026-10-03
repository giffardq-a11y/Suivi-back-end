"""Sessions d'aide au craving : sérialisation et statistiques.

Rien n'est stocké en dehors des sessions elles-mêmes : les statistiques
sont recalculées à chaque lecture (même principe que substance_progress.py).
La fenêtre « N derniers jours » est découpée en UTC comme le reste de l'app ;
la répartition par heure et par jour de semaine est exprimée dans le fuseau
de l'utilisateur (comme les heures des envies du module Humeur).
"""
from collections import Counter
from datetime import datetime

from .. import models, schemas
from .common import aware

ISSUES_TERMINEES = {
    models.CravingOutcome.RESISTE.value,
    models.CravingOutcome.CEDE.value,
    models.CravingOutcome.ABANDONNE.value,
}
TOP_DECLENCHEURS = 5


def duree_secondes(c: models.Craving) -> int | None:
    if c.ended_at is None or c.started_at is None:
        return None
    return max(0, int((aware(c.ended_at) - aware(c.started_at)).total_seconds()))


def serialiser(c: models.Craving) -> schemas.CravingOut:
    return schemas.CravingOut(
        id=c.id, substance_id=c.substance_id,
        started_at=aware(c.started_at),
        ended_at=aware(c.ended_at) if c.ended_at else None,
        planned_seconds=c.planned_seconds,
        intensity_start=c.intensity_start, intensity_end=c.intensity_end,
        trigger=c.trigger_label, outcome=c.outcome, note=c.note, entry_id=c.entry_id,
        duration_seconds=duree_secondes(c),
    )


def _moyenne(valeurs: list) -> float | None:
    return round(sum(valeurs) / len(valeurs), 2) if valeurs else None


def statistiques(sessions: list, fuseau, jours: int, substance_id: str | None = None) -> schemas.CravingStats:
    issues = Counter(c.outcome for c in sessions)
    resistes = issues[models.CravingOutcome.RESISTE.value]
    cedes = issues[models.CravingOutcome.CEDE.value]
    tranchees = resistes + cedes

    durees = [d for d in (duree_secondes(c) for c in sessions if c.outcome in ISSUES_TERMINEES) if d is not None]
    declencheurs = Counter(c.trigger_label for c in sessions if c.trigger_label)
    par_heure = [0] * 24
    par_jour = [0] * 7
    for c in sessions:
        local: datetime = aware(c.started_at).astimezone(fuseau)
        par_heure[local.hour] += 1
        par_jour[local.weekday()] += 1

    return schemas.CravingStats(
        substance_id=substance_id, jours=jours, total=len(sessions),
        resistes=resistes, cedes=cedes,
        abandonnes=issues[models.CravingOutcome.ABANDONNE.value],
        en_cours=issues[models.CravingOutcome.EN_COURS.value],
        taux_resistance=round(resistes / tranchees, 3) if tranchees else None,
        intensite_moyenne_debut=_moyenne([c.intensity_start for c in sessions]),
        intensite_moyenne_fin=_moyenne([c.intensity_end for c in sessions if c.intensity_end is not None]),
        duree_moyenne_secondes=_moyenne(durees),
        top_declencheurs=[
            schemas.DeclencheurCompte(nom=nom, nombre=n)
            for nom, n in sorted(declencheurs.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_DECLENCHEURS]
        ],
        par_heure=par_heure, par_jour_semaine=par_jour,
    )
