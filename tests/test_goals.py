"""Objectifs : création, progression à la main des objectifs « manuels »
(sans lien avec une mesure), modification, suppression — voir
app/routers/goals.py.
"""
from app import models
from app.database import SessionLocal
from app.routers import goals as routeur_goals


def _creer(client, h, **corps):
    r = client.post("/goals", json={"label": "Vendre l'appartement au Maroc", **corps}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _objectif(client, h, goal_id):
    liste = client.get("/goals", headers=h).json()["goals"]
    return next(g for g in liste if g["id"] == goal_id)


def _modifier(client, h, goal_id, **corps):
    return client.put(f"/goals/{goal_id}", json=corps, headers=h)


def _completed_at(goal_id):
    db = SessionLocal()
    try:
        return db.get(models.Goal, goal_id).completed_at
    finally:
        db.close()


def test_creation_sans_cible_donne_un_objectif_a_cocher(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    goal_id = _creer(client, h)
    g = _objectif(client, h, goal_id)
    assert g["target_value"] == 1 and g["current_value"] == 0
    assert g["manual"] is True and g["completed"] is False and g["percent"] == 0


def test_objectif_lie_exige_une_cible(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.post("/goals", json={"label": "Peser 70 kg", "linkedType": "weight_target"}, headers=h)
    assert r.status_code in (400, 422)
    r = client.post("/goals", json={"label": "Peser 70 kg", "linkedType": "weight_target", "targetValue": 70},
                    headers=h)
    assert r.status_code == 201


def test_champ_manual(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    libre = _creer(client, h, targetValue=3)
    lie = _creer(client, h, linkedType="weight_target", targetValue=70)
    assert _objectif(client, h, libre)["manual"] is True
    assert _objectif(client, h, lie)["manual"] is False
    # Un objectif porté par un compteur de séances n'est pas manuel non plus.
    db = SessionLocal()
    db.get(models.Goal, libre).linked_metric = "sport_sessions"
    db.commit()
    db.close()
    assert _objectif(client, h, libre)["manual"] is False


def test_progression_a_la_main_puis_atteinte_automatique(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    goal_id = _creer(client, h, targetValue=4)

    r = _modifier(client, h, goal_id, currentValue=1)
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["id"] == goal_id and g["current_value"] == 1 and g["percent"] == 25
    assert g["completed"] is False and g["manual"] is True
    assert _completed_at(goal_id) is None

    # Atteindre la cible pose completed_at ; au-delà, la valeur est bornée.
    g = _modifier(client, h, goal_id, currentValue=9).json()
    assert g["current_value"] == 4 and g["percent"] == 100 and g["completed"] is True
    assert _completed_at(goal_id) is not None
    assert _objectif(client, h, goal_id)["completed"] is True

    # Redescendre sous la cible retire la réussite.
    g = _modifier(client, h, goal_id, currentValue=2).json()
    assert g["current_value"] == 2 and g["completed"] is False
    assert _completed_at(goal_id) is None


def test_marquer_atteint_puis_rouvrir(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    goal_id = _creer(client, h)

    g = _modifier(client, h, goal_id, completed=True).json()
    assert g["completed"] is True and g["current_value"] == 1 and g["percent"] == 100
    assert _completed_at(goal_id) is not None

    g = _modifier(client, h, goal_id, completed=False).json()
    assert g["completed"] is False and g["current_value"] == 0 and g["percent"] == 0
    assert _completed_at(goal_id) is None

    # Rouvrir un objectif à étapes : la valeur n'est remise à 0 que si elle
    # était à la cible.
    etapes = _creer(client, h, targetValue=5)
    _modifier(client, h, etapes, currentValue=3)
    g = _modifier(client, h, etapes, completed=False).json()
    assert g["current_value"] == 3 and g["completed"] is False
    g = _modifier(client, h, etapes, completed=True).json()
    assert g["current_value"] == 5 and g["completed"] is True
    g = _modifier(client, h, etapes, completed=False).json()
    assert g["current_value"] == 0 and g["completed"] is False


def test_refus_sur_un_objectif_lie(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    lie = _creer(client, h, linkedType="weight_target", targetValue=70)
    for corps in ({"currentValue": 3}, {"completed": True}):
        r = _modifier(client, h, lie, **corps)
        assert r.status_code == 400
        assert r.json()["detail"] == "Cet objectif avance tout seul."
    # Le libellé, le poids et la cible restent modifiables.
    r = _modifier(client, h, lie, label="Peser 68 kg", targetValue=68, weight=3)
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Peser 68 kg" and r.json()["target_value"] == 68 and r.json()["weight"] == 3


def test_modifier_libelle_cible_et_poids(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    goal_id = _creer(client, h, targetValue=4)
    _modifier(client, h, goal_id, currentValue=2)

    g = _modifier(client, h, goal_id, label="  Vendre l'appart  ", weight=3, targetValue=8).json()
    assert g["label"] == "Vendre l'appart" and g["weight"] == 3 and g["target_value"] == 8
    assert g["current_value"] == 2 and g["percent"] == 25

    # Baisser la cible sous la valeur actuelle : bornée, donc atteint.
    g = _modifier(client, h, goal_id, targetValue=1).json()
    assert g["current_value"] == 1 and g["completed"] is True

    assert _modifier(client, h, goal_id, weight=4).status_code == 422
    assert _modifier(client, h, goal_id, targetValue=0).status_code == 422
    assert _modifier(client, h, goal_id, currentValue=-1).status_code == 422
    assert _modifier(client, h, goal_id, label="   ").status_code == 400


def test_suppression(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    goal_id = _creer(client, h)
    assert client.delete(f"/goals/{goal_id}", headers=h).status_code == 204
    assert all(g["id"] != goal_id for g in client.get("/goals", headers=h).json()["goals"])
    assert client.delete(f"/goals/{goal_id}", headers=h).status_code == 404
    assert _modifier(client, h, goal_id, label="x").status_code == 404


def test_objectif_d_un_autre_compte_est_introuvable(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    goal_id = _creer(client, h_a, targetValue=2)

    r = _modifier(client, h_b, goal_id, currentValue=1)
    assert r.status_code == 404 and r.json()["detail"] == "Objectif introuvable"
    assert client.delete(f"/goals/{goal_id}", headers=h_b).status_code == 404
    # Rien n'a bougé chez le propriétaire.
    g = _objectif(client, h_a, goal_id)
    assert g["current_value"] == 0 and g["label"] == "Vendre l'appartement au Maroc"


def test_personnage_l_evenement_part_a_l_atteinte_et_se_retire_a_la_reouverture(
        client, nouveau_compte, monkeypatch):
    retraits = []
    monkeypatch.setattr(routeur_goals.personnage_hooks, "retrait",
                        lambda db, user, source, source_id: retraits.append((source, source_id)))
    _, _, h, _ = nouveau_compte()
    goal_id = _creer(client, h, targetValue=2)

    _modifier(client, h, goal_id, completed=True)
    assert retraits == []                       # atteint : rien à retirer
    _modifier(client, h, goal_id, currentValue=1)
    assert retraits == [("goal_completed", goal_id)]

    # Rouvrir un objectif déjà ouvert ne retire rien de plus.
    _modifier(client, h, goal_id, completed=False)
    assert len(retraits) == 1

    # Supprimer un objectif atteint retire aussi son événement.
    _modifier(client, h, goal_id, completed=True)
    client.delete(f"/goals/{goal_id}", headers=h)
    assert retraits[-1] == ("goal_completed", goal_id) and len(retraits) == 2


def test_reinitialisation_remet_l_objectif_manuel_a_zero(client, nouveau_compte):
    _, mdp, h, _ = nouveau_compte()
    goal_id = _creer(client, h, targetValue=3)
    _modifier(client, h, goal_id, completed=True)
    assert _objectif(client, h, goal_id)["completed"] is True

    r = client.post("/me/reset/progression", json={"password": mdp}, headers=h)
    assert r.status_code == 204
    g = _objectif(client, h, goal_id)
    assert g["current_value"] == 0 and g["completed"] is False and g["percent"] == 0
    assert _completed_at(goal_id) is None
