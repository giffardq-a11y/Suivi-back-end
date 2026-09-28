"""Point d'entrée unique entre les modules et le module Personnage.

Chaque action notable des autres modules passe par ici, jamais directement
par services/stats.py : ce fichier garantit qu'un échec du moteur de
personnage ne fait JAMAIS échouer l'action d'origine. Toute exception est
journalisée, la session est remise en état (rollback) et l'appel renvoie
None / []. Les routeurs appellent donc ces fonctions APRÈS avoir commité leur
propre écriture : le rollback ne peut défaire que le travail du moteur.

Sans personnage créé, rien n'est attribué (stats.award renvoie None).

Contrat : **idempotence par (source, source_id)** (par stat, dans
stats.award). Certains événements sont constatés à la lecture et non à la
création (envie résistée : on ne le sait qu'après 2 h ; mois terminé sous le
budget : on ne le sait qu'au mois suivant ; journée sans tabac : le
lendemain), donc le même événement peut être signalé plusieurs fois ; il ne
rapporte qu'une fois.

Fonctions :
  - evenement(db, user, source, source_id, payload)  une action du barème
    (config.json, clé « bareme »). Le jour de l'action, qui porte les
    plafonds journaliers, se lit dans payload['dateKey'] (défaut : aujourd'hui).
  - action(db, user, genre, objet)  un objet enregistré (course, séance,
    pesée, pas...) traduit en événements par stats.evenements_de, puis les
    habitudes cochées automatiquement dans la foulée.
  - retrait(db, user, source, source_id)  log supprimé : ses points partent,
    le niveau et l'XP restent.
  - habitudes(db, user)  validations d'habitudes récentes et séries.
  - constater(db, user)  constats à la lecture : journées sans tabac/alcool,
    paliers de santé, habitudes cochées automatiquement.

Sources émises (barème complet dans app/data/personnage/config.json) :
  - 'hydration_goal'       objectif d'eau du jour atteint (source_id = 'YYYY-MM-DD')
  - 'sleep_7h'             nuit de 7 h ou plus (source_id = id de la nuit)
  - 'mood_entry'           humeur ou journal de gratitude noté (id de l'entrée)
  - 'craving_resisted'     envie notée puis résistée (id de l'envie)
  - 'budget_month_under'   mois terminé sous le budget total (source_id = 'YYYY-MM')
  - 'savings_pot_achieved' objectif de cagnotte atteint (id de la cagnotte)
  - 'goal_completed'       objectif atteint (id de l'objectif)
  - 'cards_reviewed'       tranche de 10 cartes révisées ('YYYY-MM-DD:n')
  - 'card_mastered'        carte arrivée en dernière boîte (id de la carte)
  - 'partner_encouragement' encouragement envoyé au proche (id du message)
  - via action() : 'run', 'run_pace_record', 'cardio', 'technical_sport',
    'flexibility_session', 'strength_session', 'strength_volume',
    'strength_pr', 'steps_goal', 'weight_progress'
  - via habitudes() / constater() : 'habit_done', 'habit_streak',
    'tobacco_free_day', 'alcohol_free_day', 'health_milestone'
"""
import logging

from sqlalchemy.orm import Session

from .. import models
from . import stats
from .common import now_utc

_log = logging.getLogger("uvicorn.error")


def _isoler(nom: str, db: Session, fonction, *args, defaut=None, **kwargs):
    try:
        return fonction(*args, **kwargs)
    except Exception:
        _log.exception("Personnage : échec de %s (action d'origine conservée)", nom)
        try:
            db.rollback()
        except Exception:
            pass
        return defaut


def evenement(db: Session, user: models.User, source: str, source_id: str, payload: dict | None = None) -> dict | None:
    """Signale une action au module Personnage (voir la docstring du module)."""
    payload = payload or {}
    return _isoler(source, db, stats.award, db, user, source, source_id, payload.get("dateKey"), payload)


def action(db: Session, user: models.User, genre: str, objet) -> list[dict]:
    """Objet enregistré (genre : 'course', 'autre_sport', 'souplesse',
    'muscu', 'pas', 'pesee') : ses événements, puis les habitudes cochées
    automatiquement par l'enregistrement (habitudes « sport », etc.)."""
    evts = _isoler(genre, db, stats.evenements_de, db, user, genre, objet, defaut=[])
    resultats = []
    for source, source_id, jour, payload in evts:
        r = evenement(db, user, source, source_id, {**payload, "dateKey": jour})
        if r and r.get("points_par_stat"):
            resultats.append({"source": source, **r})
    resultats += habitudes(db, user)
    return resultats


def retrait(db: Session, user: models.User, source: str, source_id: str) -> None:
    """Log supprimé : retire ses événements (points), sans baisser le niveau."""
    _isoler(f"retrait {source}", db, stats.retirer, db, user, source, source_id)


def habitudes(db: Session, user: models.User) -> list[dict]:
    """Validations d'habitudes des deux derniers jours (UTC) et séries."""
    from datetime import timedelta
    depuis = (now_utc() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return _isoler("habitudes", db, stats.constater_habitudes, db, user, depuis, defaut=[])


def constater(db: Session, user: models.User) -> list[dict]:
    """Constats faits à la lecture (tableau de bord, personnage)."""
    if _isoler("lecture personnage", db, stats.personnage, db, user) is None:
        return []
    resultats = _isoler("sobriété", db, stats.constater_sobriete, db, user, defaut=[])
    return resultats + habitudes(db, user)
