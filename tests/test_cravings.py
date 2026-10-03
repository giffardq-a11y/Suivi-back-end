"""Sessions d'aide au craving (/craving-sessions, table cravings) et raison
« Pourquoi je réduis » (substances.reason).

Démarrage, fin résisté / cédé (avec création et liaison de l'entrée de
consommation par le service de POST /entries), transitions, validations,
isolement entre comptes, liste, statistiques calculées à la lecture,
suggestion (raison + résistés sur 7 jours)."""
from datetime import datetime, timedelta, timezone

from app import models
from app.database import SessionLocal


def _tabac(client, h):
    return next(s for s in client.get("/substances", headers=h).json() if s["category"] == "tobacco")


def _demarrer(client, h, substance_id, **extra):
    corps = {"substance_id": substance_id, "intensity_start": 7, **extra}
    r = client.post("/craving-sessions", headers=h, json=corps)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- Démarrage et fin ----------

def test_demarrage(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    c = _demarrer(client, h, tabac["id"], trigger="  Café ")
    assert c["outcome"] == "en_cours"
    assert c["planned_seconds"] == 600
    assert c["intensity_start"] == 7 and c["intensity_end"] is None
    assert c["trigger"] == "café"  # trim + minuscules
    assert c["ended_at"] is None and c["duration_seconds"] is None and c["entry_id"] is None

    c2 = _demarrer(client, h, tabac["id"], planned_seconds=300)
    assert c2["planned_seconds"] == 300 and c2["trigger"] is None


def test_fin_resiste(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    c = _demarrer(client, h, tabac["id"])
    r = client.put(f"/craving-sessions/{c['id']}", headers=h,
                   json={"outcome": "resiste", "intensity_end": 3, "note": " Marché dehors "})
    assert r.status_code == 200, r.text
    fin = r.json()
    assert fin["outcome"] == "resiste" and fin["intensity_end"] == 3 and fin["note"] == "Marché dehors"
    assert fin["ended_at"] is not None and fin["duration_seconds"] >= 0
    assert fin["entry_id"] is None
    # Aucune consommation créée.
    assert client.get("/entries", headers=h).json() == []


def test_fin_cede_avec_log_entry_cree_et_lie_l_entree(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    client.put(f"/substances/{tabac['id']}", headers=h, json={"unit_cost": 0.5})
    c = _demarrer(client, h, tabac["id"])
    r = client.put(f"/craving-sessions/{c['id']}", headers=h,
                   json={"outcome": "cede", "log_entry": True, "quantity": 2})
    assert r.status_code == 200, r.text
    fin = r.json()
    assert fin["outcome"] == "cede" and fin["entry_id"]

    entrees = client.get("/entries", headers=h).json()
    assert len(entrees) == 1
    e = entrees[0]
    assert e["id"] == fin["entry_id"]
    assert e["substance_id"] == tabac["id"] and e["type"] == "consumption"
    assert e["quantity"] == 2 and e["price"] == 1.0  # même règle de prix que POST /entries

    # Rejouer la fin ne crée pas de doublon.
    r = client.put(f"/craving-sessions/{c['id']}", headers=h, json={"outcome": "cede", "log_entry": True})
    assert r.status_code == 200 and r.json()["entry_id"] == fin["entry_id"]
    assert len(client.get("/entries", headers=h).json()) == 1


def test_fin_cede_sans_log_entry_ne_cree_rien(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    c = _demarrer(client, h, _tabac(client, h)["id"])
    r = client.put(f"/craving-sessions/{c['id']}", headers=h, json={"outcome": "cede"})
    assert r.status_code == 200 and r.json()["entry_id"] is None
    assert client.get("/entries", headers=h).json() == []


def test_transitions(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    c = _demarrer(client, h, _tabac(client, h)["id"])
    url = f"/craving-sessions/{c['id']}"
    # Mise à jour sans issue : reste en cours.
    r = client.put(url, headers=h, json={"trigger": "ennui"})
    assert r.status_code == 200 and r.json()["outcome"] == "en_cours" and r.json()["trigger"] == "ennui"
    # log_entry sans 'cede' : 422.
    assert client.put(url, headers=h, json={"outcome": "resiste", "log_entry": True}).status_code == 422
    assert client.put(url, headers=h, json={"outcome": "abandonne"}).status_code == 200
    # Terminée : l'issue ne change plus, ni vers une autre issue ni vers en_cours.
    assert client.put(url, headers=h, json={"outcome": "resiste"}).status_code == 409
    assert client.put(url, headers=h, json={"outcome": "en_cours"}).status_code == 409
    # La note reste modifiable, et la même issue est acceptée.
    r = client.put(url, headers=h, json={"outcome": "abandonne", "note": "appel reçu"})
    assert r.status_code == 200 and r.json()["note"] == "appel reçu"


# ---------- Validations ----------

def test_validations_422(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    sid = _tabac(client, h)["id"]
    for corps in ({"substance_id": sid, "intensity_start": 0},
                  {"substance_id": sid, "intensity_start": 11},
                  {"substance_id": sid},
                  {"substance_id": sid, "intensity_start": 5, "planned_seconds": 0},
                  {"substance_id": sid, "intensity_start": 5, "trigger": "x" * 41}):
        r = client.post("/craving-sessions", headers=h, json=corps)
        assert r.status_code == 422, (corps, r.text)

    c = _demarrer(client, h, sid)
    url = f"/craving-sessions/{c['id']}"
    for corps in ({"outcome": "gagne"},
                  {"outcome": "resiste", "intensity_end": 0},
                  {"outcome": "resiste", "intensity_end": 11},
                  {"outcome": "cede", "log_entry": True, "quantity": 0},
                  {"outcome": "cede", "log_entry": True, "quantity": 1.5}):
        r = client.put(url, headers=h, json=corps)
        assert r.status_code == 422, (corps, r.text)
    # Rien n'a bougé.
    assert client.get("/craving-sessions", headers=h).json()[0]["outcome"] == "en_cours"


def test_substance_inconnue_404(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.post("/craving-sessions", headers=h, json={"substance_id": "nope", "intensity_start": 5})
    assert r.status_code == 404
    assert client.put("/craving-sessions/nope", headers=h, json={"outcome": "resiste"}).status_code == 404


# ---------- Isolement ----------

def test_isolement_entre_utilisateurs(client, nouveau_compte):
    _, _, h1, _ = nouveau_compte()
    _, _, h2, _ = nouveau_compte()
    tabac1 = _tabac(client, h1)
    c = _demarrer(client, h1, tabac1["id"])

    # B ne voit ni ne modifie la session de A, ni ne démarre sur sa substance.
    assert client.put(f"/craving-sessions/{c['id']}", headers=h2, json={"outcome": "cede"}).status_code == 404
    assert client.get("/craving-sessions", headers=h2).json() == []
    assert client.post("/craving-sessions", headers=h2,
                       json={"substance_id": tabac1["id"], "intensity_start": 5}).status_code == 404
    assert client.get(f"/craving-sessions?substance_id={tabac1['id']}", headers=h2).status_code == 404
    assert client.get(f"/craving-sessions/stats?substance_id={tabac1['id']}", headers=h2).status_code == 404
    assert client.get(f"/craving-sessions/suggestion?substance_id={tabac1['id']}", headers=h2).status_code == 404
    assert client.get("/craving-sessions/stats", headers=h2).json()["total"] == 0

    # Chez A, rien n'a changé.
    assert client.get("/craving-sessions", headers=h1).json()[0]["outcome"] == "en_cours"


# ---------- Liste ----------

def test_liste_recents_d_abord_filtres_et_limite(client, nouveau_compte):
    _, _, h, uid = nouveau_compte()
    tabac = _tabac(client, h)
    alcool = next(s for s in client.get("/substances", headers=h).json() if s["category"] == "alcohol")
    maintenant = datetime.now(timezone.utc)
    db = SessionLocal()
    for jours, sid in ((1, tabac["id"]), (3, tabac["id"]), (40, tabac["id"]), (2, alcool["id"])):
        db.add(models.Craving(user_id=uid, substance_id=sid, started_at=maintenant - timedelta(days=jours),
                              planned_seconds=600, intensity_start=5, outcome="resiste"))
    db.commit()
    db.close()

    tout = client.get("/craving-sessions", headers=h).json()
    assert len(tout) == 4
    debuts = [c["started_at"] for c in tout]
    assert debuts == sorted(debuts, reverse=True)

    assert len(client.get(f"/craving-sessions?substance_id={tabac['id']}", headers=h).json()) == 3
    assert len(client.get(f"/craving-sessions?substance_id={tabac['id']}&days=30", headers=h).json()) == 2
    page = client.get("/craving-sessions?limit=2", headers=h).json()
    assert [c["id"] for c in page] == [c["id"] for c in tout[:2]]
    page2 = client.get("/craving-sessions?limit=2&offset=2", headers=h).json()
    assert [c["id"] for c in page2] == [c["id"] for c in tout[2:]]
    assert client.get("/craving-sessions?limit=0", headers=h).status_code == 422


# ---------- Statistiques ----------

def test_stats_sur_jeu_de_donnees(client, nouveau_compte):
    _, _, h, uid = nouveau_compte()
    tabac = _tabac(client, h)
    alcool = next(s for s in client.get("/substances", headers=h).json() if s["category"] == "alcohol")

    db = SessionLocal()
    db.query(models.User).filter(models.User.id == uid).one().timezone = "UTC"
    # Lundi récent à 08 h UTC, pour des cases heure/jour prévisibles.
    aujourd_hui = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday() + 7)
    jeu = [
        # (début, durée s, issue, intensité début, fin, déclencheur, substance)
        (lundi, 600, "resiste", 8, 3, "stress", tabac["id"]),
        (lundi + timedelta(hours=1), 300, "resiste", 6, 2, "stress", tabac["id"]),
        (lundi + timedelta(days=2, hours=12), 900, "cede", 9, None, "café", tabac["id"]),
        (lundi + timedelta(days=2, hours=12, minutes=30), 120, "abandonne", 4, 4, None, tabac["id"]),
        (lundi + timedelta(days=3), None, "en_cours", 5, None, "ennui", tabac["id"]),
        # Hors fenêtre de 30 jours : ignorée.
        (lundi - timedelta(days=60), 600, "cede", 10, None, "stress", tabac["id"]),
        # Autre substance : comptée seulement sans filtre.
        (lundi, 600, "resiste", 2, 1, "social", alcool["id"]),
    ]
    for debut, duree, issue, i_debut, i_fin, decl, sid in jeu:
        db.add(models.Craving(
            user_id=uid, substance_id=sid, started_at=debut,
            ended_at=debut + timedelta(seconds=duree) if duree is not None else None,
            planned_seconds=600, intensity_start=i_debut, intensity_end=i_fin,
            trigger_label=decl, outcome=issue))
    db.commit()
    db.close()

    r = client.get(f"/craving-sessions/stats?substance_id={tabac['id']}", headers=h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["jours"] == 30 and s["substance_id"] == tabac["id"]
    assert (s["total"], s["resistes"], s["cedes"], s["abandonnes"], s["en_cours"]) == (5, 2, 1, 1, 1)
    assert s["taux_resistance"] == round(2 / 3, 3)
    assert s["intensite_moyenne_debut"] == round((8 + 6 + 9 + 4 + 5) / 5, 2)
    assert s["intensite_moyenne_fin"] == 3.0          # (3 + 2 + 4) / 3
    assert s["duree_moyenne_secondes"] == 480.0       # (600 + 300 + 900 + 120) / 4, en cours exclue
    assert s["top_declencheurs"] == [{"nom": "stress", "nombre": 2}, {"nom": "café", "nombre": 1},
                                     {"nom": "ennui", "nombre": 1}]
    assert len(s["par_heure"]) == 24 and len(s["par_jour_semaine"]) == 7
    assert s["par_heure"][8] == 2 and s["par_heure"][9] == 1 and s["par_heure"][20] == 2
    assert s["par_jour_semaine"] == [2, 0, 2, 1, 0, 0, 0]

    tout = client.get("/craving-sessions/stats", headers=h).json()
    assert tout["total"] == 6 and tout["resistes"] == 3 and tout["substance_id"] is None
    assert client.get("/craving-sessions/stats?days=365", headers=h).json()["total"] == 7


def test_stats_vides(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    s = client.get("/craving-sessions/stats", headers=h).json()
    assert s["total"] == 0 and s["taux_resistance"] is None and s["intensite_moyenne_debut"] is None
    assert s["par_heure"] == [0] * 24 and s["top_declencheurs"] == []


# ---------- Raison et suggestion ----------

def test_raison_put_get_post(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    assert tabac["reason"] is None
    r = client.put(f"/substances/{tabac['id']}", headers=h, json={"reason": "  Courir avec ma fille  "})
    assert r.status_code == 200, r.text
    assert _tabac(client, h)["reason"] == "Courir avec ma fille"
    # Un autre champ modifié ne touche pas à la raison.
    client.put(f"/substances/{tabac['id']}", headers=h, json={"unit_cost": 1})
    assert _tabac(client, h)["reason"] == "Courir avec ma fille"
    # Chaîne vide : efface.
    client.put(f"/substances/{tabac['id']}", headers=h, json={"reason": "   "})
    assert _tabac(client, h)["reason"] is None

    r = client.post("/substances", headers=h, json={"label": "Snus", "reason": "Mes dents"})
    assert r.status_code == 201
    cree = next(s for s in client.get("/substances", headers=h).json() if s["id"] == r.json()["id"])
    assert cree["reason"] == "Mes dents"


def test_raison_trop_longue_422(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    assert client.put(f"/substances/{tabac['id']}", headers=h, json={"reason": "x" * 301}).status_code == 422
    assert client.post("/substances", headers=h, json={"label": "Snus", "reason": "x" * 301}).status_code == 422
    # 300 après trim : accepté.
    assert client.put(f"/substances/{tabac['id']}", headers=h,
                      json={"reason": "  " + "x" * 300 + "  "}).status_code == 200


def test_suggestion(client, nouveau_compte):
    _, _, h, uid = nouveau_compte()
    tabac = _tabac(client, h)
    s = client.get(f"/craving-sessions/suggestion?substance_id={tabac['id']}", headers=h).json()
    assert s == {"substance_id": tabac["id"], "raison": None, "derniers_resistes": 0}

    client.put(f"/substances/{tabac['id']}", headers=h, json={"reason": "Respirer mieux"})
    maintenant = datetime.now(timezone.utc)
    db = SessionLocal()
    for jours, issue in ((1, "resiste"), (6, "resiste"), (2, "cede"), (10, "resiste")):
        db.add(models.Craving(user_id=uid, substance_id=tabac["id"], started_at=maintenant - timedelta(days=jours),
                              planned_seconds=600, intensity_start=5, outcome=issue))
    db.commit()
    db.close()
    s = client.get(f"/craving-sessions/suggestion?substance_id={tabac['id']}", headers=h).json()
    assert s["raison"] == "Respirer mieux" and s["derniers_resistes"] == 2

    assert client.get("/craving-sessions/suggestion", headers=h).status_code == 422


# ---------- Suppression ----------

def test_supprimer_la_substance_emporte_ses_sessions(client, nouveau_compte):
    _, _, h, uid = nouveau_compte()
    tabac = _tabac(client, h)
    c = _demarrer(client, h, tabac["id"])
    client.put(f"/craving-sessions/{c['id']}", headers=h, json={"outcome": "cede", "log_entry": True})
    assert client.delete(f"/substances/{tabac['id']}", headers=h).status_code == 204
    assert client.get("/craving-sessions", headers=h).json() == []
    db = SessionLocal()
    assert db.query(models.Craving).filter(models.Craving.user_id == uid).count() == 0
    db.close()
