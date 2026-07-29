from datetime import datetime, timezone
from typing import Tuple

from sqlalchemy.orm import Session

from .. import models


def compute_reward_budget(db: Session, user: models.User, real_savings: float, now: datetime = None) -> Tuple[float, float, float]:
    """Retourne (multiplicateur, budget_recompense, solde_disponible).

    Règles spec §3.4 :
      poids_reussis = somme des weight des Goal avec completed_at non nul
                       et "en cours" (ici : simplement non nul — la notion
                       d'objectif récurrent qui expire en fin de période
                       sera ajoutée avec le modèle de récurrence, pas encore
                       présent dans ce premier flow).
      multiplicateur = 1 + 0.25 * poids_reussis
      budget_recompense = round(economies_reelles * multiplicateur)
      solde_disponible = budget_recompense - somme(cost_at_purchase)
    """
    now = now or datetime.now(timezone.utc)

    poids_reussis = sum(
        g.weight for g in user.goals if g.completed_at is not None
    )
    multiplier = 1 + 0.25 * poids_reussis
    reward_budget = round(real_savings * multiplier)

    spent = sum(p.cost_at_purchase for p in user.reward_purchases)
    available_balance = reward_budget - spent

    return multiplier, reward_budget, available_balance
