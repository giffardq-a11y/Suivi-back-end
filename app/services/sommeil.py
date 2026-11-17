"""Nuit retenue par jour de réveil : partagé par /health/history et le tableau
commun, pour que la même nuit ne soit jamais comptée deux fois."""
from typing import Iterable

from .. import models

SOURCE_IMPORT = "health_connect"


def nuit_retenue_par_jour(nuits: Iterable["models.SleepLog"]) -> dict[str, "models.SleepLog"]:
    """Une nuit par jour de réveil (date_key) : si la même nuit existe saisie
    à la main et importée, on garde l'importée (elle porte les phases) ; à
    source égale, la plus longue (une sieste ne remplace pas la nuit)."""
    def rang(n: "models.SleepLog"):
        return (n.source == SOURCE_IMPORT, n.duration_min or 0)

    retenues: dict[str, models.SleepLog] = {}
    for n in nuits:
        deja = retenues.get(n.date_key)
        if deja is None or rang(n) > rang(deja):
            retenues[n.date_key] = n
    return retenues
