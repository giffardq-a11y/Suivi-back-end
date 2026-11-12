"""Tableau partagé : lien public en lecture seule, catégories du jour, proche."""
from datetime import datetime, timedelta, timezone

from app import models
from app.database import SessionLocal


def _cats(personne) -> dict:
    return {c["key"]: c for c in personne["today"]["categories"]}


def _nouveau_tableau(client, h, nom="Maison") -> str:
    r = client.post("/boards", json={"name": nom}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _lien(client, h, board_id=None) -> str:
    """Chemin public d'un tableau (créé s'il n'est pas donné)."""
    board_id = board_id or _nouveau_tableau(client, h)
    r = client.post(f"/boards/{board_id}/link", headers=h)
    assert r.status_code == 201, r.text
    return f"/board/{r.json()['token']}"


def test_lien_public_sans_connexion_et_donnees_agregees(client, nouveau_compte):
    email, _, h, _ = nouveau_compte()
    board_id = _nouveau_tableau(client, h)
    assert client.get("/boards", headers=h).json()["boards"][0]["link"]["enabled"] is False
    chemin = _lien(client, h, board_id)

    r = client.get(chemin)  # aucune en-tête d'autorisation
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    corps = r.json()
    assert len(corps["people"]) == 1
    moi = corps["people"][0]
    cats = _cats(moi)
    # Compte neuf, tous modules actifs, aucune habitude : cinq catégories.
    assert set(cats) == {"sport", "nutrition", "addictions", "hydratation", "sommeil"}
    assert not cats["sport"]["done"] and not cats["nutrition"]["done"] and cats["addictions"]["done"]
    # Ni pesées (données de santé que la page n'affiche pas) ni e-mail.
    assert moi["pointsMax"] == 35 and "weights" not in moi
    # Jamais sur un écran commun : cycle, humeur, budget.
    assert not {"cycle", "humeur", "budget"} & set(cats)
    # Ni e-mail ni identifiant dans la réponse publique.
    assert email not in r.text and "user_id" not in r.text
    assert corps["name"] == "Maison"
    assert client.get("/boards", headers=h).json()["boards"][0]["link"]["lastReadAt"] is not None


def test_cases_du_jour_points_et_pesee(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    chemin = _lien(client, h)

    assert client.post("/training/runs", json={"distanceKm": 3, "durationMin": 25}, headers=h).status_code == 201
    assert client.post("/diet/meals", json={"label": "Saumon", "calories": 650, "type": "diner"}, headers=h).status_code == 201
    assert client.post("/weight", json={"weightKg": 85.4}, headers=h).status_code == 201

    moi = client.get(chemin).json()["people"][0]
    cats = _cats(moi)
    assert cats["sport"]["done"] and cats["sport"]["value"] == "25 min"
    assert cats["nutrition"]["done"] and cats["nutrition"]["value"] == "650 / 2000 kcal"
    assert moi["points"] >= 3 and moi["streakDays"] >= 1
    assert "weights" not in moi and "85.4" not in client.get(chemin).text

    # Dépasser le budget calorique décoche « manger ».
    assert client.post("/diet/meals", json={"label": "Excès", "calories": 3000, "type": "collation"}, headers=h).status_code == 201
    assert _cats(client.get(chemin).json()["people"][0])["nutrition"]["done"] is False


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
        assert _cats(client.get(chemin).json()["people"][0])["addictions"]["done"] is True
        db.add(models.ConsumptionEntry(user_id=user_id, substance_id=biere.id, occurred_at=datetime.now(timezone.utc)))
        db.commit()
    finally:
        db.close()
    assert _cats(client.get(chemin).json()["people"][0])["addictions"]["done"] is False


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
    sport = _cats(client.get(chemin).json()["people"][0])["sport"]
    assert sport["done"] is True and sport["value"] == "8200 pas"


def test_remplacement_et_suppression_du_lien(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    board_id = _nouveau_tableau(client, h)
    ancien = _lien(client, h, board_id)
    nouveau = _lien(client, h, board_id)
    assert ancien != nouveau
    assert client.get(ancien).status_code == 404
    assert client.get(nouveau).status_code == 200
    assert client.delete(f"/boards/{board_id}/link", headers=h).status_code == 204
    assert client.get(nouveau).status_code == 404
    assert client.get("/board/jeton-invente").status_code == 404
    assert client.post(f"/boards/{board_id}/link").status_code in (401, 403)


def test_lien_proche_ne_suffit_pas(client, nouveau_compte):
    """Être lié comme « proche » ne fait pas apparaître sur un tableau : il
    faut y être invité et accepter."""
    _, _, h_a, _ = nouveau_compte()
    email_b, _, h_b, _ = nouveau_compte()
    chemin = _lien(client, h_a)
    assert client.post("/partner/invite", json={"email": email_b}, headers=h_a).status_code == 200
    invitation = client.get("/partner", headers=h_b).json()["pendingReceived"][0]["linkId"]
    assert client.post(f"/partner/invites/{invitation}/accept", headers=h_b).status_code == 200
    assert len(client.get(chemin).json()["people"]) == 1


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


def test_hydratation_sommeil_et_modules_inactifs(client, nouveau_compte, nouveau_compte_avec_modules):
    _, _, h, user_id = nouveau_compte()
    chemin = _lien(client, h)
    jour = client.get(chemin).json()["people"][0]["today"]["date"]
    assert client.put("/hydration/settings", json={"dailyGoalMl": 1000}, headers=h).status_code == 200
    assert client.post("/hydration", json={"amountMl": 500}, headers=h).status_code == 201
    assert _cats(client.get(chemin).json()["people"][0])["hydratation"]["done"] is False
    assert client.post("/hydration", json={"amountMl": 500}, headers=h).status_code == 201
    eau = _cats(client.get(chemin).json()["people"][0])["hydratation"]
    assert eau["done"] is True and eau["value"] == "1.0 / 1.0 L"

    db = SessionLocal()
    try:
        fin = datetime.now(timezone.utc)
        db.add(models.SleepLog(user_id=user_id, date_key=jour, started_at=fin - timedelta(hours=8, minutes=10),
                               ended_at=fin, duration_min=490, source="manual"))
        db.commit()
    finally:
        db.close()
    sommeil = _cats(client.get(chemin).json()["people"][0])["sommeil"]
    assert sommeil["done"] is True and sommeil["value"] == "8 h 10 / 8 h 00"

    # Un compte qui n'a choisi que le sport ne montre que le sport.
    _, _, h2, _ = nouveau_compte_avec_modules(["sport"])
    seul = client.get(_lien(client, h2)).json()["people"][0]
    assert set(_cats(seul)) == {"sport"} and seul["pointsMax"] == 7


def test_nom_jamais_tire_de_l_email(client):
    """À l'inscription sans nom, le nom affiché est le début de l'e-mail :
    l'écran commun ne doit pas le montrer."""
    r = client.post("/auth/signup", json={"email": "prenom.nom.tableau@example.com", "password": "motdepasse-test-123"})
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get(_lien(client, h))
    assert "prenom.nom.tableau" not in r.text and r.json()["people"][0]["name"] == "Sans nom"

    db = SessionLocal()
    try:
        db.query(models.User).filter(models.User.email == "prenom.nom.tableau@example.com").update({"display_name": "Quentin"})
        db.commit()
    finally:
        db.close()
    assert client.get(_lien(client, h)).json()["people"][0]["name"] == "Quentin"
