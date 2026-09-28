"""Moteur du module Personnage : points de stat, XP, niveaux, rangs, paliers
de santé (cahier : mobile/docs/tanren-rpg/PROMPT-module-personnage.md §3-4).

Tout le paramétrage (univers, classes, coefficients, barème, plafonds,
paliers, rangs) est dans app/data/personnage/config.json ; ce fichier ne
contient que la mécanique.

Principes tenus ici :
  - rien n'est attribué tant que l'utilisateur n'a pas créé son personnage ;
  - idempotence par (source, source_id, stat) : une action signalée deux fois
    (constat à la lecture, rattrapage rejoué...) ne rapporte qu'une fois ;
  - plafonds en points de base par source, stat et jour d'origine de
    l'action (date_key), pas par jour de calcul : le rattrapage respecte donc
    les mêmes plafonds que le direct ;
  - l'XP ne punit jamais : ni level ni total_xp ne redescendent, même quand
    un log supprimé retire ses points (retirer).

Sources d'actions : les routeurs passent par services/personnage_hooks.py,
qui isole toute erreur du moteur de l'action d'origine. Les fonctions
evenements_* traduisent un objet enregistré (course, séance...) en
événements ; le rattrapage (rattraper) les réutilise telles quelles.
"""
import json
import logging
import math
import unicodedata
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..modules import est_actif
from .common import aware, date_key as _date_key, now_utc, today_key

_log = logging.getLogger("uvicorn.error")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "personnage" / "config.json"


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def stats_cles() -> list[str]:
    return config()["stats"]


# ---------- Univers, classes, archétypes ----------

def univers(cle: str) -> dict | None:
    return config()["univers"].get(cle)


def classe(universe: str, class_key: str) -> dict | None:
    u = univers(universe)
    if u is None:
        return None
    return next((c for c in u["classes"] if c["cle"] == class_key), None)


def archetype(perso: models.Character) -> dict:
    c = classe(perso.universe, perso.class_key)
    # Classe disparue de la config (renommée) : archétype neutre plutôt
    # qu'une erreur, les points restent attribués avec un coefficient 1.
    if c is None:
        return {"nom": "?", "coefficients": {s: 1.0 for s in stats_cles()},
                "base": {s: 10 for s in stats_cles()}, "passif": {"sources": [], "bonus_pct": 0, "libelle": ""}}
    return config()["archetypes"][c["archetype"]]


# ---------- Niveaux et rangs ----------

def cout_niveau(n: int) -> int:
    """XP pour passer du niveau n à n+1."""
    p = config()["niveaux"]
    return round(p["base"] * n ** p["exposant"])


def niveau_pour_xp(total_xp: int) -> tuple[int, int, int]:
    """(niveau, XP depuis le début du niveau, XP du niveau entier)."""
    niveau, reste = 1, max(0, total_xp)
    while reste >= cout_niveau(niveau):
        reste -= cout_niveau(niveau)
        niveau += 1
    return niveau, reste, cout_niveau(niveau)


def rang_pour_niveau(level: int) -> dict:
    rangs = sorted(config()["rangs"], key=lambda r: r["niveau_min"])
    courant = rangs[0]
    for r in rangs:
        if level >= r["niveau_min"]:
            courant = r
    return courant


def personnage(db: Session, user: models.User) -> models.Character | None:
    return db.query(models.Character).filter(models.Character.user_id == user.id).first()


# ---------- Attribution ----------

def _points_bruts(regle: dict, payload: dict) -> dict[str, float]:
    points = regle.get("points")
    if points == "payload":
        ratio = float(payload.get("ratio", 1) or 1)
        return {s: float(v) * ratio for s, v in (payload.get("points") or {}).items()}
    if "paliers" in regle:
        return {s: float(v) for s, v in (regle["paliers"].get(str(payload.get("palier"))) or {}).items()}
    if "par" in regle:
        quantite = float(payload.get(regle["par"]) or 0)
        # Unités entières seulement (5,4 km = 5 points) : 1e-9 pour que 30 min
        # divisées par 10 ne tombent pas à 2,999...
        unites = math.floor(quantite / regle.get("diviseur", 1) + 1e-9)
        return {s: float(v) * unites for s, v in points.items()}
    return {s: float(v) for s, v in (points or {}).items()}


