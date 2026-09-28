"""Module Personnage, suite : boutique, inventaire, équipement, coffres et
quêtes du jour (cahier : mobile/docs/tanren-rpg/PROMPT-module-personnage.md
§4-6). Le moteur de points reste dans services/stats.py, qui appelle ce
fichier au moment d'attribuer (bonus d'équipement, coffres, quêtes).

Données : catalogue d'objets dans app/data/personnage/catalogue_equipement.json,
coffres et quêtes dans config.json (clés « coffres » et « quetes »).

Règles tenues ici :
  - l'inventaire et l'équipement sont tenus PAR UNIVERS : changer d'univers
    ne fait rien perdre, on retrouve ses objets en y revenant ; on n'achète
    et on n'équipe que dans l'univers courant ;
  - bonus d'équipement : somme des % des objets équipés (univers courant,
    encore autorisés pour le rang et la classe) sur une stat, plafonnée à
    +15 %, PUIS additionnée à la capacité passive de classe (plafonds
    séparés : le passif n'entame pas le plafond de l'équipement). Le total
    est stocké dans stat_events.bonus_pct ;
  - coffres gagnés, jamais achetés, créés une seule fois (unicité user_id,
    kind, ref) : passage de rang, série d'habitude de 7/30/100 jours,
    semaine calendaire avec 5 jours de quête faite ;
  - quêtes du jour : 3 modèles tirés de façon stable par utilisateur et par
    jour, parmi ceux des modules actifs ; faites dès qu'un stat_event d'une
    de leurs sources existe ce jour-là, leur XP est versée une fois.

Pas d'objet de départ (l'utilisateur achète ou gagne tout) et pas de
boutique premium dans cette version (aucun paiement réel).

Les erreurs métier lèvent ErreurEquipement(statut, message) : le routeur les
traduit en HTTPException, ce fichier reste indépendant de FastAPI.
"""
import json
import random
from functools import lru_cache
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..modules import est_actif
from . import stats
from .common import now_utc, to_ms, today_key

CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "personnage" / "catalogue_equipement.json"

RARETES = ["commun", "rare", "epique", "legendaire"]

# Tirage des coffres : remplaçable dans les tests.
_alea = random.Random()


class ErreurEquipement(Exception):
    def __init__(self, statut: int, message: str):
        super().__init__(message)
        self.statut = statut
        self.message = message


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


def emplacements() -> list[str]:
    return catalogue()["emplacements"]


def objets() -> dict[str, dict]:
    return {o["cle"]: o for o in catalogue()["objets"]}


def objet(cle: str) -> dict | None:
    return objets().get(cle)


def rang_actuel(perso: models.Character) -> int:
    return stats.rang_pour_niveau(perso.level or 1)["rang"]


def raison_verrou(o: dict, perso: models.Character) -> str | None:
    """Pourquoi le personnage ne peut pas acheter ni équiper cet objet (rang
    d'abord, puis classe), ou None."""
    if o["rang_requis"] > rang_actuel(perso):
        return f"Rang {o['rang_requis']} requis"
    if o.get("classe") and not (perso.universe == o["univers"] and perso.class_key == o["classe"]):
        c = stats.classe(o["univers"], o["classe"])
        return f"Réservé à la classe {c['nom'] if c else o['classe']}"
    return None


def possedes(db: Session, user_id: str, universe: str) -> set[str]:
    return {k for (k,) in db.query(models.InventoryItem.item_key).filter(
        models.InventoryItem.user_id == user_id, models.InventoryItem.universe == universe).all()}


def equipes(db: Session, user_id: str, universe: str) -> dict[str, str]:
    """{emplacement: clé d'objet}."""
    return {slot: k for slot, k in db.query(models.EquippedItem.slot, models.EquippedItem.item_key).filter(
        models.EquippedItem.user_id == user_id, models.EquippedItem.universe == universe).all()}


