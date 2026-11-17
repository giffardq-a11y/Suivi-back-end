"""Ce qu'un compte neuf contient d'office, partagé entre l'inscription
(routers/auth.py) et « tout effacer » (services/reset.py) : un compte effacé
doit repartir comme un compte neuf, avec les mêmes modules actifs.
"""
from sqlalchemy.orm import Session

from .. import models
from ..modules import est_actif


def creer_defauts(db: Session, user: models.User) -> None:
    """Ajoute (sans valider) les contenus par défaut du compte.

    Les 2 substances « de base » (alcool/tabac) sont un pilier de l'app
    (streaks Accueil, économies, bénéfices santé) — sans elles un compte se
    retrouverait avec un dashboard vide et l'Accueil ne pourrait rien
    enregistrer. Coût par défaut neutre, éditable ensuite dans Paramètres
    (voir routers/settings.py). Créées seulement si le module addictions est
    actif (toujours vrai tant qu'un client n'envoie pas `modules`).

    À l'appelant de faire le commit."""
    if est_actif(user, "addictions"):
        db.add_all([
            models.Substance(
                user_id=user.id, label="Alcool", unit="1 verre",
                category=models.SubstanceCategory.ALCOHOL, unit_cost=6.0, usual_frequency_per_day=1.0,
            ),
            models.Substance(
                user_id=user.id, label="Tabac", unit="1 cigarette",
                category=models.SubstanceCategory.TOBACCO, unit_cost=0.6, usual_frequency_per_day=1.0,
            ),
        ])
