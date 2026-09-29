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
  - rattrapage(db, user)  à la création du personnage : tout l'historique
    rejoué à travers les mêmes règles (stats.rattraper).
  - resumer(resultats)  agrège une liste de résultats (evenement/habitudes/
    action/constater) en un seul résumé pour la réponse HTTP (champ
    « personnage » : toast mobile « +40 XP · Force »), ou None si rien à
    afficher.

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


def rattrapage(db: Session, user: models.User) -> dict | None:
    """Historique existant rejoué à la création du personnage (idempotent)."""
    return _isoler("rattrapage", db, stats.rattraper, db, user)


def constater(db: Session, user: models.User) -> list[dict]:
    """Constats faits à la lecture (tableau de bord, personnage)."""
    if _isoler("lecture personnage", db, stats.personnage, db, user) is None:
        return []
    resultats = _isoler("sobriété", db, stats.constater_sobriete, db, user, defaut=[])
    return resultats + habitudes(db, user)


def resumer(resultats: list[dict | None]) -> dict | None:
    """Agrège une liste de résultats de `stats.award` (tels que renvoyés par
    `evenement()`, `habitudes()`, `action()` ou `constater()`) en un seul
    résumé destiné au mobile — le petit toast « +40 XP · Force » affiché
    après une action qui rapporte de l'XP au personnage.

    Méthode d'agrégation (un routeur peut passer aussi bien un résultat
    unique `[evenement(...)]` qu'une liste de plusieurs événements) :
      - `xp` : somme des `xp` de chaque résultat ;
      - `points_par_stat` : fusion par stat, points sommés (arrondi à 2
        décimales) ;
      - `level_up` : vrai si au moins un résultat de la liste l'est ;
      - `new_rank` : celui du dernier résultat de la liste qui en a un (les
        résultats sont dans l'ordre chronologique des événements traités,
        donc c'est le rang le plus récemment atteint) ;
      - `chests` / `quests_done` : concaténés dans l'ordre.
    Les résultats `None` ou `falsy` (pas de personnage, source inconnue,
    plafond déjà atteint) sont ignorés. Renvoie `None` si la liste est vide,
    ne contient que des `None`, ou si rien de notable n'en ressort (aucune
    XP, aucun coffre, aucune quête, pas de montée de niveau) : pas de toast à
    afficher plutôt qu'un toast « +0 XP ».
    """
    xp_total = 0
    points_par_stat: dict[str, float] = {}
    level_up = False
    new_rank = None
    chests: list = []
    quests_done: list = []
    vu = False
    for r in resultats or []:
        if not r:
            continue
        vu = True
        xp_total += r.get("xp") or 0
        for stat, points in (r.get("points_par_stat") or {}).items():
            points_par_stat[stat] = round(points_par_stat.get(stat, 0) + points, 2)
        if r.get("level_up"):
            level_up = True
        if r.get("new_rank"):
            new_rank = r["new_rank"]
        chests.extend(r.get("chests") or [])
        quests_done.extend(r.get("quests_done") or [])

    if not vu or not (xp_total or points_par_stat or level_up or chests or quests_done):
        return None

    return {
        "points_par_stat": points_par_stat,
        "xp": xp_total,
        "level_up": level_up,
        "new_rank": new_rank,
        "chests": chests,
        "quests_done": quests_done,
    }