def _semaine_de(jour: str) -> list[str]:
    d = date.fromisoformat(jour)
    lundi = d - timedelta(days=d.weekday())
    return [(lundi + timedelta(days=i)).isoformat() for i in range(7)]


def _deja_attribue(db: Session, user_id: str, source: str, stat: str, jours: list[str]) -> float:
    total = (
        db.query(func.coalesce(func.sum(models.StatEvent.base_points), 0.0))
        .filter(models.StatEvent.user_id == user_id, models.StatEvent.source == source,
                models.StatEvent.stat == stat, models.StatEvent.date_key.in_(jours))
        .scalar()
    )
    return float(total or 0)


def _crediter(perso: models.Character, xp: int) -> dict:
    """Ajoute l'XP, les éclats, et monte le niveau. L'XP déjà versée pour des
    événements retirés depuis (xp_avance) est reprise d'abord."""
    reprise = min(perso.xp_avance or 0, xp)
    perso.xp_avance = (perso.xp_avance or 0) - reprise
    net = xp - reprise
    ancien_total = perso.total_xp or 0
    ancien_niveau = perso.level or 1
    ancien_rang = rang_pour_niveau(ancien_niveau)["rang"]
    par_eclat = config()["xp_par_eclat"]
    perso.total_xp = ancien_total + net
    perso.shards = (perso.shards or 0) + perso.total_xp // par_eclat - ancien_total // par_eclat
    perso.level = max(ancien_niveau, niveau_pour_xp(perso.total_xp)[0])
    nouveau_rang = rang_pour_niveau(perso.level)
    return {
        "xp": net,
        "level": perso.level,
        "level_up": perso.level > ancien_niveau,
        "new_rank": ({"rank": nouveau_rang["rang"], "name": nouveau_rang["nom"]}
                     if nouveau_rang["rang"] > ancien_rang else None),
    }