def serialiser_objet(o: dict, perso: models.Character, possedes_: set[str], equipes_: set[str]) -> dict:
    return {
        "key": o["cle"], "name": o["nom"], "slot": o["emplacement"], "rarity": o["rarete"],
        "price": o["prix"], "rank_required": o["rang_requis"], "class_key": o.get("classe"),
        "bonus": dict(o["bonus"]) if o.get("bonus") else None,
        "icon": o["icone"], "color": o["couleur"],
        "owned": o["cle"] in possedes_, "equipped": o["cle"] in equipes_,
        "locked_reason": raison_verrou(o, perso),
    }


def _objet_pour(db: Session, perso: models.Character, cle: str | None) -> dict | None:
    o = objet(cle) if cle else None
    if o is None:
        return None
    return serialiser_objet(o, perso, possedes(db, perso.user_id, o["univers"]),
                            set(equipes(db, perso.user_id, o["univers"]).values()))


# ---------- Catalogue, achat, équipement ----------

def catalogue_pour(db: Session, perso: models.Character, universe: str) -> dict:
    if stats.univers(universe) is None:
        raise ErreurEquipement(422, f"Univers inconnu : {universe}")
    p = possedes(db, perso.user_id, universe)
    e = set(equipes(db, perso.user_id, universe).values())
    return {
        "universe": universe,
        "slots": emplacements(),
        "items": [serialiser_objet(o, perso, p, e) for o in catalogue()["objets"] if o["univers"] == universe],
    }


def equipement_de(db: Session, perso: models.Character) -> dict:
    """Équipement de l'univers courant : un objet (ou None) par emplacement."""
    p = possedes(db, perso.user_id, perso.universe)
    e = equipes(db, perso.user_id, perso.universe)
    slots = {}
    for slot in emplacements():
        o = objet(e[slot]) if slot in e else None
        slots[slot] = serialiser_objet(o, perso, p, set(e.values())) if o else None
    return {"universe": perso.universe, "slots": slots}


def acheter(db: Session, perso: models.Character, cle: str) -> dict:
    o = objet(cle)
    if o is None:
        raise ErreurEquipement(422, f"Objet inconnu : {cle}")
    if o["univers"] != perso.universe:
        raise ErreurEquipement(422, "Cet objet appartient à un autre univers.")
    if cle in possedes(db, perso.user_id, perso.universe):
        raise ErreurEquipement(409, "Objet déjà possédé.")
    raison = raison_verrou(o, perso)
    if raison:
        raise ErreurEquipement(422, raison)
    if (perso.shards or 0) < o["prix"]:
        raise ErreurEquipement(402, f"Éclats insuffisants : {o['prix']} requis, {perso.shards or 0} disponibles.")
    perso.shards = (perso.shards or 0) - o["prix"]
    db.add(models.InventoryItem(user_id=perso.user_id, universe=o["univers"], item_key=cle,
                                source="shop", acquired_at=now_utc()))
    try:
        db.commit()
    except IntegrityError:
        # Deux achats simultanés du même objet : le second est refusé, sans débit.
        db.rollback()
        raise ErreurEquipement(409, "Objet déjà possédé.")
    return {"item_key": cle, "shards_restants": perso.shards}


def _verifier_slot(slot: str) -> None:
    if slot not in emplacements():
        raise ErreurEquipement(422, f"Emplacement inconnu : {slot}")


def equiper(db: Session, perso: models.Character, slot: str, cle: str) -> dict:
    _verifier_slot(slot)
    o = objet(cle)
    if o is None:
        raise ErreurEquipement(422, f"Objet inconnu : {cle}")
    if o["emplacement"] != slot:
        raise ErreurEquipement(422, f"Cet objet se porte sur l'emplacement « {o['emplacement']} », pas « {slot} ».")
    if cle not in possedes(db, perso.user_id, perso.universe):
        raise ErreurEquipement(403, "Objet non possédé.")
    raison = raison_verrou(o, perso)
    if raison:
        raise ErreurEquipement(422, raison)
    ligne = db.query(models.EquippedItem).filter(
        models.EquippedItem.user_id == perso.user_id, models.EquippedItem.universe == perso.universe,
        models.EquippedItem.slot == slot).first()
    if ligne is None:
        db.add(models.EquippedItem(user_id=perso.user_id, universe=perso.universe, slot=slot, item_key=cle))
    else:
        ligne.item_key = cle
    db.commit()
    return equipement_de(db, perso)


