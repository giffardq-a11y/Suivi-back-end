"""Import Health Connect étendu : balance connectée (poids, masse grasse,
composition), fréquence cardiaque du jour et phases du sommeil.

L'import de base (séances, nuits, pas, poids) est déjà couvert par
test_sleep.py ; on ne vérifie ici que ce qui a été ajouté pour la balance et
la montre."""
from datetime import datetime, timedelta, timezone


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _il_y_a(heures: float) -> int:
    return _ms(datetime.now(timezone.utc) - timedelta(hours=heures))


def _pesee(client, h):
    """Une pesée complète de balance : poids, masse grasse, composition."""
    return {
        "weights": [{"externalId": "w1", "weightKg": 78.4, "occurredMs": _il_y_a(2)}],
        "bodyFat": [{"externalId": "bf1", "percent": 19.5, "occurredMs": _il_y_a(2)}],
        "composition": [{"externalId": "c1", "occurredMs": _il_y_a(2),
                         "leanMassKg": 62.1, "boneMassKg": 3.2, "bmrKcal": 1720}],
    }


def test_balance_importe_poids_masse_grasse_et_composition(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.post("/health/import", json=_pesee(client, h), headers=h)
    assert r.status_code == 201, r.text
    corps = r.json()
    assert (corps["pesees"], corps["masse_grasse"], corps["compositions"]) == (1, 1, 1)

    # La masse grasse importée rejoint l'historique existant de l'app.
    graisse = client.get("/body-fat", headers=h).json()
    assert graisse["current_percent"] == 19.5
    assert graisse["entries"][0]["note"] == "Importé de la balance"

    resume = client.get("/health/summary", headers=h).json()
    assert resume["derniere_pesee_kg"] == 78.4
    assert resume["masse_grasse_pct"] == 19.5
    assert resume["masse_maigre_kg"] == 62.1
    assert resume["imc"] is None  # taille inconnue : pas d'IMC inventé


def test_balance_resynchronisation_sans_doublon(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    montre = _pesee(client, h)
    client.post("/health/import", json=montre, headers=h)
    r = client.post("/health/import", json=montre, headers=h).json()
    assert (r["pesees"], r["masse_grasse"], r["compositions"]) == (0, 0, 0)
    assert len(client.get("/body-fat", headers=h).json()["entries"]) == 1
    assert len(client.get("/weight", headers=h).json()["entries"]) == 1


def test_imc_calcule_avec_la_taille_du_profil(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    assert client.put("/profile", json={"heightCm": 180}, headers=h).status_code == 200
    client.post("/health/import", json=_pesee(client, h), headers=h)
    # 78,4 / 1,8² = 24,2
    assert client.get("/health/summary", headers=h).json()["imc"] == 24.2


def test_composition_vide_ignoree_et_valeurs_invalides_refusees(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    vide = {"composition": [{"externalId": "c0", "occurredMs": _il_y_a(1)}]}
    assert client.post("/health/import", json=vide, headers=h).json()["compositions"] == 0

    for corps in (
        {"bodyFat": [{"externalId": "x", "percent": 0, "occurredMs": _il_y_a(1)}]},
        {"bodyFat": [{"externalId": "x", "percent": 120, "occurredMs": _il_y_a(1)}]},
        {"composition": [{"externalId": "x", "occurredMs": _il_y_a(1), "leanMassKg": -3}]},
        {"heartRate": [{"dateKey": "hier", "restingBpm": 60}]},
        {"heartRate": [{"dateKey": "2026-11-10", "restingBpm": 900}]},
    ):
        assert client.post("/health/import", json=corps, headers=h).status_code == 422, corps


def test_frequence_cardiaque_du_jour(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    jour = {"dateKey": "2026-11-10", "restingBpm": 58, "avgBpm": 72, "minBpm": 50, "maxBpm": 140}
    r = client.post("/health/import", json={"heartRate": [jour]}, headers=h).json()
    assert r["jours_fc"] == 1
    assert client.get("/health/summary", headers=h).json()["fc_repos_bpm"] == 58

    # Nouvelle synchro du même jour, sans mesure de repos : on met à jour la
    # moyenne et le maximum, sans effacer le repos déjà connu, et sans doublon.
    client.post("/health/import", json={"heartRate": [{"dateKey": "2026-11-10", "avgBpm": 75, "maxBpm": 150}]},
                headers=h)
    from app.database import SessionLocal
    from app import models
    db = SessionLocal()
    try:
        lignes = db.query(models.DailyHeartRate).filter(models.DailyHeartRate.date_key == "2026-11-10").all()
        mine = [l for l in lignes if l.avg_bpm == 75]
        assert len(mine) == 1
        assert (mine[0].resting_bpm, mine[0].min_bpm, mine[0].max_bpm) == (58, 50, 150)
    finally:
        db.close()


def test_phases_du_sommeil(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    debut = datetime.now(timezone.utc) - timedelta(hours=16)  # nuit terminée, jamais dans le futur
    nuit = {"externalId": "n1", "startMs": _ms(debut), "endMs": _ms(debut + timedelta(hours=8)),
            "awakeMin": 30, "lightMin": 250, "deepMin": 90, "remMin": 110}
    assert client.post("/health/import", json={"sleep": [nuit]}, headers=h).json()["nuits"] == 1

    # Une nuit saisie à la main n'a pas de phases.
    client.post("/sleep", json={"startMs": _ms(debut - timedelta(days=2)),
                                "endMs": _ms(debut - timedelta(days=2) + timedelta(hours=7))}, headers=h)

    nuits = client.get("/sleep", headers=h).json()["nights"]
    importee = next(n for n in nuits if n["source"] == "health_connect")
    manuelle = next(n for n in nuits if n["source"] == "manual")
    assert importee["stages"] == {"awakeMin": 30, "lightMin": 250, "deepMin": 90, "remMin": 110}
    assert manuelle["stages"] is None

    resume = client.get("/health/summary", headers=h).json()
    assert resume["derniere_nuit_phases"]["profond"] == 90

    # La montre corrige ses phases après coup : mise à jour, pas de doublon.
    nuit["deepMin"] = 100
    assert client.post("/health/import", json={"sleep": [nuit]}, headers=h).json()["nuits"] == 0
    nuits = client.get("/sleep", headers=h).json()["nights"]
    assert next(n for n in nuits if n["source"] == "health_connect")["stages"]["deepMin"] == 100


def test_import_sans_phases_reste_valide(client, nouveau_compte):
    """Anciennes versions de l'app : sommeil sans phases, aucun nouveau champ."""
    _, _, h, _ = nouveau_compte()
    debut = datetime.now(timezone.utc) - timedelta(hours=10)
    nuit = {"externalId": "ancienne", "startMs": _ms(debut), "endMs": _ms(debut + timedelta(hours=7))}
    assert client.post("/health/import", json={"sleep": [nuit]}, headers=h).status_code == 201
    assert client.get("/health/summary", headers=h).json()["derniere_nuit_phases"] is None


def test_cloisonnement_des_mesures(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    client.post("/health/import", json=_pesee(client, h_a), headers=h_a)
    resume_b = client.get("/health/summary", headers=h_b).json()
    assert resume_b["masse_grasse_pct"] is None and resume_b["derniere_pesee_kg"] is None
    assert client.get("/body-fat", headers=h_b).json()["entries"] == []
