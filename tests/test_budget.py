"""Module Budget : dépenses, catégories, résumé du mois, cagnottes alimentées
par les économies (alcool, tabac), cloisonnement."""
from datetime import date, datetime, timedelta, timezone


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_categories_par_defaut_et_remplacement(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    cles = [c["key"] for c in client.get("/budget/categories", headers=h).json()]
    assert cles == ["courses", "restaurants", "transport", "logement", "loisirs", "sante", "abonnements", "autre"]

    r = client.put("/budget/categories", json={"categories": [
        {"key": "courses", "label": "Supermarché", "icon": "🛒", "monthlyLimit": 300},
        {"key": "velo", "label": "Vélo", "monthlyLimit": 50},
    ]}, headers=h)
    assert r.status_code == 200
    assert [(c["key"], c["label"], c["monthlyLimit"]) for c in r.json()] == [
        ("courses", "Supermarché", 300), ("velo", "Vélo", 50)]
    assert client.put("/budget/categories", json={"categories": [{"key": "A B", "label": "x"}]},
                      headers=h).status_code == 422
    assert client.put("/budget/categories", json={"categories": [{"key": "a", "label": "x"}, {"key": "a", "label": "y"}]},
                      headers=h).status_code == 422


def test_depenses_et_resume_du_mois(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    client.put("/budget/categories", json={"categories": [
        {"key": "courses", "label": "Courses", "monthlyLimit": 200},
        {"key": "loisirs", "label": "Loisirs", "monthlyLimit": 100},
        {"key": "autre", "label": "Autre"},
    ]}, headers=h)
    # Mois passé et terminé : 2026-08.
    aout = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    ids = [client.post("/expenses", json={"amount": a, "categoryKey": k, "occurredAtMs": _ms(aout)}, headers=h).json()["id"]
           for a, k in [(120.5, "courses"), (30, "loisirs"), (15, "autre")]]
    client.post("/expenses", json={"amount": 999, "categoryKey": "courses",
                                   "occurredAtMs": _ms(datetime(2026, 9, 1, tzinfo=timezone.utc))}, headers=h)
    assert client.post("/expenses", json={"amount": 5, "categoryKey": "inconnue"}, headers=h).status_code == 400
    assert client.post("/expenses", json={"amount": -5, "categoryKey": "autre"}, headers=h).status_code == 422

    assert len(client.get("/expenses?month=2026-08", headers=h).json()) == 3
    s = client.get("/budget/summary?month=2026-08", headers=h).json()
    assert s["totalSpent"] == 165.5 and s["totalBudget"] == 300 and s["remaining"] == 134.5
    assert s["underBudget"] is True and s["monthComplete"] is True
    courses = next(c for c in s["byCategory"] if c["key"] == "courses")
    assert courses["spent"] == 120.5 and courses["remaining"] == 79.5 and courses["percent"] == 60
    assert ("budget_month_under", "2026-08") in evenements

    # Catégorie retirée : ses dépenses restent comptées, signalées « archived ».
    client.put("/budget/categories", json={"categories": [{"key": "courses", "label": "Courses", "monthlyLimit": 200}]},
               headers=h)
    s = client.get("/budget/summary?month=2026-08", headers=h).json()
    assert s["totalSpent"] == 165.5
    assert {c["key"] for c in s["byCategory"] if c["archived"]} == {"loisirs", "autre"}

    assert client.delete(f"/expenses/{ids[0]}", headers=h).status_code == 204
    assert client.delete(f"/expenses/{ids[0]}", headers=h).status_code == 404
    assert client.get("/budget/summary?month=2026-08", headers=h).json()["totalSpent"] == 45
    assert client.get("/budget/summary?month=2026-13", headers=h).status_code == 422


def test_mois_au_dessus_du_budget_ou_sans_budget(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    client.post("/expenses", json={"amount": 50, "categoryKey": "autre",
                                   "occurredAtMs": _ms(datetime(2026, 7, 5, tzinfo=timezone.utc))}, headers=h)
    # Catégories par défaut sans limite : pas de budget, ni sous ni au-dessus.
    assert client.get("/budget/summary?month=2026-07", headers=h).json()["underBudget"] is None
    client.put("/budget/categories", json={"categories": [{"key": "autre", "label": "Autre", "monthlyLimit": 40}]},
               headers=h)
    assert client.get("/budget/summary?month=2026-07", headers=h).json()["underBudget"] is False
    assert not [e for e in evenements if e[0] == "budget_month_under"]


def test_cagnottes_et_economies(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    alcool = next(s for s in client.get("/substances", headers=h).json() if s["category"] == "alcohol")
    arret = (date.today() - timedelta(days=10)).isoformat()
    assert client.put(f"/substances/{alcool['id']}", json={"quit_date": arret}, headers=h).status_code == 200

    economies = client.get("/savings-pots", headers=h).json()["sobrietySavings"]
    assert economies["total"] > 0 and economies["available"] == economies["total"]
    total = economies["total"]

    pot = client.post("/savings-pots", json={"label": "Vélo", "targetAmount": total + 10,
                                             "source": "sobriety_savings", "rewardId": "reward-1"}, headers=h).json()
    assert pot["reward"]["label"] == "Un resto" and pot["currentAmount"] == 0
    assert client.post("/savings-pots", json={"label": "x", "targetAmount": 10, "rewardId": "nope"},
                       headers=h).status_code == 404

    # « Verser mes économies » : tout le disponible, une seule fois.
    r = client.post(f"/savings-pots/{pot['id']}/transfer", json={}, headers=h)
    assert r.status_code == 201 and r.json()["transferred"] == total
    assert r.json()["sobrietySavings"]["available"] == 0
    assert client.post(f"/savings-pots/{pot['id']}/transfer", json={}, headers=h).status_code == 400
    assert not [e for e in evenements if e[0] == "savings_pot_achieved"]

    # Versement manuel qui fait atteindre l'objectif : signalé une fois.
    r = client.post(f"/savings-pots/{pot['id']}/transfer", json={"amount": 10, "source": "manual"}, headers=h)
    assert r.json()["achievedAt"] is not None and r.json()["percent"] == 100
    client.post(f"/savings-pots/{pot['id']}/transfer", json={"amount": 5, "source": "manual"}, headers=h)
    assert evenements.count(("savings_pot_achieved", pot["id"])) == 1

    assert client.post(f"/savings-pots/{pot['id']}/transfer", json={"source": "manual"}, headers=h).status_code == 422
    pots = client.get("/savings-pots", headers=h).json()["pots"]
    assert pots[0]["currentAmount"] == round(total + 15, 2) and pots[0]["rewardFunded"] is (total + 15 >= 40)


def test_cloisonnement(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    depense = client.post("/expenses", json={"amount": 12, "categoryKey": "courses"}, headers=h_a).json()
    pot = client.post("/savings-pots", json={"label": "Voyage", "targetAmount": 500}, headers=h_a).json()
    client.put("/budget/categories", json={"categories": [{"key": "perso_a", "label": "A"}]}, headers=h_a)

    assert client.get("/expenses", headers=h_b).json() == []
    assert client.get("/savings-pots", headers=h_b).json()["pots"] == []
    assert "perso_a" not in {c["key"] for c in client.get("/budget/categories", headers=h_b).json()}
    assert client.get("/budget/summary", headers=h_b).json()["totalSpent"] == 0
    assert client.delete(f"/expenses/{depense['id']}", headers=h_b).status_code == 404
    assert client.post(f"/savings-pots/{pot['id']}/transfer", json={"amount": 5, "source": "manual"},
                       headers=h_b).status_code == 404
    assert len(client.get("/expenses", headers=h_a).json()) == 1
