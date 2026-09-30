"""Réinitialisation de compte (2 niveaux) : voir app/services/reset.py.

Réutilise le remplisseur générique de test_suppression_compte.py (une ligne
par table, clés étrangères chaînées) pour ne pas maintenir une deuxième
liste de tables à la main.
"""
from datetime import date

from app import models
from app.database import SessionLocal
from app.services.reset import TABLES_EPARGNEES_TOUT_EFFACER, TABLES_PROGRESSION
from test_suppression_compte import _lignes_de, _remplir


def test_progression_efface_historique_garde_configuration(client, nouveau_compte):
    email, mdp, h, id_a = nouveau_compte()
    _, _, _, id_b = nouveau_compte()
    db = SessionLocal()
    _remplir(db, id_a)
    _remplir(db, id_b)
    avant_a = _lignes_de(db, id_a)
    avant_b = _lignes_de(db, id_b)
    db.close()

    assert client.post("/me/reset/progression", json={"password": "faux"}, headers=h).status_code == 403

    r = client.post("/me/reset/progression", json={"password": mdp}, headers=h)
    assert r.status_code == 204

    db = SessionLocal()
    apres_a = _lignes_de(db, id_a)
    # Tables de progression vidées, tout le reste toujours à 1 ligne (la
    # config n'est jamais supprimée, seulement recalée pour certaines).
    for nom, n in avant_a.items():
        if nom in TABLES_PROGRESSION:
            assert nom not in apres_a, f"{nom} aurait dû être vidée"
        else:
            assert apres_a.get(nom) == n, f"{nom} n'aurait pas dû changer de nombre de lignes"

    substance = db.query(models.Substance).filter_by(user_id=id_a).first()
    assert substance.quit_date == date.today().isoformat()

    goal = db.query(models.Goal).filter_by(user_id=id_a).first()
    assert goal.current_value == 0
    assert goal.completed_at is None

    perso = db.query(models.Character).filter_by(user_id=id_a).first()
    assert perso.level == 1 and perso.total_xp == 0 and perso.shards == 0 and perso.xp_avance == 0

    # Le compte reste utilisable : session valide, pas de déconnexion.
    assert client.get("/diet/pantry", headers=h).status_code == 200
    # L'autre compte n'a rien perdu.
    assert _lignes_de(db, id_b) == avant_b
    db.close()


def test_tout_effacer_garde_seulement_le_compte(client, nouveau_compte):
    email, mdp, h, id_a = nouveau_compte()
    _, _, _, id_b = nouveau_compte()
    db = SessionLocal()
    _remplir(db, id_a)
    _remplir(db, id_b)
    avant_b = _lignes_de(db, id_b)
    db.close()

    assert client.post("/me/reset/tout", json={"password": "faux"}, headers=h).status_code == 403

    r = client.post("/me/reset/tout", json={"password": mdp}, headers=h)
    assert r.status_code == 204

    db = SessionLocal()
    apres_a = _lignes_de(db, id_a)
    # Rien ne doit rester en dehors des tables épargnées (le compte lui-même
    # et sa session), et les épargnées ne sont jamais touchées.
    assert set(apres_a) <= TABLES_EPARGNEES_TOUT_EFFACER
    assert apres_a.get("refresh_tokens", 1) >= 1

    # Le compte reste connecté (contrairement à DELETE /me).
    assert client.get("/diet/pantry", headers=h).status_code == 200
    assert _lignes_de(db, id_b) == avant_b
    db.close()
