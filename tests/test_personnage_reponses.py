"""Champ additif « personnage » dans la réponse HTTP des routes qui
appellent services/personnage_hooks.evenement()/action() (voir
personnage_hooks.resumer()) : le mobile en tire son toast « +X XP · Stat ».

Chaque route qui accorde des points renvoie désormais, en plus de son corps
habituel, une clé « personnage » — le résumé agrégé (points_par_stat, xp,
level_up, new_rank, chests, quests_done), ou None si rien à afficher (pas de
personnage créé, ou l'action ne rapporte rien de nouveau, ex. plafond déjà
atteint).
"""
from app.services import personnage_hooks


def _creer_personnage(client, headers):
    r = client.post(
        "/character",
        json={"universe": "anime", "class_key": "combattant", "name": "Test"},
        headers=headers,
    )
    assert r.status_code == 201, r.text


# ---------- Habitudes ----------

def test_cocher_une_habitude_renvoie_personnage(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    _creer_personnage(client, h)

    habit_id = client.post("/habits", json={"label": "Lire 10 pages"}, headers=h).json()["id"]
    r = client.post(f"/habits/{habit_id}/log", headers=h)
    assert r.status_code == 201
    corps = r.json()
    assert corps["ok"] is True
    assert corps["personnage"] is not None
    assert corps["personnage"]["xp"] > 0
    assert corps["personnage"]["points_par_stat"].get("wil", 0) > 0


def test_cocher_une_habitude_sans_personnage_renvoie_personnage_null(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    habit_id = client.post("/habits", json={"label": "Lire 10 pages"}, headers=h).json()["id"]
    r = client.post(f"/habits/{habit_id}/log", headers=h)
    assert r.status_code == 201
    assert r.json()["personnage"] is None


# ---------- Sport (séance de musculation) ----------

def test_seance_musculation_renvoie_personnage(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    _creer_personnage(client, h)

    r = client.post("/strength-sessions", json={"durationMin": 30, "exercises": []}, headers=h)
    assert r.status_code == 201
    corps = r.json()
    assert corps["ok"] is True
    assert corps["personnage"] is not None
    assert corps["personnage"]["xp"] > 0
    assert corps["personnage"]["points_par_stat"].get("str", 0) > 0


def test_seance_musculation_sans_personnage_renvoie_personnage_null(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.post("/strength-sessions", json={"durationMin": 30, "exercises": []}, headers=h)
    assert r.status_code == 201
    assert r.json()["personnage"] is None


# ---------- Hydratation (objectif du jour atteint) ----------

def test_objectif_hydratation_atteint_renvoie_personnage(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    _creer_personnage(client, h)

    assert client.put("/hydration/settings", json={"dailyGoalMl": 500}, headers=h).status_code == 200
    r = client.post("/hydration", json={"amountMl": 500}, headers=h)
    assert r.status_code == 201
    corps = r.json()
    assert corps["goalReached"] is True
    assert corps["personnage"] is not None
    assert corps["personnage"]["points_par_stat"].get("hp", 0) > 0

    # Un second verre le même jour ne rapporte plus rien (plafond_jour = 1) :
    # pas de nouveau toast.
    r2 = client.post("/hydration", json={"amountMl": 100}, headers=h)
    assert r2.json()["personnage"] is None


def test_objectif_hydratation_sans_personnage_renvoie_personnage_null(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    assert client.put("/hydration/settings", json={"dailyGoalMl": 500}, headers=h).status_code == 200
    r = client.post("/hydration", json={"amountMl": 500}, headers=h)
    assert r.status_code == 201
    assert r.json()["personnage"] is None


# ---------- personnage_hooks.resumer() : agrégation ----------

def test_resumer_agrege_xp_stats_coffres_et_quetes():
    resultats = [
        {"points_par_stat": {"str": 2.0}, "xp": 20, "level_up": False, "new_rank": None,
         "chests": [], "quests_done": ["habitude"]},
        None,  # ignoré (plafond déjà atteint, ou pas de personnage)
        {"points_par_stat": {"str": 1.0, "hp": 1.0}, "xp": 10, "level_up": True,
         "new_rank": {"rank": 2, "name": "Bronze"}, "chests": [{"kind": "rank"}], "quests_done": []},
    ]
    resume = personnage_hooks.resumer(resultats)
    assert resume == {
        "points_par_stat": {"str": 3.0, "hp": 1.0},
        "xp": 30,
        "level_up": True,
        "new_rank": {"rank": 2, "name": "Bronze"},
        "chests": [{"kind": "rank"}],
        "quests_done": ["habitude"],
    }


def test_resumer_vide_ou_sans_effet_renvoie_none():
    assert personnage_hooks.resumer([]) is None
    assert personnage_hooks.resumer([None, None]) is None
    assert personnage_hooks.resumer([{"points_par_stat": {}, "xp": 0, "level_up": False,
                                      "new_rank": None, "chests": [], "quests_done": []}]) is None
