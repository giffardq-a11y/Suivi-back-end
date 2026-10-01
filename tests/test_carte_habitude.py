"""Carte d'habitude de l'Accueil (bande des 7 jours, série, semaine du plan)
et compteur du jour sur le bouton « +1 » alcool/tabac."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.habit_progress import bande_semaine, semaine_du_plan, serie_jours, serie_semaines

# Jeudi 1er octobre 2026, midi.
MAINTENANT = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
LUNDI = date(2026, 9, 28)


def _habit(**kw):
    base = dict(days_of_week=None, tracking_mode="sessions", weekly_target=7, weekly_volume_target=None,
                session_quantity=None, progressive_weeks=None, progressive_start_date=None)
    return SimpleNamespace(**{**base, **kw})


def _log(d: date, quantity=None):
    return SimpleNamespace(occurred_at=datetime(d.year, d.month, d.day, 9), quantity=quantity)


def test_bande_quotidienne():
    faits = {LUNDI, LUNDI + timedelta(days=2)}
    assert bande_semaine(_habit(), faits, MAINTENANT, hebdo=False) == [
        "done", "missed", "done", "today", "todo", "todo", "todo"]


def test_bande_jours_choisis_et_hebdo():
    # Mardi et jeudi seulement : lundi/mercredi sont « off », pas ratés.
    h = _habit(days_of_week="1,3")
    assert bande_semaine(h, set(), MAINTENANT, hebdo=False) == [
        "off", "missed", "off", "today", "off", "off", "off"]
    # Habitude 3 fois/semaine : un jour passé sans séance n'est pas « raté ».
    assert bande_semaine(_habit(weekly_target=3), set(), MAINTENANT, hebdo=True)[:3] == ["todo"] * 3


def test_serie_jours():
    h = _habit()
    faits = {MAINTENANT.date() - timedelta(days=i) for i in range(1, 6)}
    # Aujourd'hui pas encore fait : la série d'hier tient toujours.
    assert serie_jours(h, faits, MAINTENANT) == 5
    assert serie_jours(h, faits | {MAINTENANT.date()}, MAINTENANT) == 6
    # Un trou casse la série.
    assert serie_jours(h, {MAINTENANT.date(), MAINTENANT.date() - timedelta(days=2)}, MAINTENANT) == 1


def test_serie_jours_saute_les_jours_non_prevus():
    h = _habit(days_of_week="1,3")  # mardi, jeudi
    faits = {date(2026, 9, 22), date(2026, 9, 24), date(2026, 9, 29)}  # mar, jeu, mar
    assert serie_jours(h, faits, MAINTENANT) == 3


def test_serie_semaines():
    h = _habit(weekly_target=2)
    logs = [_log(LUNDI - timedelta(days=7)), _log(LUNDI - timedelta(days=5)),
            _log(LUNDI - timedelta(days=14)), _log(LUNDI - timedelta(days=13)),
            _log(LUNDI)]  # semaine en cours pas encore atteinte : ne casse rien
    assert serie_semaines(logs, h, MAINTENANT) == 2
    logs.append(_log(LUNDI + timedelta(days=1)))
    assert serie_semaines(logs, h, MAINTENANT) == 3


def test_serie_semaines_volume():
    h = _habit(tracking_mode="volume", weekly_volume_target=10, session_quantity=4)
    logs = [_log(LUNDI - timedelta(days=7), 6), _log(LUNDI - timedelta(days=6))]  # 6 + 4 = 10
    assert serie_semaines(logs, h, MAINTENANT) == 1


def test_semaine_du_plan():
    assert semaine_du_plan(_habit(), MAINTENANT) == (None, None)
    debut = MAINTENANT - timedelta(days=17)
    assert semaine_du_plan(_habit(progressive_weeks=15, progressive_start_date=debut), MAINTENANT) == (3, 15)
    tres_vieux = MAINTENANT - timedelta(days=400)
    assert semaine_du_plan(_habit(progressive_weeks=15, progressive_start_date=tres_vieux), MAINTENANT) == (15, 15)


def test_dashboard_expose_carte_et_compteur(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    r = client.post("/habits", json={"label": "Méditer", "weekly_target": 7}, headers=h)
    assert r.status_code == 201, r.text
    habit_id = r.json()["id"]
    assert client.post(f"/habits/{habit_id}/log", json={}, headers=h).status_code == 201

    tabac = next(s for s in client.get("/substances", headers=h).json() if s["category"] == "tobacco")
    for qte in (1, 2):
        r = client.post("/entries", json={"substance_id": tabac["id"], "type": "consumption", "quantity": qte}, headers=h)
        assert r.status_code == 201, r.text

    d = client.get("/me/dashboard", headers=h).json()
    carte = next(x for x in d["habits_today"] if x["id"] == habit_id)
    assert carte["streak"] == 1 and carte["streak_unit"] == "days"
    assert len(carte["week_days"]) == 7 and "done" in carte["week_days"]
    serie_tabac = next(s for s in d["streaks"] if s["category"] == "tobacco")
    assert serie_tabac["today_count"] == 3