def award(db: Session, user: models.User, source: str, source_id, date_key: str | None = None,
          payload: dict | None = None, *, commit: bool = True) -> dict | None:
    """Attribue les points d'une action. None si l'utilisateur n'a pas de
    personnage (ou source inconnue du barème). Sinon :
    {points_par_stat, xp, level, level_up, new_rank, milestones, chests,
    quests_done}.

    Bonus : capacité passive de la classe + bonus d'équipement de la stat
    (déjà plafonné à +15 % par services/equipement.bonus_equipement),
    additionnés ; le total va dans stat_events.bonus_pct. Coffres (rang,
    série) et quêtes du jour : services/equipement.apres_award."""
    from . import equipement
    perso = personnage(db, user)
    if perso is None:
        return None
    regle = config()["bareme"].get(source)
    if regle is None:
        _log.warning("Personnage : source inconnue du barème : %s", source)
        return None
    payload = payload or {}
    jour = date_key or payload.get("dateKey") or today_key()
    source_id = str(source_id)
    arch = archetype(perso)
    passif = arch["passif"]
    bonus = float(passif["bonus_pct"]) if source in passif.get("sources", []) else 0.0
    xp_par_point = config()["xp_par_point"]
    bonus_equip = equipement.bonus_equipement(db, perso)

    points_par_stat: dict[str, float] = {}
    xp_total = 0
    for stat, brut in _points_bruts(regle, payload).items():
        if brut <= 0 or stat not in stats_cles():
            continue
        existe = db.query(models.StatEvent.id).filter(
            models.StatEvent.user_id == user.id, models.StatEvent.source == source,
            models.StatEvent.source_id == source_id, models.StatEvent.stat == stat,
        ).first()
        if existe:
            continue
        base = brut
        if regle.get("plafond_evenement") is not None:
            base = min(base, float(regle["plafond_evenement"]))
        if regle.get("plafond_jour") is not None:
            base = min(base, float(regle["plafond_jour"]) - _deja_attribue(db, user.id, source, stat, [jour]))
        if regle.get("plafond_semaine") is not None:
            base = min(base, float(regle["plafond_semaine"]) - _deja_attribue(db, user.id, source, stat, _semaine_de(jour)))
        if base <= 0:
            continue
        mult = float(arch["coefficients"].get(stat, 1.0))
        bonus_stat = bonus + bonus_equip.get(stat, 0.0)
        points = round(base * mult * (1 + bonus_stat / 100), 4)
        xp = round(points * xp_par_point)
        db.add(models.StatEvent(
            user_id=user.id, source=source, source_id=source_id, stat=stat, base_points=base,
            class_mult=mult, bonus_pct=bonus_stat, points=points, xp=xp, date_key=jour, created_at=now_utc(),
        ))
        points_par_stat[stat] = round(points, 2)
        xp_total += xp

    milestones = [payload["milestone"]] if source == "health_milestone" and payload.get("milestone") else []
    if not points_par_stat:
        return {"points_par_stat": {}, "xp": 0, "level": perso.level, "level_up": False,
                "new_rank": None, "milestones": [], "chests": [], "quests_done": []}
    db.flush()
    ancien_rang = rang_pour_niveau(perso.level or 1)["rang"]
    resultat = {"points_par_stat": points_par_stat, **_crediter(perso, xp_total), "milestones": milestones}
    resultat.update(equipement.apres_award(db, user, perso, source, source_id, jour, payload, ancien_rang))
    if commit:
        db.commit()
    return resultat


def retirer(db: Session, user: models.User, source: str, source_id, *, commit: bool = True) -> int:
    """Supprime les événements d'un log supprimé. Les points de stat partent
    avec eux ; level et total_xp restent (l'XP ne punit jamais), mais l'XP
    correspondante passe en xp_avance pour ne pas être regagnée gratuitement
    si l'action est ressaisie. Renvoie le nombre d'événements supprimés."""
    evenements = db.query(models.StatEvent).filter(
        models.StatEvent.user_id == user.id, models.StatEvent.source == source,
        models.StatEvent.source_id == str(source_id),
    ).all()
    if not evenements:
        return 0
    perso = personnage(db, user)
    if perso is not None:
        perso.xp_avance = (perso.xp_avance or 0) + sum(e.xp or 0 for e in evenements)
    for e in evenements:
        db.delete(e)
    if commit:
        db.commit()
    return len(evenements)


# ---------- Traduction des actions en événements ----------
# Chaque fonction renvoie une liste de (source, source_id, date_key, payload),
# à passer à award. Les records comparent aux actions strictement
# antérieures : le résultat est le même en direct et au rattrapage.

