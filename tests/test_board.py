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
    # Net comme dans le compte : 650 mangés moins les 250 kcal de la course de 25 min.
    assert cats["nutrition"]["done"] and cats["nutrition"]["value"] == "400 / 2000 kcal"
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


# --- Cohérence avec le compte : mêmes règles que l'app, jour par jour ---

MERCREDI = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)  # jour fixe : tests indépendants de l'heure


def _etat(user_id, maintenant=MERCREDI) -> dict:
    """Catégories du jour calculées à `maintenant` (état_personne direct : le
    jour affiché est celui de `maintenant`)."""
    from app.services.board import etat_personne
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        return _cats(etat_personne(db, user, maintenant))
    finally:
        db.close()


def _ajouter(*lignes):
    db = SessionLocal()
    try:
        db.add_all(lignes)
        db.commit()
        for ligne in lignes:
            db.refresh(ligne)  # garde id et champs lisibles après fermeture
    finally:
        db.close()


def test_jour_decoupe_en_utc_comme_le_compte(client, nouveau_compte):
    """Un verre bu à 23 h 30 UTC (0 h 30 à Paris) compte pour la veille des
    deux côtés : tableau et GET /hydration."""
    _, _, h, user_id = nouveau_compte()
    veille = MERCREDI - timedelta(days=1)
    assert client.put("/hydration/settings", json={"dailyGoalMl": 500}, headers=h).status_code == 200
    _ajouter(models.WaterLog(user_id=user_id, amount_ml=500, occurred_at=veille.replace(hour=23, minute=30)))

    assert client.get(f"/hydration?date={veille.date().isoformat()}", headers=h).json()["totalMl"] == 500
    assert client.get(f"/hydration?date={MERCREDI.date().isoformat()}", headers=h).json()["totalMl"] == 0
    assert _etat(user_id, veille)["hydratation"]["done"] is True
    assert _etat(user_id, MERCREDI)["hydratation"]["done"] is False


def test_habitude_hebdo_pas_due_chaque_jour(client, nouveau_compte):
    _, _, h, user_id = nouveau_compte()
    nage = models.Habit(user_id=user_id, key="nage", label="Natation", weekly_target=3)
    marche = models.Habit(user_id=user_id, key="marche", label="Marche")
    _ajouter(nage, marche)
    # Seule la quotidienne est attendue.
    habitudes = _etat(user_id)["habitudes"]
    assert habitudes["value"] == "0 / 1" and habitudes["done"] is False
    # Une hebdo faite un jour libre compte pour, jamais contre.
    _ajouter(models.HabitLog(habit_id=nage.id, occurred_at=MERCREDI))
    assert _etat(user_id)["habitudes"]["value"] == "1 / 2"
    _ajouter(models.HabitLog(habit_id=marche.id, occurred_at=MERCREDI))
    assert _etat(user_id)["habitudes"] == {"key": "habitudes", "label": "Habitudes", "done": True, "value": "2 / 2"}
    # Un jour sans rien d'attendu (que l'hebdo, non faite) : catégorie absente.
    db = SessionLocal()
    try:
        db.query(models.Habit).filter(models.Habit.id == marche.id).update({"active": False})
        db.commit()
    finally:
        db.close()
    assert "habitudes" not in _etat(user_id, MERCREDI + timedelta(days=1))


def test_habitude_a_jours_fixes_due_ces_jours_la(client, nouveau_compte):
    _, _, _, user_id = nouveau_compte()
    _ajouter(models.Habit(user_id=user_id, key="nage", label="Natation", weekly_target=3, days_of_week="2"))
    assert _etat(user_id)["habitudes"]["value"] == "0 / 1"  # mercredi = 2
    assert "habitudes" not in _etat(user_id, MERCREDI + timedelta(days=1))


def test_nutrition_sur_le_net_apres_sport(client, nouveau_compte):
    _, _, _, user_id = nouveau_compte()
    _ajouter(
        models.Meal(user_id=user_id, label="Gros repas", calories=2300, type="diner", occurred_at=MERCREDI),
        models.Run(user_id=user_id, distance_km=8, duration_min=50, calories_burned=500, occurred_at=MERCREDI),
    )
    nutrition = _etat(user_id)["nutrition"]
    assert nutrition["done"] is True and nutrition["value"] == "1800 / 2000 kcal"
    # Sans la dépense, le même repas dépasse le budget.
    _, _, _, autre = nouveau_compte()
    _ajouter(models.Meal(user_id=autre, label="Gros repas", calories=2300, type="diner", occurred_at=MERCREDI))
    assert _etat(autre)["nutrition"]["done"] is False


def test_reduction_progressive_consommation_dans_la_limite(client, nouveau_compte):
    _, _, _, user_id = nouveau_compte()
    db = SessionLocal()
    try:
        alcool = db.query(models.Substance).filter(
            models.Substance.user_id == user_id, models.Substance.category == models.SubstanceCategory.ALCOHOL).first()
        alcool.reduction_start_value = 3
        alcool.reduction_step_per_week = 1
        alcool.reduction_start_date = MERCREDI.date()  # limite du jour : 3
        db.commit()
        alcool_id = alcool.id
    finally:
        db.close()
    _ajouter(models.ConsumptionEntry(user_id=user_id, substance_id=alcool_id, quantity=2, occurred_at=MERCREDI))
    addictions = _etat(user_id)["addictions"]
    assert addictions["done"] is True and addictions["value"] == "dans la limite"
    _ajouter(models.ConsumptionEntry(user_id=user_id, substance_id=alcool_id, quantity=2, occurred_at=MERCREDI))
    addictions = _etat(user_id)["addictions"]
    assert addictions["done"] is False and addictions["value"] == "consommation"


def test_sommeil_une_nuit_par_jour_importee_prioritaire(client, nouveau_compte):
    _, _, _, user_id = nouveau_compte()
    jour = MERCREDI.date().isoformat()
    fin = MERCREDI
    _ajouter(
        models.SleepLog(user_id=user_id, date_key=jour, started_at=fin - timedelta(minutes=390), ended_at=fin,
                        duration_min=390, source="manual"),
        models.SleepLog(user_id=user_id, date_key=jour, started_at=fin - timedelta(minutes=380), ended_at=fin,
                        duration_min=380, source="health_connect", external_id="nuit-1"),
    )
    sommeil = _etat(user_id)["sommeil"]
    assert sommeil["value"] == "6 h 20 / 8 h 00" and sommeil["done"] is False


def test_seance_sans_duree_affiche_seance_faite(client, nouveau_compte):
    _, _, _, user_id = nouveau_compte()
    _ajouter(models.StrengthSession(user_id=user_id, duration_min=0, occurred_at=MERCREDI))
    sport = _etat(user_id)["sport"]
    assert sport["done"] is True and sport["value"] == "séance faite"
