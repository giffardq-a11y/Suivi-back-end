"""Module Humeur et journal : humeur, envies (résistance calculée à la
lecture), gratitude, cloisonnement, statistiques."""
from datetime import datetime, timedelta, timezone


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _alcool(client, h) -> str:
    return next(s for s in client.get("/substances", headers=h).json() if s["category"] == "alcohol")["id"]


def test_humeur_ajout_journal_suppression(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    r = client.post("/mood", json={"mood": 4, "energy": 3, "tags": ["Sport", "sport", " famille "],
                                   "note": "Belle course ce matin"}, headers=h)
    assert r.status_code == 201
    humeur = r.json()
    assert humeur["tags"] == ["sport", "famille"]
    client.post("/mood", json={"mood": 2, "tags": ["travail"]}, headers=h)
    assert ("mood_entry", humeur["id"]) in evenements

    assert len(client.get("/mood", headers=h).json()) == 2
    assert [e["id"] for e in client.get("/mood?tag=sport", headers=h).json()] == [humeur["id"]]
    assert [e["id"] for e in client.get("/mood?q=course", headers=h).json()] == [humeur["id"]]

    assert client.delete(f"/mood/{humeur['id']}", headers=h).status_code == 204
    assert client.delete(f"/mood/{humeur['id']}", headers=h).status_code == 404
    assert len(client.get("/mood", headers=h).json()) == 1


def test_validation(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    assert client.post("/mood", json={"mood": 6}, headers=h).status_code == 422
    assert client.post("/cravings", json={"intensity": 0}, headers=h).status_code == 422
    assert client.post("/gratitude", json={"items": []}, headers=h).status_code == 422
    assert client.post("/gratitude", json={"items": ["a", "b", "c", "d"]}, headers=h).status_code == 422


def test_envie_resistee_cedee_en_cours(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    alcool = _alcool(client, h)
    maintenant = datetime.now(timezone.utc)

    # Il y a 5 h, pas de consommation ensuite : résistée.
    resistee = client.post("/cravings", json={"intensity": 4, "substanceId": alcool, "trigger": ["Stress"],
                                              "occurredAtMs": _ms(maintenant - timedelta(hours=5))}, headers=h).json()
    assert resistee["status"] == "resisted" and resistee["resisted"] is True and resistee["trigger"] == ["stress"]
    # Il y a 4 h, suivie d'un verre 1 h plus tard : cédée.
    cedee = client.post("/cravings", json={"intensity": 5, "substanceId": alcool,
                                           "occurredAtMs": _ms(maintenant - timedelta(hours=4))}, headers=h).json()
    client.post("/entries", json={"substance_id": alcool,
                                  "occurred_at": (maintenant - timedelta(hours=3)).isoformat()}, headers=h)
    # À l'instant : on ne sait pas encore.
    en_cours = client.post("/cravings", json={"intensity": 2, "substanceId": alcool}, headers=h).json()
    assert en_cours["status"] == "pending" and en_cours["resisted"] is None

    statuts = {e["id"]: e["status"] for e in client.get("/cravings", headers=h).json()}
    # La consommation saisie après coup a corrigé l'envie de -4 h.
    assert statuts == {resistee["id"]: "resisted", cedee["id"]: "consumed", en_cours["id"]: "pending"}
    signalees = {sid for source, sid in evenements if source == "craving_resisted"}
    assert signalees == {resistee["id"]}

    # Une consommation d'une AUTRE substance ne compte pas contre l'envie.
    autre = client.post("/substances", json={"label": "Sucre"}, headers=h).json()["id"]
    envie = client.post("/cravings", json={"intensity": 3, "substanceId": alcool,
                                           "occurredAtMs": _ms(maintenant - timedelta(hours=10))}, headers=h).json()
    client.post("/entries", json={"substance_id": autre,
                                  "occurred_at": (maintenant - timedelta(hours=9)).isoformat()}, headers=h)
    assert next(e for e in client.get("/cravings", headers=h).json() if e["id"] == envie["id"])["status"] == "resisted"


def test_gratitude_une_entree_par_jour(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    premiere = client.post("/gratitude", json={"items": ["Le soleil", " "]}, headers=h).json()
    assert premiere["items"] == ["Le soleil"]
    seconde = client.post("/gratitude", json={"items": ["Le soleil", "Un appel de ma sœur"]}, headers=h).json()
    assert seconde["id"] == premiere["id"]
    client.post("/gratitude", json={"items": ["Hier"], "dateKey": "2026-01-01"}, headers=h)
    lecture = client.get("/gratitude", headers=h).json()
    assert len(lecture) == 2 and lecture[0]["items"] == ["Le soleil", "Un appel de ma sœur"]
    assert ("mood_entry", premiere["id"]) in evenements


def test_cloisonnement(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    humeur = client.post("/mood", json={"mood": 3}, headers=h_a).json()
    client.post("/cravings", json={"intensity": 3}, headers=h_a)
    client.post("/gratitude", json={"items": ["x"]}, headers=h_a)
    assert client.get("/mood", headers=h_b).json() == []
    assert client.get("/cravings", headers=h_b).json() == []
    assert client.get("/gratitude", headers=h_b).json() == []
    assert client.delete(f"/mood/{humeur['id']}", headers=h_b).status_code == 404
    # La substance d'un autre compte n'est pas utilisable.
    assert client.post("/cravings", json={"intensity": 3, "substanceId": _alcool(client, h_a)},
                       headers=h_b).status_code == 404
    assert len(client.get("/mood", headers=h_a).json()) == 1


def test_statistiques(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    alcool = _alcool(client, h)
    midi = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    # J-1 : bonne journée (5, sport), J-2 : mauvaise (1 et 2, travail + stress) avec un verre, J-3 : neutre (3).
    client.post("/mood", json={"mood": 5, "tags": ["sport"], "occurredAtMs": _ms(midi - timedelta(days=1))}, headers=h)
    for m in (1, 2):
        client.post("/mood", json={"mood": m, "tags": ["travail", "stress"],
                                   "occurredAtMs": _ms(midi - timedelta(days=2))}, headers=h)
    client.post("/mood", json={"mood": 3, "occurredAtMs": _ms(midi - timedelta(days=3))}, headers=h)
    client.post("/entries", json={"substance_id": alcool, "occurred_at": (midi - timedelta(days=2)).isoformat()},
                headers=h)
    client.post("/cravings", json={"intensity": 4, "substanceId": alcool,
                                   "occurredAtMs": _ms(midi - timedelta(days=2, hours=1))}, headers=h)

    s = client.get("/mood/stats?days=10", headers=h).json()
    assert s["entries"] == 4
    assert s["avgMood"] == round((5 + 1 + 2 + 3) / 4, 2)
    assert s["goodDays"] == 1 and s["badDays"] == 1
    assert s["topTagsGoodDays"] == [{"tag": "sport", "count": 1}]
    assert {t["tag"]: t["count"] for t in s["topTagsBadDays"]} == {"travail": 2, "stress": 2}
    assert sum(w["entries"] for w in s["weekly"]) == 4
    assert s["cravings"]["total"] == 1 and s["cravings"]["consumed"] == 1 and sum(s["cravings"]["byHour"]) == 1
    mc = s["moodVsConsumption"]
    assert mc["daysWithConsumption"] == 1 and mc["avgMoodWithConsumption"] == 1.5
    assert mc["daysWithoutConsumption"] == 2 and mc["avgMoodWithoutConsumption"] == 4.0
