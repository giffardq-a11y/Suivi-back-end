"""Module Personnage : moteur de stats (services/stats.py), branchements dans
les routes existantes, endpoints /character.

Les dates sont posées explicitement (date_key, now) partout où un plafond
journalier ou un palier de santé est en jeu : le test ne dépend pas de
l'heure à laquelle il tourne.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import models
from app.database import SessionLocal
from app.services import stats


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def joueur(nouveau_compte, db):
    """Fabrique : compte + personnage créé directement en base (sans passer
    par POST /character, donc sans rattrapage). Renvoie (user, en-têtes)."""
    def creer(class_key="combattant", personnage=True):
        _, _, h, uid = nouveau_compte()
        user = db.query(models.User).filter(models.User.id == uid).one()
        if personnage:
            db.add(models.Character(user_id=uid, universe="anime", class_key=class_key, name="Test"))
            db.commit()
        return user, h
    return creer


def _perso(db, user):
    db.expire_all()
    return db.query(models.Character).filter(models.Character.user_id == user.id).one()


def _evenements(db, user, source=None):
    q = db.query(models.StatEvent).filter(models.StatEvent.user_id == user.id)
    if source:
        q = q.filter(models.StatEvent.source == source)
    return q.all()


JOUR = "2026-09-01"


# ---------- Moteur ----------

def test_sans_personnage_rien_n_est_attribue(joueur, db):
    user, _ = joueur(personnage=False)
    assert stats.award(db, user, "habit_done", "x", JOUR) is None
    assert _evenements(db, user) == []


def test_idempotence_par_source_et_id(joueur, db):
    user, _ = joueur()
    premier = stats.award(db, user, "goal_completed", "objectif-1", JOUR)
    assert premier["points_par_stat"] == {"wil": 12.0}      # 10 × 1,2 (Colosse)
    second = stats.award(db, user, "goal_completed", "objectif-1", JOUR)
    assert second["points_par_stat"] == {} and second["xp"] == 0
    assert len(_evenements(db, user)) == 1
    assert _perso(db, user).total_xp == 120


def test_plafonds_journaliers(joueur, db):
    user, _ = joueur("ninja")
    # Hydratation : 1 par jour, un autre jour repart à zéro.
    assert stats.award(db, user, "hydration_goal", "a", JOUR)["points_par_stat"] == {"hp": 1.0}
    assert stats.award(db, user, "hydration_goal", "b", JOUR)["points_par_stat"] == {}
    assert stats.award(db, user, "hydration_goal", "c", "2026-09-02")["points_par_stat"] == {"hp": 1.0}
    # Course : +1 par km entier, 15 par jour, même réparti sur plusieurs courses.
    r1 = stats.award(db, user, "run", "r1", JOUR, {"distanceKm": 12.7})
    assert r1["points_par_stat"] == {"end": 18.0}          # 12 × 1,5 (Éclaireur)
    r2 = stats.award(db, user, "run", "r2", JOUR, {"distanceKm": 10})
    assert _evenements(db, user, "run")[1].base_points == 3  # 15 - 12
    assert r2["points_par_stat"] == {"end": 4.5}
    assert stats.award(db, user, "run", "r3", JOUR, {"distanceKm": 5})["points_par_stat"] == {}
    # Volume : plafond par séance, pas par jour.
    v = stats.award(db, user, "strength_volume", "s1", JOUR, {"volumeKg": 9400})
    assert _evenements(db, user, "strength_volume")[0].base_points == 5


def test_plafond_hebdomadaire(joueur, db):
    user, _ = joueur()
    assert stats.award(db, user, "weight_progress", "p1", "2026-09-07")["points_par_stat"]  # lundi
    assert stats.award(db, user, "weight_progress", "p2", "2026-09-13")["points_par_stat"] == {}  # dimanche
    assert stats.award(db, user, "weight_progress", "p3", "2026-09-14")["points_par_stat"]  # lundi suivant


def test_coefficients_de_classe(joueur, db):
    colosse, _ = joueur("combattant")
    stratege, _ = joueur("stratege")
    assert stats.award(db, colosse, "strength_session", "s", JOUR)["points_par_stat"] == {"str": 3.0}
    assert stats.award(db, stratege, "strength_session", "s", JOUR)["points_par_stat"] == {"str": 1.4}
    assert stats.award(db, stratege, "cards_reviewed", "c", JOUR)["points_par_stat"] == {"int": 1.5}


def test_capacites_passives(joueur, db):
    colosse, _ = joueur("combattant")
    moine, _ = joueur("moine")
    ninja, _ = joueur("ninja")
    # Colosse : record ×2 → 5 × 1,5 × 2.
    assert stats.award(db, colosse, "strength_pr", "pr", JOUR)["points_par_stat"] == {"str": 15.0}
    assert _evenements(db, colosse, "strength_pr")[0].bonus_pct == 100
    # Mystique : envie résistée +50 % → 3 × 1,5 × 1,5.
    assert stats.award(db, moine, "craving_resisted", "e", JOUR)["points_par_stat"] == {"spi": 6.75}
    # Éclaireur : pas ×2 → 1 × 1,5 × 2 ; pas de bonus sur une autre source.
    assert stats.award(db, ninja, "steps_goal", JOUR, JOUR)["points_par_stat"] == {"end": 3.0}
    assert stats.award(db, ninja, "craving_resisted", "e", JOUR)["points_par_stat"] == {"spi": 2.4}


def test_niveaux_rangs_et_eclats(joueur, db):
    assert stats.cout_niveau(1) == 80
    assert stats.cout_niveau(2) == round(80 * 2 ** 1.35)
    assert stats.niveau_pour_xp(79) == (1, 79, 80)
    assert stats.niveau_pour_xp(80)[0] == 2
    assert [stats.rang_pour_niveau(n)["nom"] for n in (1, 9, 10, 25, 50, 80, 120)] == \
        ["Apprenti", "Apprenti", "Initié", "Guerrier", "Maître", "Légende", "Légende"]

    user, _ = joueur("samourai")
    r = stats.award(db, user, "goal_completed", "o1", JOUR)      # 10 × 1,5 = 15 pts = 150 XP
    assert r["xp"] == 150 and r["level_up"] is True and r["level"] == 2 and r["new_rank"] is None
    assert _perso(db, user).shards == 15

    # Juste sous le niveau 10 : le gain suivant fait changer de rang.
    seuil_10 = sum(stats.cout_niveau(n) for n in range(1, 10))
    perso = _perso(db, user)
    perso.total_xp, perso.level = seuil_10 - 1, 9
    db.commit()
    r = stats.award(db, user, "goal_completed", "o2", JOUR)
    assert r["level"] == 10 and r["new_rank"] == {"rank": 2, "name": "Initié"}


def test_retirer_garde_le_niveau_et_ne_se_regagne_pas(joueur, db):
    user, _ = joueur()
    stats.award(db, user, "strength_session", "s1", JOUR)       # 3 pts, 30 XP
    avant = _perso(db, user)
    xp, niveau = avant.total_xp, avant.level
    assert stats.retirer(db, user, "strength_session", "s1") == 1
    apres = _perso(db, user)
    assert _evenements(db, user) == []
    assert (apres.total_xp, apres.level) == (xp, niveau)
    # Ressaisie de la même action : les points reviennent, pas l'XP.
    r = stats.award(db, user, "strength_session", "s1", JOUR)
    assert r["points_par_stat"] == {"str": 3.0} and r["xp"] == 0
    assert _perso(db, user).total_xp == xp
    # Une autre action rapporte normalement.
    assert stats.award(db, user, "strength_session", "s2", JOUR)["xp"] == 30


# ---------- Sobriété ----------

def _tabac(db, user):
    return db.query(models.Substance).filter(
        models.Substance.user_id == user.id, models.Substance.category == models.SubstanceCategory.TOBACCO).one()


def _hp_par_source(db, user, source):
    return sorted(round(e.points, 2) for e in _evenements(db, user, source) if e.stat == "hp")


def test_non_fumeur_ne_gagne_rien(joueur, db):
    user, _ = joueur()
    maintenant = datetime.now(timezone.utc)
    user.created_at = maintenant - timedelta(days=30)
    db.commit()
    # Substances Alcool/Tabac créées d'office, mais ni date d'arrêt ni conso.
    assert stats.constater_sobriete(db, user, now=maintenant) == []
    assert _evenements(db, user) == []


def test_journees_sans_tabac(joueur, db):
    user, _ = joueur()
    maintenant = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)
    user.created_at = datetime(2026, 9, 10, 8, tzinfo=timezone.utc)
    tabac = _tabac(db, user)
    tabac.quit_date = "2026-09-01"        # avant l'inscription : comptée depuis l'inscription
    db.add(models.ConsumptionEntry(user_id=user.id, substance_id=tabac.id,
                                   occurred_at=datetime(2026, 9, 15, 20, tzinfo=timezone.utc)))
    db.commit()
    stats.constater_sobriete(db, user, now=maintenant)
    jours = sorted(e.date_key for e in _evenements(db, user, "tobacco_free_day"))
    # Du 10 au 19 (hier), sauf le 15.
    assert jours == [f"2026-09-{j:02d}" for j in range(10, 20) if j != 15]
    # Relancé : rien de plus.
    stats.constater_sobriete(db, user, now=maintenant)
    assert len(_evenements(db, user, "tobacco_free_day")) == 9


def test_paliers_tabac_rechute_et_reprise_a_50_pourcent(joueur, db):
    user, _ = joueur("combattant")   # hp × 1,1, end × 0,9
    maintenant = datetime.now(timezone.utc)
    tabac = _tabac(db, user)
    tabac.quit_date = (maintenant - timedelta(days=20)).date().isoformat()
    db.commit()

    stats.constater_sobriete(db, user, now=maintenant)
    assert _hp_par_source(db, user, "health_milestone") == [5.5, 16.5]      # 12 h, 2 semaines
    niveau, xp = _perso(db, user).level, _perso(db, user).total_xp

    # Rechute il y a 15 jours : compteur reparti, rien de perdu.
    db.add(models.ConsumptionEntry(user_id=user.id, substance_id=tabac.id,
                                   occurred_at=maintenant - timedelta(days=15)))
    db.commit()
    stats.constater_sobriete(db, user, now=maintenant)
    perso = _perso(db, user)
    assert perso.level >= niveau and perso.total_xp >= xp
    # 12 h et 2 semaines regagnés à 50 %.
    assert _hp_par_source(db, user, "health_milestone") == [2.75, 5.5, 8.25, 16.5]
    paliers = db.query(models.HealthMilestone).filter(models.HealthMilestone.user_id == user.id).all()
    assert sorted(m.ratio for m in paliers) == [0.5, 0.5, 1.0, 1.0]

    # Relancé, ou date d'arrêt déplacée sans nouvelle rechute : rien de plus.
    stats.constater_sobriete(db, user, now=maintenant)
    tabac = _tabac(db, user)
    tabac.quit_date = (maintenant - timedelta(days=1)).date().isoformat()
    db.commit()
    stats.constater_sobriete(db, user, now=maintenant + timedelta(days=30))
    assert len(_hp_par_source(db, user, "health_milestone")) == 4


def test_soigneur_paliers_plus_20_pourcent(joueur, db):
    user, _ = joueur("soigneur")
    maintenant = datetime.now(timezone.utc)
    tabac = _tabac(db, user)
    tabac.quit_date = (maintenant - timedelta(days=2)).date().isoformat()
    db.commit()
    stats.constater_sobriete(db, user, now=maintenant)
    assert _hp_par_source(db, user, "health_milestone") == [9.0]           # 5 × 1,5 × 1,2


# ---------- Branchements dans les routes existantes ----------

def _par_source(db, user):
    db.expire_all()
    resultat: dict = {}
    for e in _evenements(db, user):
        resultat.setdefault(e.source, {}).setdefault(e.stat, 0)
        resultat[e.source][e.stat] += e.base_points
    return resultat


def test_seances_de_sport(client, joueur, db):
    user, h = joueur()
    assert client.post("/training/runs", json={"distanceKm": 5.2, "durationMin": 30}, headers=h).status_code == 201
    serie = {"reps": 10, "weight": 60, "done": True}
    seance = {"mode": "live", "durationMin": 45,
              "exercises": [{"name": "Squat", "sets": [serie, serie]}]}
    assert client.post("/strength-sessions", json=seance, headers=h).status_code == 201
    plus_lourd = {**seance, "exercises": [{"name": "Squat", "sets": [serie, {**serie, "weight": 80}]}]}
    assert client.post("/strength-sessions", json=plus_lourd, headers=h).status_code == 201
    assert client.post("/training/other-sports", json={"sportLabel": "Escalade", "durationMin": 60},
                       headers=h).status_code == 201
    assert client.post("/training/other-sports", json={"sportLabel": "Yoga", "durationMin": 30},
                       headers=h).status_code == 201
    assert client.post("/training/flexibility", json={"activity": "etirements", "plannedDurationMin": 15,
                                                      "durationMin": 15}, headers=h).status_code == 201

    points = _par_source(db, user)
    assert points["run"] == {"end": 5}
    assert points["strength_session"] == {"str": 4}              # 2 séances
    assert points["strength_volume"] == {"str": 2}               # 1 200 kg puis 1 400 kg
    assert points["strength_pr"] == {"str": 5}                   # 80 kg > 60 kg au squat
    assert points["cardio"] == {"end": 6}                        # escalade 60 min, pas le yoga
    assert points["technical_sport"] == {"agi": 2}
    assert points["flexibility_session"] == {"agi": 4}           # yoga + étirements


def test_habitude_tenue_puis_decochee(client, joueur, db):
    user, h = joueur()
    habit_id = client.post("/habits", json={"label": "Lire"}, headers=h).json()["id"]
    assert client.post(f"/habits/{habit_id}/log", headers=h).status_code == 201
    assert _par_source(db, user) == {"habit_done": {"wil": 1}}
    xp = _perso(db, user).total_xp
    assert client.delete(f"/habits/{habit_id}/log", headers=h).status_code == 204
    assert _par_source(db, user) == {}
    assert _perso(db, user).total_xp == xp


def test_serie_de_7_jours(joueur, db):
    user, _ = joueur("samourai")
    habit = models.Habit(user_id=user.id, key="lire", label="Lire")
    db.add(habit)
    db.commit()
    debut = datetime(2026, 8, 1, 9, tzinfo=timezone.utc)
    for i in range(8):
        db.add(models.HabitLog(habit_id=habit.id, occurred_at=debut + timedelta(days=i)))
    db.commit()
    stats.constater_habitudes(db, user)
    serie = _evenements(db, user, "habit_streak")
    assert len(serie) == 1 and serie[0].base_points == 5 and serie[0].date_key == "2026-08-07"
    assert serie[0].points == 5 * 1.5 * 1.25                     # Gardien : +25 %
    assert len(_evenements(db, user, "habit_done")) == 8


def test_suppression_d_une_nuit(client, joueur, db):
    user, h = joueur()
    fin = datetime.now(timezone.utc).replace(microsecond=0)
    debut = fin - timedelta(hours=8)
    nuit = client.post("/sleep", json={"startMs": int(debut.timestamp() * 1000), "endMs": int(fin.timestamp() * 1000)},
                       headers=h).json()
    assert _par_source(db, user) == {"sleep_7h": {"hp": 1}}
    assert client.delete(f"/sleep/{nuit['id']}", headers=h).status_code == 204
    assert _par_source(db, user) == {}


def test_un_echec_du_moteur_ne_bloque_pas_l_action(client, joueur, db, monkeypatch):
    user, h = joueur()

    def panne(*args, **kwargs):
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(stats, "award", panne)
    assert client.post("/training/runs", json={"distanceKm": 3, "durationMin": 20}, headers=h).status_code == 201
    assert client.post("/hydration", json={"amountMl": 5000}, headers=h).status_code == 201
    assert db.query(models.Run).filter(models.Run.user_id == user.id).count() == 1
    assert _evenements(db, user) == []


def test_sans_personnage_les_routes_n_attribuent_rien(client, joueur, db):
    user, h = joueur(personnage=False)
    assert client.post("/training/runs", json={"distanceKm": 3, "durationMin": 20}, headers=h).status_code == 201
    assert client.get("/me/dashboard", headers=h).status_code == 200
    assert _evenements(db, user) == []