def desequiper(db: Session, perso: models.Character, slot: str) -> dict:
    _verifier_slot(slot)
    db.query(models.EquippedItem).filter(
        models.EquippedItem.user_id == perso.user_id, models.EquippedItem.universe == perso.universe,
        models.EquippedItem.slot == slot).delete()
    db.commit()
    return equipement_de(db, perso)


def bonus_equipement(db: Session, perso: models.Character) -> dict[str, float]:
    """% de bonus par stat des objets équipés dans l'univers courant, plafonné
    (plafond_bonus_pct du catalogue, 15 %). Un objet devenu interdit (classe
    changée) reste équipé mais ne compte plus."""
    plafond = float(catalogue()["plafond_bonus_pct"])
    total: dict[str, float] = {}
    for cle in equipes(db, perso.user_id, perso.universe).values():
        o = objet(cle)
        if o is None or not o.get("bonus") or raison_verrou(o, perso):
            continue
        s = o["bonus"]["stat"]
        total[s] = total.get(s, 0.0) + float(o["bonus"]["pct"])
    return {s: min(plafond, v) for s, v in total.items()}


# ---------- Coffres ----------

def _conf_coffres() -> dict:
    return stats.config()["coffres"]


def probabilites() -> dict[str, float]:
    return dict(_conf_coffres()["probabilites"])


def serialiser_coffre(db: Session, perso: models.Character | None, c: models.Chest) -> dict:
    contenu = None
    if c.contents is not None:
        item = _objet_pour(db, perso, c.contents.get("item_key")) if perso is not None else None
        contenu = {"shards": c.contents.get("shards", 0), "item": item}
    return {"id": c.id, "kind": c.kind, "earned_at": to_ms(c.earned_at),
            "opened_at": to_ms(c.opened_at), "contents": contenu}


def _creer_coffre(db: Session, user_id: str, kind: str, ref: str) -> models.Chest | None:
    """Crée le coffre s'il n'existe pas déjà (idempotent)."""
    existe = db.query(models.Chest.id).filter(
        models.Chest.user_id == user_id, models.Chest.kind == kind, models.Chest.ref == ref).first()
    if existe:
        return None
    coffre = models.Chest(user_id=user_id, kind=kind, ref=ref, earned_at=now_utc())
    db.add(coffre)
    db.flush()
    return coffre


def coffres_de_rang(db: Session, user_id: str, ancien_rang: int, nouveau_rang: int) -> list[models.Chest]:
    """Un coffre par rang franchi (un gros gain peut en franchir plusieurs)."""
    crees = []
    for rang in range(ancien_rang + 1, nouveau_rang + 1):
        c = _creer_coffre(db, user_id, "rank", str(rang))
        if c:
            crees.append(c)
    return crees


def coffre_de_serie(db: Session, user_id: str, palier: int, ref: str) -> models.Chest | None:
    """Palier de série d'une habitude (7, 30 ou 100 jours consécutifs, tels
    que détectés par stats.constater_habitudes). ref = source_id de
    l'événement habit_streak : habitude + début de série + longueur."""
    if palier not in (7, 30, 100):
        return None
    return _creer_coffre(db, user_id, f"streak_{palier}", ref)


