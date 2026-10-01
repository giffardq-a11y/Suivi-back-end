"""Habitudes à perdre : journaliser une occurrence."""


def test_log_occurrence(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    mauvaise = client.post("/bad-habits", headers=h, json={"label": "Grignoter"}).json()
    r = client.post(f"/bad-habits/{mauvaise['id']}/log", headers=h, json={"note": "soir"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_log_occurrence_introuvable_404(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.post("/bad-habits/inexistant/log", headers=h, json={})
    assert r.status_code == 404


def test_log_occurrence_autre_compte_404(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()
    mauvaise = client.post("/bad-habits", headers=h_a, json={"label": "Grignoter"}).json()
    r = client.post(f"/bad-habits/{mauvaise['id']}/log", headers=h_b, json={})
    assert r.status_code == 404
