"""Modules activables : registre (aucune table oubliée), inscription avec un
sous-ensemble de modules, routes /me/modules, purge des données d'un module,
sections du tableau de bord masquées quand leur module est désactivé.
"""
from app.database import Base, SessionLocal
from app import models
from app.modules import MODULES, SOCLE, TOUS


def test_toute_table_est_couverte_par_le_socle_ou_un_module():
    """Chaque table du schéma appartient au SOCLE (toujours actif) ou aux
    tables d'un module — sinon une table ajoutée plus tard échapperait à la
    fois à `modules_actifs` et à `supprimer_donnees` (voir app/modules.py)."""
    tables_modules = {t for m in MODULES.values() for t in m["tables"]}
    couvertes = SOCLE | tables_modules
    toutes = {t.name for t in Base.metadata.sorted_tables}
    assert toutes - couvertes == set()


def test_inscription_avec_modules_restreints(client, nouveau_compte_avec_modules):
    email, mdp, h, uid = nouveau_compte_avec_modules(["sport", "nutrition"])

    db = SessionLocal()
    user = db.query(models.User).filter(models.User.id == uid).one()
    assert user.enabled_modules == ["sport", "nutrition"]
    # Pas de module addictions actif : pas de substances Alcool/Tabac créées.
    assert db.query(models.Substance).filter(models.Substance.user_id == uid).count() == 0
    db.close()

    modules_dashboard = client.get("/me/dashboard", headers=h).json()
    assert modules_dashboard["enabled_modules"] == ["sport", "nutrition"]


def test_inscription_sans_modules_comportement_inchange(client, nouveau_compte):
    _, _, h, uid = nouveau_compte()

    db = SessionLocal()
    user = db.query(models.User).filter(models.User.id == uid).one()
    assert user.enabled_modules is None
    assert db.query(models.Substance).filter(models.Substance.user_id == uid).count() == 2
    db.close()

    dashboard = client.get("/me/dashboard", headers=h).json()
    assert sorted(dashboard["enabled_modules"]) == sorted(TOUS)


def test_get_modules(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.get("/me/modules", headers=h)
    assert r.status_code == 200
    corps = r.json()
    assert sorted(corps["enabled"]) == sorted(TOUS)
    assert {"key": "budget", "label": "Budget"} in corps["available"]
    assert len(corps["available"]) == len(TOUS)


def test_put_modules_valide_et_rejette_les_cles_inconnues(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()

    r = client.put("/me/modules", json={"enabled": ["sport", "hydratation"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["enabled"] == ["sport", "hydratation"]
    # Persisté : une relecture renvoie la même liste, pas « tout actif ».
    assert client.get("/me/modules", headers=h).json()["enabled"] == ["sport", "hydratation"]

    r = client.put("/me/modules", json={"enabled": ["sport", "n_importe_quoi"]}, headers=h)
    assert r.status_code == 422


def test_supprimer_donnees_module_efface_le_module_et_garde_le_socle(client, nouveau_compte):
    _, _, h, uid = nouveau_compte()
    assert client.post("/hydration", json={"amountMl": 500}, headers=h).status_code == 201
    assert client.post("/weight", json={"weightKg": 70}, headers=h).status_code == 201

    r = client.post("/me/modules/hydratation/supprimer-donnees", headers=h)
    assert r.status_code == 200
    assert r.json()["module"] == "hydratation"
    assert r.json()["deleted"].get("water_logs") == 1

    assert client.get("/hydration", headers=h).json()["totalMl"] == 0
    # Le socle (ici : les pesées) n'est pas touché par la purge d'un module.
    assert len(client.get("/weight", headers=h).json()["entries"]) == 1

    # Module inconnu : 404, rien à effacer.
    assert client.post("/me/modules/n_importe_quoi/supprimer-donnees", headers=h).status_code == 404


def test_dashboard_masque_les_sections_des_modules_desactives(client, nouveau_compte_avec_modules):
    email, mdp, h, uid = nouveau_compte_avec_modules(["sport", "nutrition"])

    # Une habitude créée malgré le module désactivé (l'API habitudes reste
    # accessible tant qu'elle n'est pas elle-même conditionnée : seul le
    # tableau de bord doit la masquer ici).
    db = SessionLocal()
    habit = models.Habit(user_id=uid, key="lire", label="Lire")
    db.add(habit)
    db.commit()
    db.close()

    dashboard = client.get("/me/dashboard", headers=h).json()
    assert dashboard["enabled_modules"] == ["sport", "nutrition"]
    # habitudes désactivé : pas d'habitude du jour malgré la ligne créée.
    assert dashboard["habits_today"] == []
    # addictions désactivé : pas de streak (aucune substance de toute façon).
    assert dashboard["streaks"] == []
    assert dashboard["savings"]["total"] == 0
    # nutrition actif : le bilan calorique est bien présent.
    assert dashboard["calorie_balance"] is not None