def verifier_coffre_hebdo(db: Session, user_id: str, jour: str) -> models.Chest | None:
    """Coffre hebdomadaire : au moins jours_hebdo (5) jours de la semaine
    calendaire de `jour` (lundi à dimanche) avec une quête du jour faite."""
    semaine = stats._semaine_de(jour)
    db.flush()
    jours = {j for (j,) in db.query(models.DailyQuest.date_key).filter(
        models.DailyQuest.user_id == user_id, models.DailyQuest.date_key.in_(semaine),
        models.DailyQuest.done_at.isnot(None)).distinct().all()}
    if len(jours) < stats.config()["quetes"]["jours_hebdo"]:
        return None
    return _creer_coffre(db, user_id, "weekly", semaine[0])


def lister_coffres(db: Session, perso: models.Character) -> list[dict]:
    coffres = db.query(models.Chest).filter(models.Chest.user_id == perso.user_id).all()
    # Fermés d'abord, puis du plus récent au plus ancien.
    coffres.sort(key=lambda c: (c.opened_at is not None, -(to_ms(c.earned_at) or 0)))
    return [serialiser_coffre(db, perso, c) for c in coffres]


def _tirer_rarete(rng: random.Random) -> str:
    tirage, cumul = rng.random(), 0.0
    probas = probabilites()
    for r in RARETES:
        cumul += probas.get(r, 0)
        if tirage < cumul:
            return r
    return RARETES[0]


def ouvrir(db: Session, perso: models.Character, chest_id: str, rng: random.Random | None = None) -> dict:
    """Ouvre un coffre : éclats (selon le genre de coffre) + un objet de
    l'univers actif, pas encore possédé et équipable (rang, classe). Rareté
    tirée selon les probabilités ; aucun objet disponible dans cette rareté →
    rareté inférieure ; aucun du tout → éclats seuls."""
    rng = rng or _alea
    coffre = db.query(models.Chest).filter(models.Chest.id == chest_id,
                                           models.Chest.user_id == perso.user_id).first()
    if coffre is None:
        raise ErreurEquipement(404, "Coffre inconnu.")
    if coffre.opened_at is not None:
        raise ErreurEquipement(409, "Coffre déjà ouvert.")

    deja = possedes(db, perso.user_id, perso.universe)
    candidats = [o for o in catalogue()["objets"]
                 if o["univers"] == perso.universe and o["cle"] not in deja and raison_verrou(o, perso) is None]
    rarete = _tirer_rarete(rng)
    choisi = None
    for r in reversed(RARETES[:RARETES.index(rarete) + 1]):
        de_cette_rarete = sorted((o for o in candidats if o["rarete"] == r), key=lambda o: o["cle"])
        if de_cette_rarete:
            choisi = rng.choice(de_cette_rarete)
            break

    eclats = int(_conf_coffres()["eclats"].get(coffre.kind, 0))
    perso.shards = (perso.shards or 0) + eclats
    if choisi is not None:
        db.add(models.InventoryItem(user_id=perso.user_id, universe=choisi["univers"], item_key=choisi["cle"],
                                    source="chest", acquired_at=now_utc()))
    coffre.opened_at = now_utc()
    coffre.contents = {"shards": eclats, "item_key": choisi["cle"] if choisi else None}
    db.commit()
    return serialiser_coffre(db, perso, coffre)["contents"]


# ---------- Crédit d'XP hors stat (quêtes) ----------

def crediter(db: Session, user: models.User, perso: models.Character, xp: int) -> list[models.Chest]:
    """XP versée hors stat_event (quête faite) : niveau, éclats, et coffres
    de rang si un rang est franchi."""
    ancien = rang_actuel(perso)
    stats._crediter(perso, xp)
    return coffres_de_rang(db, user.id, ancien, rang_actuel(perso))


# ---------- Quêtes du jour ----------

def _modeles() -> list[dict]:
    return stats.config()["quetes"]["modeles"]


