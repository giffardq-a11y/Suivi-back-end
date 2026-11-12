"""GET /health/history : historique des constantes de santé pour l'écran
Santé de l'app (fréquence cardiaque, sommeil avec phases, pas, poids, masse
grasse, composition corporelle)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _jour(il_y_a: int) -> str:
    """Date locale du compte de test, calculée comme le serveur (fuseau par
    défaut des comptes, repli sur UTC sans base de fuseaux)."""
    from app import models
    from app.services.common import fuseau_utilisateur
    compte = SimpleNamespace(timezone=models.User.__table__.c.timezone.default.arg)
    aujourdhui = datetime.now(timezone.utc).astimezone(fuseau_utilisateur(compte)).date()
    return (aujourdhui - timedelta(days=il_y_a)).isoformat()


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _importer(client, h):
    """Dix jours de montre, une pesée récente et une pesée ancienne."""
    corps = {
        "heartRate": [{"dateKey": _jour(i), "avgBpm": 70 + i, "minBpm": 50, "maxBpm": 130} for i in range(10)],
        "steps": [{"dateKey": _jour(i), "steps": 1000 * (i + 1)} for i in range(10)],
        "sleep": [],
        "weights": [
            {"externalId": "w-ancien", "weightKg": 80.0, "occurredMs": _ms(_maintenant() - timedelta(days=20))},
            {"externalId": "w-recent", "weightKg": 78.5, "occurredMs": _ms(_maintenant() - timedelta(days=2))},
        ],
        "bodyFat": [{"externalId": "bf", "percent": 19.5, "occurredMs": _ms(_maintenant() - timedelta(days=20))}],
        "composition": [{"externalId": "c", "occurredMs": _ms(_maintenant() - timedelta(days=20)),
                         "leanMassKg": 62.1, "boneMassKg": 3.2, "bmrKcal": 1720}],
    }
    # Réveils il y a 1 à 9 jours, à l'heure qu'il est : sur 7 jours, les
    # 6 premiers sont toujours dans la période (elle commence à minuit, il y
    # a 6 jours), celui d'il y a 7 jours jamais.
    for i in range(1, 10):
        fin = _maintenant() - timedelta(days=i)
        corps["sleep"].append({"externalId": f"n{i}", "startMs": _ms(fin - timedelta(hours=7)), "endMs": _ms(fin),
                               "awakeMin": 20, "lightMin": 220, "deepMin": 80, "remMin": 100})
    r = client.post("/health/import", json=corps, headers=h)
    assert r.status_code == 201, r.text


def test_compte_vide(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.get("/health/history", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["days"] == 30
    for serie in ("heartRate", "sleep", "steps", "weight", "bodyFat", "composition"):
        assert corps[serie] == [], serie
    assert all(v is None for v in corps["latest"].values())


def test_series_importees_sur_la_periode(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    _importer(client, h)

    corps = client.get("/health/history?days=7", headers=h).json()
    # 7 jours = aujourd'hui et les 6 précédents, triés du plus ancien au plus récent.
    assert [f["dateKey"] for f in corps["heartRate"]] == [_jour(i) for i in range(6, -1, -1)]
    assert corps["heartRate"][-1] == {"dateKey": _jour(0), "restingBpm": None, "avgBpm": 70,
                                      "minBpm": 50, "maxBpm": 130}
    assert [p["steps"] for p in corps["steps"]] == [7000, 6000, 5000, 4000, 3000, 2000, 1000]
    assert corps["fromDateKey"] == _jour(6)
    # Nuits : même format que GET /sleep, avec les phases.
    assert len(corps["sleep"]) == 6
    assert corps["sleep"][0]["stages"] == {"awakeMin": 20, "lightMin": 220, "deepMin": 80, "remMin": 100}
    assert corps["sleep"][0]["dateKey"] < corps["sleep"][-1]["dateKey"]

    # Seule la pesée récente est dans la période ; la masse grasse et la
    # composition (il y a 20 j) n'y sont pas, mais restent dans `latest`.
    assert [w["weightKg"] for w in corps["weight"]] == [78.5]
    assert corps["bodyFat"] == [] and corps["composition"] == []
    latest = corps["latest"]
    assert latest["weightKg"]["value"] == 78.5
    assert latest["bodyFatPercent"]["value"] == 19.5
    assert (latest["leanMassKg"]["value"], latest["boneMassKg"]["value"], latest["bmrKcal"]["value"]) == (62.1, 3.2, 1720)

    corps30 = client.get("/health/history?days=30", headers=h).json()
    assert len(corps30["heartRate"]) == 10
    assert [w["weightKg"] for w in corps30["weight"]] == [80.0, 78.5]
    assert corps30["composition"][0]["leanMassKg"] == 62.1


def test_nuit_saisie_et_importee_comptee_une_fois(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    fin = _maintenant() - timedelta(hours=3)
    debut = fin - timedelta(hours=8)
    client.post("/sleep", json={"startMs": _ms(debut), "endMs": _ms(fin)}, headers=h)
    client.post("/health/import", json={"sleep": [{"externalId": "x", "startMs": _ms(debut), "endMs": _ms(fin),
                                                   "awakeMin": 10, "lightMin": 300, "deepMin": 90, "remMin": 80}]},
                headers=h)
    nuits = client.get("/health/history?days=7", headers=h).json()["sleep"]
    assert len(nuits) == 1
    assert nuits[0]["source"] == "health_connect"
    assert nuits[0]["stages"]["deepMin"] == 90


def test_sieste_ne_remplace_pas_la_nuit(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    # Nuit puis sieste importées, réveils le même jour (UTC) : même dateKey.
    reveil = _maintenant().replace(hour=6, minute=0, second=0, microsecond=0)
    if reveil > _maintenant() - timedelta(hours=1):
        reveil -= timedelta(days=1)
    sieste_fin = reveil + timedelta(minutes=40)
    nuits = [
        {"externalId": "nuit", "startMs": _ms(reveil - timedelta(hours=8)), "endMs": _ms(reveil),
         "deepMin": 90, "lightMin": 250, "remMin": 100, "awakeMin": 40},
        {"externalId": "sieste", "startMs": _ms(sieste_fin - timedelta(minutes=25)), "endMs": _ms(sieste_fin)},
    ]
    client.post("/health/import", json={"sleep": nuits}, headers=h)
    du_jour = [n for n in client.get("/health/history?days=7", headers=h).json()["sleep"]
               if n["dateKey"] == reveil.strftime("%Y-%m-%d")]
    assert len(du_jour) == 1 and du_jour[0]["durationMin"] == 480


def test_cloisonnement_entre_comptes(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    _importer(client, h_a)
    corps = client.get("/health/history", headers=h_b).json()
    assert corps["heartRate"] == [] and corps["steps"] == [] and corps["sleep"] == []
    assert corps["latest"]["weightKg"] is None


def test_periode_invalide_et_authentification(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    for jours in (0, 367, "abc"):
        assert client.get(f"/health/history?days={jours}", headers=h).status_code == 422, jours
    assert client.get("/health/history").status_code in (401, 403)
