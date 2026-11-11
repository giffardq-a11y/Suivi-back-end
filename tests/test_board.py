"""Tableau partagé : lien public en lecture seule, cases du jour, proche."""
from datetime import datetime, timedelta, timezone

from app import models
from app.database import SessionLocal


def _lien(client, h) -> str:
    r = client.post("/board/share", headers=h)
    assert r.status_code == 201, r.text
    return r.json()["path"]


def test_lien_public_sans_connexion_et_donnees_agregees(client, nouveau_compte):
    email, _, h, _ = nouveau_compte()
    assert client.get("/board/share", headers=h).json()["enabled"] is False
    chemin = _lien(client, h)

    r = client.get(chemin)  # aucune en-tête d'autorisation
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    corps = r.json()
    assert len(corps["people"]) == 1
    moi = corps["people"][0]
    assert moi["today"] == {"date": moi["today"]["date"], "move": False, "eat": False, "clean": True}
    assert moi["pointsMax"] == 21 and moi["weights"] == []
    # Ni e-mail ni identifiant dans la réponse publique.
    assert email not in r.text and "user_id" not in r.text
    assert client.get("/board/share", headers=h).json()["lastReadAt"] is not None


def test_cases_du_jour_points_et_pesee(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    chemin = _lien(client, h)

    assert client.post("/training/runs", json={"distanceKm": 3, "durationMin": 25}, headers=h).status_code == 201
    assert client.post("/diet/meals", json={"label": "Saumon", "calories": 650, "type": "diner"}, headers=h).status_code == 201
    assert client.post("/weight", json={"weightKg": 85.4}, headers=h).status_code == 201

    moi = client.get(chemin).json()["people"][0]
    assert moi["today"]["move"] and moi["today"]["eat"] and moi["today"]["clean"]
    assert moi["points"] >= 3 and moi["streakDays"] >= 1
    assert moi["weights"][-1]["kg"] == 85.4

    # Dépasser le budget calorique décoche « manger ».
    assert client.post("/diet/meals", json={"label": "Excès", "calories": 3000, "type": "collation"}, headers=h).status_code == 201
    assert client.get(chemin).json()["people"][0]["today"]["eat"] is False


def test_consommation_alcool_decoche_sobre(client, nouveau_compte):
    _, _, h, user_id = nouveau_compte()
    chemin = _lien(client, h)
    db = SessionLocal()
    try:
        biere = models.Substance(user_id=user_id, label="Bière", category=models.SubstanceCategory.ALCOHOL)
        the = models.Substance(user_id=user_id, label="Thé", category=models.SubstanceCategory.OTHER)
        db.add_all([biere, the])
        db.commit()
        db.add(models.ConsumptionEntry(user_id=user_id, substance_id=the.id, occurred_at=datetime.now(timezone.utc)))
        db.commit()
        assert client.get(chemin).json()["people"][0]["today"]["clean"] is True
        db.add(models.ConsumptionEntry(user_id=user_id, substance_id=biere.id, occurred_at=datetime.now(timezone.utc)))
        db.commit()
    finally:
        db.close()
    assert client.get(chemin).json()["people"][0]["today"]["clean"] is False


def test_jour_de_repos_actif_par_les_pas(client, nouveau_compte):
    _, _, h, user_id = nouveau_compte()
    chemin = _lien(client, h)
    jour = client.get(chemin).json()["people"][0]["today"]["date"]
    db = SessionLocal()
    try:
        db.add(models.DailySteps(user_id=user_id, date_key=jour, steps=8200))
        db.commit()
    finally:
        db.close()
    assert client.get(chemin).json()["people"][0]["today"]["move"] is True


def test_remplacement_et_suppression_du_lien(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    ancien = _lien(client, h)
    nouveau = _lien(client, h)
    assert ancien != nouveau
    assert client.get(ancien).status_code == 404
    assert client.get(nouveau).status_code == 200
    assert client.delete("/board/share", headers=h).status_code == 204
    assert client.get(nouveau).status_code == 404
    assert client.get("/board/jeton-invente").status_code == 404
    assert client.post("/board/share").status_code in (401, 403)


def test_proche_visible_seulement_s_il_partage_aussi(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    email_b, _, h_b, _ = nouveau_compte()
    chemin = _lien(client, h_a)
    assert client.post("/partner/invite", json={"email": email_b}, headers=h_a).status_code == 200
    invitation = client.get("/partner", headers=h_b).json()["pendingReceived"][0]["linkId"]
    assert client.post(f"/partner/invites/{invitation}/accept", headers=h_b).status_code == 200

    # Lié mais sans lien de partage à lui : le proche n'apparaît pas.
    assert len(client.get(chemin).json()["people"]) == 1
    _lien(client, h_b)
    assert len(client.get(chemin).json()["people"]) == 2


def test_serie_sur_plusieurs_jours(client, nouveau_compte):
    _, _, h, user_id = nouveau_compte()
    chemin = _lien(client, h)
    maintenant = datetime.now(timezone.utc).replace(hour=12, minute=0)
    db = SessionLocal()
    try:
        for recul in (0, 1, 2):
            quand = maintenant - timedelta(days=recul)
            db.add(models.Run(user_id=user_id, distance_km=3, duration_min=25, occurred_at=quand))
            db.add(models.Meal(user_id=user_id, label="Repas", calories=1800, type="diner", occurred_at=quand))
        db.commit()
    finally:
        db.close()
    assert client.get(chemin).json()["people"][0]["streakDays"] == 3
