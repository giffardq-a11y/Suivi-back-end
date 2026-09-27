"""Module Hydratation : verres, objectif, séries, cloisonnement."""
from datetime import datetime, timedelta, timezone

def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_ajout_lecture_suppression_et_objectif(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    r = client.put("/hydration/settings", json={"dailyGoalMl": 1000, "glassSizes": [200, 500]}, headers=h)
    assert r.status_code == 200 and r.json()["dailyGoalMl"] == 1000 and r.json()["glassSizes"] == [200, 500]

    ids = [client.post("/hydration", json={"amountMl": 500}, headers=h).json()["id"] for _ in range(3)]
    jour = client.get("/hydration", headers=h).json()
    assert jour["totalMl"] == 1500 and jour["goalReached"] and len(jour["logs"]) == 3
    # Un seul événement : celui du verre qui fait franchir l'objectif.
    assert [s for s, _ in evenements] == ["hydration_goal"]

    assert client.delete(f"/hydration/{ids[0]}", headers=h).status_code == 204
    assert client.get("/hydration", headers=h).json()["totalMl"] == 1000
    assert client.delete(f"/hydration/{ids[0]}", headers=h).status_code == 404


def test_objectif_suggere_selon_le_poids(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    assert client.get("/hydration", headers=h).json()["goalMl"] == 2000
    assert client.post("/weight", json={"weightKg": 70}, headers=h).status_code == 201
    reglages = client.get("/hydration", headers=h).json()["settings"]
    assert reglages["suggestedGoalMl"] == 2300  # 70 x 33 = 2310, arrondi aux 50 ml
    assert "pas un conseil médical" in reglages["suggestionNote"]


def test_cloisonnement(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    id_a = client.post("/hydration", json={"amountMl": 250}, headers=h_a).json()["id"]
    assert client.get("/hydration", headers=h_b).json()["totalMl"] == 0
    assert client.delete(f"/hydration/{id_a}", headers=h_b).status_code == 404
    assert client.get("/hydration", headers=h_a).json()["totalMl"] == 250


def test_validation(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    assert client.post("/hydration", json={"amountMl": 0}, headers=h).status_code == 422
    assert client.put("/hydration/settings", json={"reminderStart": "25:00"}, headers=h).status_code == 422
    assert client.put("/hydration/settings", json={"glassSizes": []}, headers=h).status_code == 422


def test_statistiques_et_series(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    client.put("/hydration/settings", json={"dailyGoalMl": 1000}, headers=h)
    maintenant = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    # Objectif atteint hier et avant-hier, pas il y a 3 jours, atteint il y a 4 et 5 jours.
    for jours, ml in [(1, 1000), (2, 1200), (3, 400), (4, 1000), (5, 1000)]:
        client.post("/hydration", json={"amountMl": ml, "occurredAtMs": _ms(maintenant - timedelta(days=jours))}, headers=h)
    s = client.get("/hydration/stats?days=7", headers=h).json()
    assert len(s["perDay"]) == 7
    assert s["daysGoalReached"] == 4
    # Aujourd'hui pas encore atteint : la série part d'hier.
    assert s["currentStreak"] == 2
    assert s["bestStreak"] == 2
    assert s["averageMl"] == round((1000 + 1200 + 400 + 1000 + 1000) / 7)