def tirer_quetes(user: models.User, jour: str) -> list[dict]:
    """Tirage stable (même utilisateur, même jour → mêmes quêtes) parmi les
    modèles des modules actifs. Moins de 3 disponibles (peu de modules
    actifs) : complété par les autres modèles, pour en avoir toujours 3."""
    rng = random.Random(f"{user.id}-{jour}")
    n = stats.config()["quetes"]["par_jour"]
    actifs = [m for m in _modeles() if est_actif(user, m["module"])]
    autres = [m for m in _modeles() if m not in actifs]
    choix = rng.sample(actifs, min(n, len(actifs)))
    if len(choix) < n:
        choix += rng.sample(autres, min(n - len(choix), len(autres)))
    return choix


def valider_quetes(db: Session, user: models.User, perso: models.Character, jour: str) -> dict:
    """Coche les quêtes tirées pour `jour` dont une source a produit un
    stat_event ce jour-là et verse leur XP (une fois). Renvoie
    {"quests_done": [...], "chests": [coffres créés]} sans commiter."""
    db.flush()
    a_faire = db.query(models.DailyQuest).filter(
        models.DailyQuest.user_id == user.id, models.DailyQuest.date_key == jour,
        models.DailyQuest.done_at.is_(None)).all()
    modeles = {m["cle"]: m for m in _modeles()}
    faites, coffres = [], []
    for q in a_faire:
        m = modeles.get(q.quest_key)
        if m is None:
            continue
        fait = db.query(models.StatEvent.id).filter(
            models.StatEvent.user_id == user.id, models.StatEvent.date_key == jour,
            models.StatEvent.source.in_(m["sources"])).first()
        if not fait:
            continue
        q.done_at = now_utc()
        coffres += crediter(db, user, perso, q.xp)
        faites.append({"key": q.quest_key, "label": m["libelle"], "xp": q.xp})
    if faites:
        hebdo = verifier_coffre_hebdo(db, user.id, jour)
        if hebdo:
            coffres.append(hebdo)
    return {"quests_done": faites, "chests": coffres}


def quetes_du_jour(db: Session, user: models.User, perso: models.Character, jour: str | None = None) -> dict:
    jour = jour or today_key()
    lignes = db.query(models.DailyQuest).filter(
        models.DailyQuest.user_id == user.id, models.DailyQuest.date_key == jour).all()
    if not lignes:
        for m in tirer_quetes(user, jour):
            db.add(models.DailyQuest(user_id=user.id, date_key=jour, quest_key=m["cle"], xp=int(m["xp"])))
        try:
            db.commit()
        except IntegrityError:
            # Premier appel du jour en double : l'autre a déjà tiré (même tirage).
            db.rollback()
    valider_quetes(db, user, perso, jour)
    db.commit()
    lignes = db.query(models.DailyQuest).filter(
        models.DailyQuest.user_id == user.id, models.DailyQuest.date_key == jour).all()
    modeles = {m["cle"]: m for m in _modeles()}
    ordre = list(modeles)
    lignes.sort(key=lambda q: ordre.index(q.quest_key) if q.quest_key in ordre else len(ordre))
    return {
        "date": jour,
        "quests": [{"key": q.quest_key, "label": modeles.get(q.quest_key, {}).get("libelle", q.quest_key),
                    "xp": q.xp, "done": q.done_at is not None} for q in lignes],
    }


# ---------- Branchement dans stats.award ----------

def apres_award(db: Session, user: models.User, perso: models.Character, source: str, source_id: str,
                jour: str, payload: dict, ancien_rang: int) -> dict:
    """Appelé par stats.award après un gain : coffres de rang et de série,
    quêtes du jour validées. Renvoie {"chests": [...], "quests_done": [...]}."""
    coffres = coffres_de_rang(db, user.id, ancien_rang, rang_actuel(perso))
    if source == "habit_streak":
        try:
            palier = int(payload.get("palier"))
        except (TypeError, ValueError):
            palier = 0
        c = coffre_de_serie(db, user.id, palier, source_id)
        if c:
            coffres.append(c)
    quetes = valider_quetes(db, user, perso, jour)
    coffres += quetes["chests"]
    return {"chests": [serialiser_coffre(db, perso, c) for c in coffres], "quests_done": quetes["quests_done"]}
