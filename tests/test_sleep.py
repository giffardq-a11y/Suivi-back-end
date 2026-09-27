"""Module Sommeil : saisie manuelle, cohabitation avec l'import de la montre,
cloisonnement, statistiques et observations."""
from datetime import datetime, timedelta, timezone


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _minuit(jours_avant: int) -> datetime:
    """Minuit UTC du jour J - jours_avant."""
    return (datetime.now(timezone.utc) - timedelta(days=jours_avant)).replace(hour=0, minute=0, second=0, microsecond=0)


def _nuit(client, h, jours_avant: int, heures: float, coucher_h: int = 22, **extra):
    """Nuit qui se termine le jour J - jours_avant, couchée la veille à coucher_h."""
    debut = _minuit(jours_avant) - timedelta(hours=24 - coucher_h)
    fin = debut + timedelta(hours=heures)
    r = client.post("/sleep", json={"startMs": _ms(debut), "endMs": _ms(fin), **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_saisie_modification_suppression(client, nouveau_compte, evenements):
    _, _, h, _ = nouveau_compte()
    courte = _nuit(client, h, 1, 6, quality=2, note="réveillé tôt")
    longue = _nuit(client, h, 0, 8, quality=4)
    assert courte["durationMin"] == 360 and courte["source"] == "manual" and courte["quality"] == 2
    # Seule la nuit de 7 h ou plus est signalée au Personnage.
    assert evenements == [("sleep_7h", longue["id"])]

    lecture = client.get("/sleep", headers=h).json()
    assert [n["id"] for n in lecture["nights"]] == [longue["id"], courte["id"]]
    assert lecture["lastNight"]["deltaToTargetMin"] == 0  # 8 h pour un objectif de 8 h par défaut

    debut = datetime.fromtimestamp(courte["startedAt"] / 1000, tz=timezone.utc)
    r = client.put(f"/sleep/{courte['id']}", json={"endMs": _ms(debut + timedelta(hours=7, minutes=30)), "quality": 3},
                   headers=h)
    assert r.status_code == 200 and r.json()["durationMin"] == 450 and r.json()["quality"] == 3
    assert r.json()["note"] == "réveillé tôt"
    assert ("sleep_7h", courte["id"]) in evenements

    assert client.delete(f"/sleep/{courte['id']}", headers=h).status_code == 204
    assert client.delete(f"/sleep/{courte['id']}", headers=h).status_code == 404
    assert len(client.get("/sleep", headers=h).json()["nights"]) == 1


def test_validation(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    t = _minuit(0)
    assert client.post("/sleep", json={"startMs": _ms(t), "endMs": _ms(t - timedelta(hours=1))}, headers=h).status_code == 400
    assert client.post("/sleep", json={"startMs": _ms(t), "endMs": _ms(t + timedelta(hours=21))}, headers=h).status_code == 400
    assert client.post("/sleep", json={"startMs": _ms(t), "endMs": _ms(t + timedelta(hours=7)), "quality": 6},
                       headers=h).status_code == 422
    assert client.put("/sleep/settings", json={"bedtimeTarget": "23h"}, headers=h).status_code == 422


def test_reglages(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    assert client.get("/sleep", headers=h).json()["settings"]["targetHours"] == 8
    r = client.put("/sleep/settings", json={"targetHours": 7.5, "bedtimeTarget": "23:00",
                                            "routineReminderEnabled": True, "routineReminderTime": "22:30"}, headers=h)
    assert r.status_code == 200
    assert r.json() == {"targetHours": 7.5, "bedtimeTarget": "23:00", "wakeTarget": None,
                        "routineReminderEnabled": True, "routineReminderTime": "22:30"}


def test_cohabitation_avec_l_import_de_la_montre(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    debut = _minuit(2) - timedelta(hours=1)
    montre = {"sleep": [{"externalId": "hc-1", "startMs": _ms(debut), "endMs": _ms(debut + timedelta(hours=7))}]}
    assert client.post("/health/import", json=montre, headers=h).status_code == 201
    _nuit(client, h, 0, 6)

    nuits = client.get("/sleep", headers=h).json()["nights"]
    importee = next(n for n in nuits if n["source"] == "health_connect")
    # Une nuit importée se note, mais ses horaires restent ceux de la montre.
    assert client.put(f"/sleep/{importee['id']}", json={"quality": 5}, headers=h).json()["quality"] == 5
    assert client.put(f"/sleep/{importee['id']}", json={"endMs": _ms(debut + timedelta(hours=9))},
                      headers=h).status_code == 400

    # Une nouvelle synchro ne crée pas de doublon, ne touche ni à la qualité
    # ni à la nuit saisie à la main.
    assert client.post("/health/import", json=montre, headers=h).json()["nuits"] == 0
    nuits = client.get("/sleep", headers=h).json()["nights"]
    assert len(nuits) == 2
    assert next(n for n in nuits if n["source"] == "health_connect")["quality"] == 5
    assert client.get("/health/summary", headers=h).json()["nuits_importees"] == 1


def test_cloisonnement(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    nuit = _nuit(client, h_a, 0, 7)
    assert client.get("/sleep", headers=h_b).json()["nights"] == []
    assert client.put(f"/sleep/{nuit['id']}", json={"quality": 1}, headers=h_b).status_code == 404
    assert client.delete(f"/sleep/{nuit['id']}", headers=h_b).status_code == 404
    assert client.get("/sleep", headers=h_a).json()["nights"][0]["quality"] is None


def test_statistiques_et_observation_alcool(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    alcool = next(s for s in client.get("/substances", headers=h).json() if s["category"] == "alcohol")
    # 3 soirs avec alcool (nuits de 6 h), 3 soirs sans (nuits de 8 h).
    for jours_avant in (1, 2, 3):
        nuit = _nuit(client, h, jours_avant, 6, quality=2)
        coucher = datetime.fromtimestamp(nuit["startedAt"] / 1000, tz=timezone.utc)
        r = client.post("/entries", json={"substance_id": alcool["id"],
                                          "occurred_at": (coucher - timedelta(hours=3)).isoformat()}, headers=h)
        assert r.status_code == 201
    for jours_avant in (4, 5, 6):
        _nuit(client, h, jours_avant, 8, quality=4)

    s = client.get("/sleep/stats?days=10", headers=h).json()
    assert s["nightsCount"] == 6
    assert s["avgDurationMin"] == 420
    assert s["avgQuality"] == 3.0
    assert s["nightsOnTarget"] == 3
    # Couchers tous à 22 h UTC : réguliers (<= 30 min même si un changement
    # d'heure tombe dans la fenêtre et que le fuseau local est disponible).
    assert s["bedtimeStdMin"] <= 30 and len(s["perNight"]) == 6
    obs = {o["key"]: o for o in s["observations"]}
    assert obs["alcohol"]["diffMin"] == -120
    assert obs["alcohol"]["nightsWith"] == 3 and obs["alcohol"]["nightsWithout"] == 3
    assert "sport" not in obs  # aucune séance : pas de conclusion

    # Sous 3 nuits par groupe, pas d'observation.
    assert client.get("/sleep/stats?days=3", headers=h).json()["observations"] == []
