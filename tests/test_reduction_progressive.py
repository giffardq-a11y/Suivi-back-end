"""Réduction progressive tabac/alcool : limite du jour = max(0, départ − pas ×
semaines complètes écoulées), recalculée à chaque lecture (services/
substance_progress.py), exposée par GET /substances et réglée par
PUT /substances/{id}."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.substance_progress import limite_du_jour, palier_courant, paliers_total


def _sub(depart=10.0, pas=1.0, debut=date(2026, 9, 1)):
    return SimpleNamespace(reduction_start_value=depart, reduction_step_per_week=pas,
                           reduction_start_date=debut)


# ---------- Service ----------

def test_cas_nominal_trois_semaines():
    s = _sub()
    jour = date(2026, 9, 1) + timedelta(days=3 * 7 + 2)  # 3 semaines complètes
    assert limite_du_jour(s, jour) == 7
    assert palier_courant(s, jour) == 4
    assert paliers_total(s) == 10


def test_semaine_zero():
    s = _sub()
    for jour in (date(2026, 9, 1), date(2026, 9, 7)):  # jour 0 et jour 6
        assert limite_du_jour(s, jour) == 10
        assert palier_courant(s, jour) == 1
    # Une date de départ dans le futur ne fait pas remonter la limite.
    assert limite_du_jour(s, date(2026, 8, 20)) == 10


def test_plancher_a_zero_et_palier_borne():
    s = _sub(depart=5, pas=2)  # 5, 3, 1, 0 → ceil(5/2) = 3 paliers
    assert paliers_total(s) == 3
    loin = date(2026, 9, 1) + timedelta(weeks=20)
    assert limite_du_jour(s, loin) == 0
    assert palier_courant(s, loin) == 3


def test_sans_reduction():
    s = SimpleNamespace(reduction_start_value=None, reduction_step_per_week=None, reduction_start_date=None)
    assert limite_du_jour(s, date(2026, 9, 1)) is None
    assert palier_courant(s, date(2026, 9, 1)) is None
    assert paliers_total(s) is None


# ---------- API ----------

def _tabac(client, h):
    return next(s for s in client.get("/substances", headers=h).json() if s["category"] == "tobacco")


def test_get_sans_reduction_par_defaut(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    for champ in ("reduction_start_value", "reduction_step_per_week", "reduction_start_date",
                  "limite_du_jour", "palier_courant", "paliers_total"):
        assert tabac[champ] is None


def test_put_puis_get(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    debut = (datetime.now(timezone.utc).date() - timedelta(days=15)).isoformat()  # 2 semaines complètes
    r = client.put(f"/substances/{tabac['id']}", headers=h, json={
        "reduction_start_value": 10, "reduction_step_per_week": 1, "reduction_start_date": debut})
    assert r.status_code == 200, r.text
    maj = _tabac(client, h)
    assert maj["reduction_start_value"] == 10 and maj["reduction_step_per_week"] == 1
    assert maj["reduction_start_date"] == debut
    assert maj["limite_du_jour"] == 8
    assert (maj["palier_courant"], maj["paliers_total"]) == (3, 10)


def test_put_sans_date_part_d_aujourd_hui_et_retrait(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    r = client.put(f"/substances/{tabac['id']}", headers=h,
                   json={"reduction_start_value": 6, "reduction_step_per_week": 2})
    assert r.status_code == 200, r.text
    maj = _tabac(client, h)
    assert maj["reduction_start_date"] is not None
    assert maj["limite_du_jour"] == 6 and maj["palier_courant"] == 1 and maj["paliers_total"] == 3

    # Retirer la réduction : les deux valeurs à null, la date part avec.
    r = client.put(f"/substances/{tabac['id']}", headers=h,
                   json={"reduction_start_value": None, "reduction_step_per_week": None})
    assert r.status_code == 200, r.text
    maj = _tabac(client, h)
    assert maj["reduction_start_date"] is None and maj["limite_du_jour"] is None


def test_put_refuse_valeurs_invalides(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tabac = _tabac(client, h)
    for corps in ({"reduction_start_value": 0, "reduction_step_per_week": 1},
                  {"reduction_start_value": 10, "reduction_step_per_week": -1},
                  {"reduction_start_value": 10}):  # pas sans l'autre
        r = client.put(f"/substances/{tabac['id']}", headers=h, json=corps)
        assert r.status_code == 422, (corps, r.text)
    assert _tabac(client, h)["reduction_start_value"] is None


def test_post_avec_reduction(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.post("/substances", headers=h, json={
        "label": "Snus", "reduction_start_value": 4, "reduction_step_per_week": 1})
    assert r.status_code == 201, r.text
    cree = next(s for s in client.get("/substances", headers=h).json() if s["id"] == r.json()["id"])
    assert cree["limite_du_jour"] == 4 and cree["paliers_total"] == 4
