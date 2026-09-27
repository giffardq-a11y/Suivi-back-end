"""Point d'entrée unique entre les modules et le futur module Personnage.

Le module Personnage (XP, caractéristiques hp / spi / wil..., voir
specs/tanren-rpg/PROMPT-module-personnage.md) n'existe pas encore. Plutôt que
d'écrire de l'XP dans chaque routeur puis de tout reprendre au moment de le
brancher, chaque action notable appelle ici `evenement(...)`, qui ne fait
rien pour l'instant. Le jour venu, seule cette fonction sera branchée sur
stats.award, avec le barème et les plafonds journaliers du cahier des
charges (ex. hydration_goal : hp +1, 1 par jour).

Contrat à respecter par l'implémentation future : **idempotence par
(source, source_id)**. Certains événements sont constatés à la lecture et non
à la création (envie résistée : on ne le sait qu'après 2 h ; mois terminé
sous le budget : on ne le sait qu'au mois suivant), donc le même événement
peut être signalé plusieurs fois. C'est à stats.award de n'attribuer les
points qu'une fois, ce que le cahier exige de toute façon (« points de
personnage attribués une seule fois »).

Sources émises aujourd'hui :
  - 'hydration_goal'       objectif d'eau du jour atteint (source_id = 'YYYY-MM-DD')
  - 'sleep_7h'             nuit de 7 h ou plus (source_id = id de la nuit)
  - 'mood_entry'           humeur ou journal de gratitude noté (id de l'entrée)
  - 'craving_resisted'     envie notée puis résistée (id de l'envie)
  - 'budget_month_under'   mois terminé sous le budget total (source_id = 'YYYY-MM')
  - 'savings_pot_achieved' objectif de cagnotte atteint (id de la cagnotte)
"""
from sqlalchemy.orm import Session

from .. import models


def evenement(db: Session, user: models.User, source: str, source_id: str, payload: dict | None = None) -> None:
    """Signale une action au module Personnage. Ne fait rien pour l'instant :
    sera branchée plus tard sur stats.award (voir la docstring du module)."""
    return None