def _normaliser(texte: str | None) -> str:
    t = unicodedata.normalize("NFKD", (texte or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _jour(dt: datetime) -> str:
    return _date_key(aware(dt))


def _nombre(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def evenements_course(db: Session, run: models.Run) -> list[tuple]:
    jour = _jour(run.occurred_at)
    evts = [("run", run.id, jour, {"distanceKm": run.distance_km})]
    if (run.distance_km or 0) >= 1 and (run.duration_min or 0) > 0:
        allure = run.duration_min / run.distance_km
        precedentes = db.query(models.Run).filter(
            models.Run.user_id == run.user_id, models.Run.id != run.id,
            models.Run.occurred_at < run.occurred_at, models.Run.distance_km >= 1,
        ).all()
        allures = [r.duration_min / r.distance_km for r in precedentes if (r.duration_min or 0) > 0]
        # Première course : pas de record (rien à battre).
        if allures and allure < min(allures):
            evts.append(("run_pace_record", run.id, jour, {"paceMinPerKm": round(allure, 2)}))
    return evts


def evenements_autre_sport(db: Session, log: models.OtherSportLog) -> list[tuple]:
    jour = _jour(log.occurred_at)
    libelle = _normaliser(log.sport_label)
    sports = config()["sports"]
    if any(m in libelle for m in sports["souplesse"]):
        return [("flexibility_session", log.id, jour, {})]
    evts = [("cardio", log.id, jour, {"durationMin": log.duration_min})]
    if any(m in libelle for m in sports["techniques"]):
        evts.append(("technical_sport", log.id, jour, {}))
    return evts


def evenements_souplesse(db: Session, seance: models.FlexibilitySession) -> list[tuple]:
    return [("flexibility_session", seance.id, _jour(seance.occurred_at), {})]


def _series_faites(exercice: dict) -> list[dict]:
    # Série sans champ 'done' (saisie rapide) : comptée comme faite.
    return [s for s in (exercice.get("sets") or []) if isinstance(s, dict) and s.get("done", True)]


def _max_par_exercice(seance: models.StrengthSession) -> dict[str, float]:
    maxi: dict[str, float] = {}
    for ex in seance.exercises or []:
        if not isinstance(ex, dict) or not ex.get("name"):
            continue
        for s in _series_faites(ex):
            poids = _nombre(s.get("weight"))
            if poids > maxi.get(ex["name"], 0):
                maxi[ex["name"]] = poids
    return maxi


def evenements_muscu(db: Session, seance: models.StrengthSession) -> list[tuple]:
    jour = _jour(seance.occurred_at)
    evts = [("strength_session", seance.id, jour, {})]
    volume = sum(
        _nombre(s.get("reps")) * _nombre(s.get("weight"))
        for ex in (seance.exercises or []) if isinstance(ex, dict)
        for s in _series_faites(ex)
    )
    if volume > 0:
        evts.append(("strength_volume", seance.id, jour, {"volumeKg": round(volume)}))
    actuels = _max_par_exercice(seance)
    if actuels:
        precedentes = db.query(models.StrengthSession).filter(
            models.StrengthSession.user_id == seance.user_id, models.StrengthSession.id != seance.id,
            models.StrengthSession.occurred_at < seance.occurred_at,
        ).all()
        anciens: dict[str, float] = {}
        for p in precedentes:
            for nom, poids in _max_par_exercice(p).items():
                anciens[nom] = max(anciens.get(nom, 0), poids)
        for nom, poids in sorted(actuels.items()):
            # Record = battre une charge déjà soulevée : un exercice jamais
            # fait n'est pas un record.
            if anciens.get(nom, 0) > 0 and poids > anciens[nom]:
                evts.append(("strength_pr", f"{seance.id}:{nom}", jour, {"exercise": nom, "weight": poids}))
    return evts


def evenements_pas(db: Session, ligne: models.DailySteps) -> list[tuple]:
    if (ligne.steps or 0) >= config()["objectif_pas_defaut"]:
        return [("steps_goal", ligne.date_key, ligne.date_key, {"steps": ligne.steps})]
    return []


def evenements_cartes_du_jour(db: Session, user: models.User, jour: str) -> list[tuple]:
    """« 10 cartes révisées » : cartes distinctes revues dans la journée
    (même compte que le seuil de l'habitude Danois), une tranche par 10."""
    debut = datetime.fromisoformat(jour).replace(tzinfo=timezone.utc)
    evenements = db.query(models.FlashCardEvent).filter(
        models.FlashCardEvent.user_id == user.id,
        models.FlashCardEvent.occurred_at >= debut, models.FlashCardEvent.occurred_at < debut + timedelta(days=1),
    ).all()
    n = len({e.card_id for e in evenements})
    return [("cards_reviewed", f"{jour}:{i}", jour, {}) for i in range(1, n // 10 + 1)]


def evenements_carte_maitrisee(db: Session, revue: models.FlashCardReview, max_box: int) -> list[tuple]:
    if (revue.box or 0) >= max_box:
        quand = revue.last_reviewed_at or now_utc()
        return [("card_mastered", revue.card_id, _jour(quand), {})]
    return []


def evenements_pesee(db: Session, user: models.User, pesee: models.WeightEntry) -> list[tuple]:
    """Pesée plus proche de l'objectif de poids que la précédente."""
    profil = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
    if profil is None or not profil.weight_goal_kg:
        return []
    precedente = (
        db.query(models.WeightEntry)
        .filter(models.WeightEntry.user_id == user.id, models.WeightEntry.id != pesee.id,
                models.WeightEntry.occurred_at < pesee.occurred_at)
        .order_by(models.WeightEntry.occurred_at.desc())
        .first()
    )
    if precedente is None:
        return []
    cible = profil.weight_goal_kg
    if abs(pesee.weight_kg - cible) < abs(precedente.weight_kg - cible):
        return [("weight_progress", pesee.id, _jour(pesee.occurred_at), {})]
    return []


def evenements_de(db: Session, user: models.User, genre: str, objet) -> list[tuple]:
    """Aiguillage utilisé par personnage_hooks.action."""
    if genre == "course":
        return evenements_course(db, objet)
    if genre == "autre_sport":
        return evenements_autre_sport(db, objet)
    if genre == "souplesse":
        return evenements_souplesse(db, objet)
    if genre == "muscu":
        return evenements_muscu(db, objet)
    if genre == "pas":
        return evenements_pas(db, objet)
    if genre == "pesee":
        return evenements_pesee(db, user, objet)
    raise ValueError(f"genre d'action inconnu : {genre}")


def attribuer(db: Session, user: models.User, evenements: list[tuple], *, commit: bool = True) -> list[dict]:
    resultats = []
    for source, source_id, jour, payload in evenements:
        r = award(db, user, source, source_id, jour, payload, commit=commit)
        if r and r["points_par_stat"]:
            resultats.append({"source": source, **r})
    return resultats


# ---------- Habitudes : habitude tenue et séries ----------

def constater_habitudes(db: Session, user: models.User, depuis: datetime | None = None,
                        *, commit: bool = True) -> list[dict]:
    """Attribue « habitude tenue » à chaque validation (y compris celles
    cochées automatiquement par une séance, une nuit ou des révisions) et les
    paliers de série 7 / 30 / 100 jours consécutifs. Idempotent (source_id =
    id du log, ou habitude + début de série + longueur)."""
    if personnage(db, user) is None:
        return []
    habitudes = db.query(models.Habit).filter(models.Habit.user_id == user.id).all()
    series = set(config()["series_habitudes"])
    evts = []
    for h in habitudes:
        logs = db.query(models.HabitLog).filter(models.HabitLog.habit_id == h.id).all()
        if not logs:
            continue
        jours = sorted({_jour(l.occurred_at) for l in logs})
        limite = _date_key(aware(depuis)) if depuis is not None else None
        for l in logs:
            if depuis is None or aware(l.occurred_at) >= aware(depuis):
                evts.append(("habit_done", l.id, _jour(l.occurred_at), {}))
        debut, longueur, precedent = None, 0, None
        for j in jours:
            d = date.fromisoformat(j)
            if precedent is not None and d - precedent == timedelta(days=1):
                longueur += 1
            else:
                debut, longueur = j, 1
            precedent = d
            if longueur in series and (limite is None or j >= limite):
                evts.append(("habit_streak", f"{h.id}:{debut}:{longueur}", j, {"palier": longueur}))
    return attribuer(db, user, evts, commit=commit)


# ---------- Sobriété : journées sans et paliers de santé ----------

CATEGORIES_SOBRIETE = {models.SubstanceCategory.TOBACCO: "tobacco", models.SubstanceCategory.ALCOHOL: "alcohol"}


def _debut_arret(sub: models.Substance) -> datetime | None:
    if not sub.quit_date:
        return None
    try:
        j = date.fromisoformat(sub.quit_date)
    except ValueError:
        return None
    return datetime(j.year, j.month, j.day, tzinfo=timezone.utc)


def constater_sobriete(db: Session, user: models.User, now: datetime | None = None,
                       *, commit: bool = True) -> list[dict]:
    """Journées sans tabac / sans alcool (hp +3 chacune) et paliers de santé.

    Suivi réel seulement : chaque compte a d'office une substance Alcool et
    une Tabac (routers/auth.py). Sans date d'arrêt déclarée ni aucune
    consommation saisie, on ne sait pas si la personne a quelque chose à
    arrêter : rien n'est attribué, sinon tout non-fumeur gagnerait +6 PV par
    jour. Module « Alcool et tabac » désactivé : rien non plus.

    Journées sans : jours pleins (jusqu'à hier, UTC) sans consommation,
    comptés depuis la création du compte ou la date d'arrêt si elle est plus
    récente — pas avant l'installation de l'app, sinon une date d'arrêt
    reculée rapporterait des années de points d'un coup.

    Paliers : comptés depuis la dernière consommation, ou la date d'arrêt si
    elle est plus récente. Premier passage : bonus entier. Regagné après une
    rechute (consommation saisie) : reprise_ratio du bonus. Déplacer la date
    d'arrêt sans rechute ne fait rien regagner. Jamais retirés."""
    perso = personnage(db, user)
    if perso is None or not est_actif(user, "addictions"):
        return []
    now = aware(now or now_utc())
    hier = (now - timedelta(days=1)).date()
    conf_paliers = config()["paliers_sante"]
    evts, milestones = [], []

    for sub in db.query(models.Substance).filter(models.Substance.user_id == user.id).all():
        cle = CATEGORIES_SOBRIETE.get(sub.category)
        if cle is None:
            continue
        consos = sorted(
            (aware(e.occurred_at) for e in db.query(models.ConsumptionEntry).filter(
                models.ConsumptionEntry.substance_id == sub.id,
                models.ConsumptionEntry.type == models.EntryType.CONSUMPTION).all()),
        )
        arret = _debut_arret(sub)
        if arret is None and not consos:
            continue

        # --- Journées sans ---
        source_jour = f"{cle}_free_day"
        debut = aware(user.created_at or now).date()
        if arret is not None and arret.date() > debut:
            debut = arret.date()
        jours_conso = {c.date().isoformat() for c in consos}
        deja = {sid for (sid,) in db.query(models.StatEvent.source_id).filter(
            models.StatEvent.user_id == user.id, models.StatEvent.source == source_jour).all()}
        d, garde = debut, 0
        while d <= hier and garde < 3660:
            j = d.isoformat()
            sid = f"{sub.id}:{j}"
            if j not in jours_conso and sid not in deja:
                evts.append((source_jour, sid, j, {}))
            d += timedelta(days=1)
            garde += 1

        # --- Paliers ---
        derniere = consos[-1] if consos else None
        if derniere is not None and (arret is None or derniere >= arret):
            reference, rechute = derniere, True
        else:
            reference, rechute = arret, False
        ref_cle = reference.strftime("%Y-%m-%dT%H:%M")
        ecoule_h = (now - reference).total_seconds() / 3600
        obtenus = db.query(models.HealthMilestone).filter(
            models.HealthMilestone.user_id == user.id, models.HealthMilestone.substance == cle).all()
        for palier in conf_paliers.get(cle, []):
            if ecoule_h < palier["heures"]:
                continue
            memes = [m for m in obtenus if m.milestone_key == palier["cle"]]
            if any(m.quit_date == ref_cle for m in memes):
                continue
            if memes:
                if not rechute or ref_cle <= max(m.quit_date for m in memes):
                    continue
                ratio = float(conf_paliers["reprise_ratio"])
            else:
                ratio = 1.0
            atteint = reference + timedelta(hours=palier["heures"])
            db.add(models.HealthMilestone(user_id=user.id, substance=cle, milestone_key=palier["cle"],
                                          quit_date=ref_cle, earned_at=now, ratio=ratio))
            info = {"substance": cle, "key": palier["cle"], "label": palier["libelle"],
                    "text": palier["texte"], "ratio": ratio}
            milestones.append(info)
            evts.append(("health_milestone", f"{cle}:{palier['cle']}:{ref_cle}", _date_key(atteint),
                         {"points": palier["points"], "ratio": ratio, "milestone": info}))

    resultats = attribuer(db, user, evts, commit=False)
    if commit:
        db.commit()
    return resultats


# ---------- Rattrapage ----------

def rattraper(db: Session, user: models.User) -> dict:
    """Rejoue l'historique de l'utilisateur à travers les mêmes règles, avec
    la date d'origine de chaque action pour les plafonds. Idempotent : le
    relancer ne rapporte rien de plus. Appelé à la création du personnage."""
    if personnage(db, user) is None:
        return {"events": 0}
    evts: list[tuple] = []
    uid = user.id

    for r in db.query(models.Run).filter(models.Run.user_id == uid).all():
        evts += evenements_course(db, r)
    for o in db.query(models.OtherSportLog).filter(models.OtherSportLog.user_id == uid).all():
        evts += evenements_autre_sport(db, o)
    for f in db.query(models.FlexibilitySession).filter(models.FlexibilitySession.user_id == uid).all():
        evts += evenements_souplesse(db, f)
    for s in db.query(models.StrengthSession).filter(models.StrengthSession.user_id == uid).all():
        evts += evenements_muscu(db, s)
    for p in db.query(models.DailySteps).filter(models.DailySteps.user_id == uid).all():
        evts += evenements_pas(db, p)
    for w in db.query(models.WeightEntry).filter(models.WeightEntry.user_id == uid).all():
        evts += evenements_pesee(db, user, w)

    # Cartes : tranches de 10 par jour, cartes en dernière boîte.
    from ..routers.flashcards import MAX_BOX
    jours_cartes = {_jour(e.occurred_at) for e in
                    db.query(models.FlashCardEvent).filter(models.FlashCardEvent.user_id == uid).all()}
    for j in sorted(jours_cartes):
        evts += evenements_cartes_du_jour(db, user, j)
    for rv in db.query(models.FlashCardReview).filter(models.FlashCardReview.user_id == uid).all():
        evts += evenements_carte_maitrisee(db, rv, MAX_BOX)

    # Sommeil, humeur, journal.
    from ..routers.sleep import SEUIL_NUIT_COMPLETE_MIN
    for n in db.query(models.SleepLog).filter(models.SleepLog.user_id == uid).all():
        if (n.duration_min or 0) >= SEUIL_NUIT_COMPLETE_MIN:
            evts.append(("sleep_7h", n.id, n.date_key, {}))
    for m in db.query(models.MoodEntry).filter(models.MoodEntry.user_id == uid).all():
        evts.append(("mood_entry", m.id, _jour(m.occurred_at), {}))
    for g in db.query(models.GratitudeEntry).filter(models.GratitudeEntry.user_id == uid).all():
        evts.append(("mood_entry", g.id, g.date_key, {}))

    # Envies résistées (statut calculé à la lecture, voir routers/mood.py).
    from ..routers.mood import _envies_avec_statut
    for e, statut in _envies_avec_statut(db, user):
        if statut == "resisted":
            evts.append(("craving_resisted", e.id, _jour(e.occurred_at), {}))

    # Hydratation : objectif du jour atteint (objectif actuel appliqué à
    # l'historique, même approximation que GET /hydration/stats).
    if db.query(models.WaterLog.id).filter(models.WaterLog.user_id == uid).first():
        from ..routers.hydration import _logs, _objectif, _reglages, _totaux_par_jour
        objectif = _objectif(db, user, _reglages(db, user))
        for j, total in _totaux_par_jour(_logs(db, user)).items():
            if objectif and total >= objectif:
                evts.append(("hydration_goal", j, j, {}))

    # Objectifs atteints (terminés, ou liés à une métrique et à 100 %).
    from ..routers.goals import _serialize_goal
    maintenant = now_utc()
    for g in db.query(models.Goal).filter(models.Goal.user_id == uid).all():
        if g.completed_at is not None:
            evts.append(("goal_completed", g.id, _jour(g.completed_at), {}))
        elif _serialize_goal(db, user, g, maintenant)["completed"]:
            evts.append(("goal_completed", g.id, _date_key(maintenant), {}))

    for p in db.query(models.SavingsPot).filter(models.SavingsPot.user_id == uid,
                                                models.SavingsPot.achieved_at.isnot(None)).all():
        evts.append(("savings_pot_achieved", p.id, _jour(p.achieved_at), {}))
    for rm in db.query(models.PartnerReminder).filter(models.PartnerReminder.from_user_id == uid).all():
        evts.append(("partner_encouragement", rm.id, _jour(rm.created_at or maintenant), {}))

    evts.sort(key=lambda e: e[2])
    resultats = attribuer(db, user, evts, commit=False)
    resultats += constater_habitudes(db, user, None, commit=False)
    resultats += constater_sobriete(db, user, commit=False)
    db.commit()
    return {"events": len(resultats)}


# ---------- Lecture ----------

def valeurs_stats(db: Session, perso: models.Character, now: datetime | None = None) -> list[dict]:
    """Valeur affichée de chaque stat (§3.4) et indicateur de forme.

    Points pondérés recalculés avec le coefficient de la classe ACTUELLE
    (base × (1 + bonus passif et d'équipement) × coefficient) : changer de classe garde les
    points et ne change que la valeur affichée, comme le veut le cahier.
    Forme : points des 7 derniers jours comparés à la moyenne hebdomadaire
    des 4 semaines précédentes."""
    now = aware(now or now_utc())
    arch = archetype(perso)
    noms = univers(perso.universe)["stats"] if univers(perso.universe) else {}
    facteur = config()["valeur_stat"]["facteur"]
    seuil = config()["forme"]["seuil"]
    debut_recent = _date_key(now - timedelta(days=6))
    debut_avant = _date_key(now - timedelta(days=34))

    evenements = db.query(models.StatEvent).filter(models.StatEvent.user_id == perso.user_id).all()
    cumul = {s: 0.0 for s in stats_cles()}
    recent = {s: 0.0 for s in stats_cles()}
    avant = {s: 0.0 for s in stats_cles()}
    for e in evenements:
        if e.stat not in cumul:
            continue
        cumul[e.stat] += (e.base_points or 0) * (1 + (e.bonus_pct or 0) / 100)
        if e.date_key >= debut_recent:
            recent[e.stat] += e.points or 0
        elif e.date_key >= debut_avant:
            avant[e.stat] += e.points or 0

    lignes = []
    for s in stats_cles():
        ponderes = cumul[s] * float(arch["coefficients"].get(s, 1.0))
        moyenne = avant[s] / 4
        if recent[s] == 0 and moyenne == 0:
            forme = "flat"
        elif moyenne == 0 or recent[s] > moyenne * (1 + seuil):
            forme = "up"
        elif recent[s] < moyenne * (1 - seuil):
            forme = "down"
        else:
            forme = "flat"
        lignes.append({
            "key": s, "label": noms.get(s, s),
            "value": int(arch["base"].get(s, 10)) + round(facteur * math.sqrt(ponderes)),
            "points": round(ponderes, 1), "forme": forme,
        })
    return lignes
