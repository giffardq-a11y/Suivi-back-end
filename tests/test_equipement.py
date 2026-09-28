"""Module Personnage, suite : boutique, équipement, bonus plafonné, coffres
(rang, série, semaine), quêtes du jour, catalogue (services/equipement.py,
endpoints /character).

Les tirages des coffres passent par un faux générateur (FauxAlea) : le test
ne dépend pas du hasard.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from app import models
from app.database import SessionLocal
from app.modules import supprimer_donnees
from app.services import equipement, stats
from app.services.common import today_key


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def joueur(nouveau_compte, db):
    """Fabrique : compte + personnage Anime créé en base. Renvoie (user, en-têtes)."""
    def creer(class_key="combattant", shards=0, level=1):
        _, _, h, uid = nouveau_compte()
        user = db.query(models.User).filter(models.User.id == uid).one()
        db.add(models.Character(user_id=uid, universe="anime", class_key=class_key, name="Test",
                                shards=shards, level=level))
        db.commit()
        return user, h
    return creer


def _perso(db, user):
    db.expire_all()
    return db.query(models.Character).filter(models.Character.user_id == user.id).one()


def _donner(db, user, *cles, equiper=False):
    """Objets ajoutés (et équipés) directement en base."""
    for cle in cles:
        o = equipement.objet(cle)
        db.add(models.InventoryItem(user_id=user.id, universe=o["univers"], item_key=cle, source="shop"))
        if equiper:
            db.add(models.EquippedItem(user_id=user.id, universe=o["univers"], slot=o["emplacement"], item_key=cle))
    db.commit()


class FauxAlea:
    """Tirage imposé : random() renvoie `valeur`, choice() le premier élément."""
    def __init__(self, valeur):
        self.valeur = valeur

    def random(self):
        return self.valeur

    def choice(self, seq):
        return seq[0]


JOUR = "2026-09-01"


# ---------- Catalogue ----------

def test_catalogue_config():
    objets = equipement.catalogue()["objets"]
    assert len(objets) == 100
    for u in ("anime", "medieval", "fantasy", "moderne", "sf"):
        assert len([o for o in objets if o["univers"] == u]) == 20
    for o in objets:
        assert o["emplacement"] in equipement.emplacements()
        if o["emplacement"] in ("familier", "aura", "fond"):
            assert o["bonus"] is None
        else:
            assert 1 <= o["bonus"]["pct"] <= 5
        if o["classe"]:
            assert stats.classe(o["univers"], o["classe"]) is not None


def test_get_catalog(client, joueur, db):
    user, h = joueur(shards=500)
    r = client.get("/character/catalog", headers=h)
    assert r.status_code == 200
    corps = r.json()
    assert corps["universe"] == "anime"
    assert corps["slots"] == ["tete", "torse", "mains", "dos", "jambes", "pieds", "accessoire", "familier", "aura", "fond"]
    assert len(corps["items"]) == 20
    items = {i["key"]: i for i in corps["items"]}
    assert set(items["anime_bandeau_dojo"]) == {"key", "name", "slot", "rarity", "price", "rank_required",
                                                "class_key", "bonus", "icon", "color", "owned", "equipped",
                                                "locked_reason"}
    assert items["anime_plastron_ardent"]["locked_reason"] == "Rang 3 requis"
    assert items["anime_sabre_bois"]["locked_reason"] == "Réservé à la classe Samouraï"
    assert items["anime_bandeau_dojo"]["locked_reason"] is None
    assert not items["anime_bandeau_dojo"]["owned"]

    assert client.post("/character/shop/buy/anime_bandeau_dojo", headers=h).status_code == 201
    assert client.put("/character/equip", json={"slot": "tete", "item_key": "anime_bandeau_dojo"},
                      headers=h).status_code == 200
    assert client.post("/character/shop/buy/anime_kimono_entrainement", headers=h).status_code == 201
    items = {i["key"]: i for i in client.get("/character/catalog", headers=h).json()["items"]}
    assert items["anime_bandeau_dojo"]["owned"] and items["anime_bandeau_dojo"]["equipped"]
    assert items["anime_kimono_entrainement"]["owned"] and not items["anime_kimono_entrainement"]["equipped"]

    # Autre univers : ses propres objets, rien de possédé.
    medieval = client.get("/character/catalog?universe=medieval", headers=h).json()
    assert medieval["universe"] == "medieval" and len(medieval["items"]) == 20
    assert not any(i["owned"] for i in medieval["items"])
    assert client.get("/character/catalog?universe=inconnu", headers=h).status_code == 422


def test_catalogue_sans_personnage(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    assert client.get("/character/catalog", headers=h).status_code == 404
    assert client.get("/character/quests/today", headers=h).status_code == 404


def test_config_chest_odds(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    odds = client.get("/character/config", headers=h).json()["chest_odds"]
    assert odds == {"commun": 0.60, "rare": 0.25, "epique": 0.12, "legendaire": 0.03}
    assert abs(sum(odds.values()) - 1) < 1e-9


# ---------- Achat ----------

def test_achat(client, joueur, db):
    user, h = joueur(shards=100)
    r = client.post("/character/shop/buy/anime_bandeau_dojo", headers=h)
    assert r.status_code == 201 and r.json() == {"item_key": "anime_bandeau_dojo", "shards_restants": 50}
    assert client.post("/character/shop/buy/anime_bandeau_dojo", headers=h).status_code == 409
    # Rang et classe vérifiés avant le prix.
    r = client.post("/character/shop/buy/anime_plastron_ardent", headers=h)
    assert r.status_code == 422 and r.json()["detail"] == "Rang 3 requis"
    r = client.post("/character/shop/buy/anime_sabre_bois", headers=h)
    assert r.status_code == 422 and "Samouraï" in r.json()["detail"]
    assert client.post("/character/shop/buy/objet_inconnu", headers=h).status_code == 422
    assert client.post("/character/shop/buy/medieval_gambison", headers=h).status_code == 422
    assert client.post("/character/shop/buy/anime_sac_voyageur", headers=h).json()["shards_restants"] == 0
    assert client.post("/character/shop/buy/anime_kimono_entrainement", headers=h).status_code == 402
    assert _perso(db, user).shards == 0
    sources = {i.item_key: i.source for i in db.query(models.InventoryItem).filter(
        models.InventoryItem.user_id == user.id).all()}
    assert sources == {"anime_bandeau_dojo": "shop", "anime_sac_voyageur": "shop"}


def test_achat_classe_et_rang_respectes(client, joueur):
    _, h = joueur("samourai", shards=1000, level=25)       # rang 3 (Guerrier)
    assert client.post("/character/shop/buy/anime_sabre_bois", headers=h).status_code == 201
    assert client.post("/character/shop/buy/anime_plastron_ardent", headers=h).status_code == 201
    assert client.post("/character/shop/buy/anime_eventail_acier", headers=h).status_code == 422  # rang 4


# ---------- Équipement ----------

def test_equiper_et_desequiper(client, joueur, db):
    user, h = joueur(shards=100)
    vide = client.get("/character/equipment", headers=h).json()
    assert vide["universe"] == "anime"
    assert list(vide["slots"]) == equipement.emplacements() and all(v is None for v in vide["slots"].values())

    client.post("/character/shop/buy/anime_bandeau_dojo", headers=h)
    r = client.put("/character/equip", json={"slot": "tete", "item_key": "anime_bandeau_dojo"}, headers=h)
    assert r.status_code == 200
    assert r.json()["slots"]["tete"]["key"] == "anime_bandeau_dojo" and r.json()["slots"]["tete"]["equipped"]
    assert r.json() == client.get("/character/equipment", headers=h).json()

    # Mauvais emplacement, objet non possédé, emplacement inconnu.
    assert client.put("/character/equip", json={"slot": "torse", "item_key": "anime_bandeau_dojo"},
                      headers=h).status_code == 422
    assert client.put("/character/equip", json={"slot": "torse", "item_key": "anime_kimono_entrainement"},
                      headers=h).status_code == 403
    assert client.put("/character/equip", json={"slot": "chapeau", "item_key": "anime_bandeau_dojo"},
                      headers=h).status_code == 422

    r = client.delete("/character/equip/tete", headers=h)
    assert r.status_code == 200 and r.json()["slots"]["tete"] is None
    assert client.delete("/character/equip/chapeau", headers=h).status_code == 422


def test_equiper_objet_de_classe_apres_changement(client, joueur, db):
    """Objet réservé à une classe quittée depuis : plus équipable."""
    user, h = joueur("samourai")
    _donner(db, user, "anime_sabre_bois")
    perso = _perso(db, user)
    perso.class_key = "ninja"
    db.commit()
    r = client.put("/character/equip", json={"slot": "mains", "item_key": "anime_sabre_bois"}, headers=h)
    assert r.status_code == 422


# ---------- Bonus d'équipement ----------

def test_bonus_d_equipement_simple(joueur, db):
    user, _ = joueur("combattant")
    _donner(db, user, "anime_bandes_poing", equiper=True)            # str +2 %
    r = stats.award(db, user, "strength_session", "s1", JOUR)
    assert r["points_par_stat"] == {"str": round(2 * 1.5 * 1.02, 2)}
    e = db.query(models.StatEvent).filter(models.StatEvent.user_id == user.id).one()
    assert e.bonus_pct == 2


def test_bonus_d_equipement_plafonne_a_15_pourcent(joueur, db, monkeypatch):
    user, _ = joueur("combattant")
    # Catalogue retouché : 4 objets à +5 % de force sur 4 emplacements = +20 %.
    modifie = copy.deepcopy(equipement.catalogue())
    renforces = ["anime_bandeau_dojo", "anime_kimono_entrainement", "anime_bandes_poing", "anime_sac_voyageur"]
    for o in modifie["objets"]:
        if o["cle"] in renforces:
            o["bonus"] = {"stat": "str", "pct": 5}
    monkeypatch.setattr(equipement, "catalogue", lambda: modifie)
    _donner(db, user, *renforces, equiper=True)
    assert equipement.bonus_equipement(db, _perso(db, user)) == {"str": 15.0}

    r = stats.award(db, user, "strength_session", "s1", JOUR)
    assert r["points_par_stat"] == {"str": round(2 * 1.5 * 1.15, 2)}
    # Passif du Colosse (+100 % sur les records) additionné, hors plafond.
    r = stats.award(db, user, "strength_pr", "pr1", JOUR)
    assert r["points_par_stat"] == {"str": round(5 * 1.5 * 2.15, 2)}
    pr = db.query(models.StatEvent).filter(models.StatEvent.user_id == user.id,
                                           models.StatEvent.source == "strength_pr").one()
    assert pr.bonus_pct == 115
    # Une autre stat n'en profite pas.
    assert stats.award(db, user, "goal_completed", "g1", JOUR)["points_par_stat"] == {"wil": 12.0}


# ---------- Coffres ----------

def _monter_au_rang_2(db, user):
    seuil_10 = sum(stats.cout_niveau(n) for n in range(1, 10))
    perso = _perso(db, user)
    perso.total_xp, perso.level = seuil_10 - 1, 9
    db.commit()
    return stats.award(db, user, "goal_completed", "o-rang", JOUR)


def test_coffre_de_rang_puis_ouverture(client, joueur, db, monkeypatch):
    user, h = joueur("combattant")
    r = _monter_au_rang_2(db, user)
    assert r["new_rank"] == {"rank": 2, "name": "Initié"}
    assert [c["kind"] for c in r["chests"]] == ["rank"]

    coffres = client.get("/character/chests", headers=h).json()
    assert len(coffres) == 1
    c = coffres[0]
    assert set(c) == {"id", "kind", "earned_at", "opened_at", "contents"}
    assert c["kind"] == "rank" and c["opened_at"] is None and c["contents"] is None
    assert isinstance(c["earned_at"], int)

    # Tirage légendaire : aucun légendaire au rang 2 → rareté inférieure
    # (épique, rang 2 max, hors classe réservée : l'aura).
    monkeypatch.setattr(equipement, "_alea", FauxAlea(0.99))
    eclats = _perso(db, user).shards
    r = client.post(f"/character/chests/{c['id']}/open", headers=h)
    assert r.status_code == 200
    contenu = r.json()
    assert contenu["shards"] == 20
    assert contenu["item"]["key"] == "anime_aura_flammes" and contenu["item"]["owned"]
    assert _perso(db, user).shards == eclats + 20
    inv = db.query(models.InventoryItem).filter(models.InventoryItem.user_id == user.id).one()
    assert (inv.item_key, inv.source, inv.universe) == ("anime_aura_flammes", "chest", "anime")

    ouvert = client.get("/character/chests", headers=h).json()[0]
    assert ouvert["opened_at"] is not None and ouvert["contents"] == contenu
    assert client.post(f"/character/chests/{c['id']}/open", headers=h).status_code == 409
    assert client.post("/character/chests/inconnu/open", headers=h).status_code == 404


def test_coffre_eclats_seuls_si_tout_est_possede(client, joueur, db, monkeypatch):
    user, h = joueur("combattant")
    perso = _perso(db, user)
    tous = [o["cle"] for o in equipement.catalogue()["objets"]
            if o["univers"] == "anime" and equipement.raison_verrou(o, perso) is None]
    _donner(db, user, *tous)
    coffre = equipement._creer_coffre(db, user.id, "streak_7", "test")
    db.commit()
    monkeypatch.setattr(equipement, "_alea", FauxAlea(0.0))
    r = client.post(f"/character/chests/{coffre.id}/open", headers=h)
    assert r.status_code == 200 and r.json() == {"shards": 5, "item": None}


def test_coffre_commun_tire_un_objet_commun(joueur, db):
    user, _ = joueur("combattant")
    coffre = equipement._creer_coffre(db, user.id, "weekly", "2026-08-03")
    db.commit()
    contenu = equipement.ouvrir(db, _perso(db, user), coffre.id, FauxAlea(0.1))
    assert contenu["shards"] == 10 and contenu["item"]["rarity"] == "commun"


def test_coffre_de_serie_7_jours(joueur, db):
    user, _ = joueur("samourai")
    habit = models.Habit(user_id=user.id, key="lire", label="Lire")
    db.add(habit)
    db.commit()
    debut = datetime(2026, 8, 1, 9, tzinfo=timezone.utc)
    for i in range(8):
        db.add(models.HabitLog(habit_id=habit.id, occurred_at=debut + timedelta(days=i)))
    db.commit()
    stats.constater_habitudes(db, user)
    stats.constater_habitudes(db, user)                           # rejoué : pas de doublon
    coffres = db.query(models.Chest).filter(models.Chest.user_id == user.id).all()
    assert [(c.kind, c.ref) for c in coffres] == [("streak_7", f"{habit.id}:2026-08-01:7")]


def test_coffre_hebdomadaire(joueur, db, monkeypatch):
    """5 jours de la semaine calendaire avec une quête du jour faite → coffre."""
    user, _ = joueur("combattant")
    lundi = datetime(2026, 8, 3).date()
    jours = [(lundi + timedelta(days=i)).isoformat() for i in range(5)]
    for j in jours:
        db.add(models.DailyQuest(user_id=user.id, date_key=j, quest_key="muscu", xp=40))
    db.commit()
    xp_avant = _perso(db, user).total_xp
    for i, j in enumerate(jours):
        r = stats.award(db, user, "strength_session", f"s{i}", j)
        assert r["quests_done"] == [{"key": "muscu", "label": "Séance de muscu", "xp": 40}]
        hebdo = [c for c in r["chests"] if c["kind"] == "weekly"]
        assert bool(hebdo) == (i == 4)
    # 5 séances (2 × 1,5 = 3 pts = 30 XP) + 5 quêtes à 40 XP.
    assert _perso(db, user).total_xp == xp_avant + 5 * 30 + 5 * 40
    coffres = db.query(models.Chest).filter(models.Chest.user_id == user.id, models.Chest.kind == "weekly").all()
    assert [c.ref for c in coffres] == ["2026-08-03"]
    # Un 6e jour dans la même semaine ne crée pas un second coffre.
    db.add(models.DailyQuest(user_id=user.id, date_key="2026-08-08", quest_key="muscu", xp=40))
    db.commit()
    stats.award(db, user, "strength_session", "s6", "2026-08-08")
    assert db.query(models.Chest).filter(models.Chest.user_id == user.id, models.Chest.kind == "weekly").count() == 1


# ---------- Quêtes du jour ----------

def test_quetes_du_jour(client, joueur, db):
    user, h = joueur()
    r1 = client.get("/character/quests/today", headers=h).json()
    r2 = client.get("/character/quests/today", headers=h).json()
    assert r1["date"] == today_key()
    assert len(r1["quests"]) == 3 and r1 == r2
    assert all(set(q) == {"key", "label", "xp", "done"} and q["done"] is False for q in r1["quests"])
    assert db.query(models.DailyQuest).filter(models.DailyQuest.user_id == user.id).count() == 3

    # L'action correspondant à la première quête la valide, pas les autres.
    modele = next(m for m in stats.config()["quetes"]["modeles"] if m["cle"] == r1["quests"][0]["key"])
    xp_avant = _perso(db, user).total_xp
    r = stats.award(db, user, modele["sources"][0], "action-1", today_key(),
                    {"distanceKm": 5, "durationMin": 30})
    assert [q["key"] for q in r["quests_done"]] == [modele["cle"]]
    assert _perso(db, user).total_xp == xp_avant + r["xp"] + modele["xp"]
    etat = {q["key"]: q["done"] for q in client.get("/character/quests/today", headers=h).json()["quests"]}
    assert etat[modele["cle"]] is True
    assert sum(etat.values()) == 1


def test_quetes_selon_modules_actifs(client, nouveau_compte_avec_modules, db):
    _, _, h, uid = nouveau_compte_avec_modules(["sport", "personnage"])
    db.add(models.Character(user_id=uid, universe="anime", class_key="ninja", name="Test"))
    db.commit()
    quetes = client.get("/character/quests/today", headers=h).json()["quests"]
    modules = {m["cle"]: m["module"] for m in stats.config()["quetes"]["modeles"]}
    assert len(quetes) == 3 and {modules[q["key"]] for q in quetes} == {"sport"}


def test_tirage_stable_par_jour():
    class U:
        id = "utilisateur-fixe"
        enabled_modules = None
    a = [m["cle"] for m in equipement.tirer_quetes(U, "2026-09-01")]
    assert a == [m["cle"] for m in equipement.tirer_quetes(U, "2026-09-01")]
    assert len(set(a)) == 3


# ---------- Suppression des données du module ----------

def test_suppression_module_personnage(client, joueur, db):
    user, h = joueur(shards=100)
    client.post("/character/shop/buy/anime_bandeau_dojo", headers=h)
    client.put("/character/equip", json={"slot": "tete", "item_key": "anime_bandeau_dojo"}, headers=h)
    client.get("/character/quests/today", headers=h)
    equipement._creer_coffre(db, user.id, "rank", "2")
    db.commit()
    compte = supprimer_donnees(db, user.id, "personnage")
    for table in ("inventory_items", "equipped_items", "chests", "daily_quests", "characters"):
        assert compte.get(table), table
