"""Réinitialisation de compte (2 niveaux) : voir app/services/reset.py.

Réutilise le remplisseur générique de test_suppression_compte.py (une ligne
par table, clés étrangères chaînées) pour ne pas maintenir une deuxième
liste de tables à la main.
"""
from datetime import datetime, timedelta, timezone

from app import models
from app.database import SessionLocal
from app.routers import goals as routeur_goals
from app.routers import journal_stats as routeur_journal
from app.services import reset as service_reset
from app.services.common import aware, debut_suivi
from app.services.habit_progress import effective_habit_target, semaine_du_plan
from app.services.reset import TABLES_EPARGNEES_TOUT_EFFACER, TABLES_PROGRESSION
from app.services.streaks import current_streak_days, personal_best_days
from app.services.substance_progress import limite_du_jour, palier_courant
from test_suppression_compte import _lignes_de, _remplir

# Instants fixes (mi-mois, midi UTC) : les tests ne dépendent ni de l'heure ni
# du jour d'exécution — le calendrier, lui, dépend du 1er du mois.
CREATION = datetime(2026, 3, 1, 9, tzinfo=timezone.utc)
RESET = datetime(2026, 3, 12, 12, tzinfo=timezone.utc)
MAINTENANT = datetime(2026, 3, 15, 12, tzinfo=timezone.utc)


def _figer(monkeypatch, instant):
    """Date de la remise à zéro (reset.now_utc) fixée à `instant`."""
    monkeypatch.setattr(service_reset, "now_utc", lambda: instant)


def _reinitialiser(client, h, mdp, niveau="progression"):
    r = client.post(f"/me/reset/{niveau}", json={"password": mdp}, headers=h)
    assert r.status_code == 204, r.text


def _creation_du_compte(user_id, quand):
    db = SessionLocal()
    db.get(models.User, user_id).created_at = quand
    db.commit()
    db.close()


def _substance(db, user_id):
    return db.query(models.Substance).filter_by(user_id=user_id).order_by(models.Substance.label).first()


def test_progression_efface_historique_garde_configuration(client, nouveau_compte, monkeypatch):
    _figer(monkeypatch, RESET)
    email, mdp, h, id_a = nouveau_compte()
    _, _, _, id_b = nouveau_compte()
    db = SessionLocal()
    _remplir(db, id_a)
    _remplir(db, id_b)
    avant_a = _lignes_de(db, id_a)
    avant_b = _lignes_de(db, id_b)
    db.close()

    assert client.post("/me/reset/progression", json={"password": "faux"}, headers=h).status_code == 403

    r = client.post("/me/reset/progression", json={"password": mdp}, headers=h)
    assert r.status_code == 204

    db = SessionLocal()
    apres_a = _lignes_de(db, id_a)
    # Tables de progression vidées, tout le reste toujours à 1 ligne (la
    # config n'est jamais supprimée, seulement recalée pour certaines).
    for nom, n in avant_a.items():
        if nom in TABLES_PROGRESSION:
            assert nom not in apres_a, f"{nom} aurait dû être vidée"
        else:
            assert apres_a.get(nom) == n, f"{nom} n'aurait pas dû changer de nombre de lignes"

    substance = db.query(models.Substance).filter_by(user_id=id_a).first()
    assert substance.quit_date == RESET.date().isoformat()

    goal = db.query(models.Goal).filter_by(user_id=id_a).first()
    assert goal.current_value == 0
    assert goal.completed_at is None

    perso = db.query(models.Character).filter_by(user_id=id_a).first()
    assert perso.level == 1 and perso.total_xp == 0 and perso.shards == 0 and perso.xp_avance == 0

    # Le compte reste utilisable : session valide, pas de déconnexion.
    assert client.get("/diet/pantry", headers=h).status_code == 200
    # L'autre compte n'a rien perdu.
    assert _lignes_de(db, id_b) == avant_b
    db.close()


def test_tout_effacer_garde_seulement_le_compte(client, nouveau_compte):
    email, mdp, h, id_a = nouveau_compte()
    _, _, _, id_b = nouveau_compte()
    db = SessionLocal()
    _remplir(db, id_a)
    _remplir(db, id_b)
    avant_b = _lignes_de(db, id_b)
    db.close()

    assert client.post("/me/reset/tout", json={"password": "faux"}, headers=h).status_code == 403

    r = client.post("/me/reset/tout", json={"password": mdp}, headers=h)
    assert r.status_code == 204

    db = SessionLocal()
    apres_a = _lignes_de(db, id_a)
    # Rien ne doit rester en dehors des tables épargnées (le compte lui-même
    # et sa session) et des deux consommations par défaut recréées (voir
    # test_tout_effacer_recree_les_consommations_par_defaut), et les épargnées
    # ne sont jamais touchées.
    assert set(apres_a) <= TABLES_EPARGNEES_TOUT_EFFACER | {"substances"}
    assert apres_a.get("substances") == 2
    assert apres_a.get("refresh_tokens", 1) >= 1

    # Le compte reste connecté (contrairement à DELETE /me).
    assert client.get("/diet/pantry", headers=h).status_code == 200
    assert _lignes_de(db, id_b) == avant_b
    db.close()


# ---------- Ce que la remise à zéro doit aussi remettre à son départ ----------

def test_habitudes_progressives_reviennent_a_leur_valeur_de_depart(client, nouveau_compte, monkeypatch):
    _figer(monkeypatch, RESET)
    _, mdp, h, uid = nouveau_compte()
    db = SessionLocal()
    depart = RESET - timedelta(weeks=5)
    db.add_all([
        # Rythme prédéfini (4 semaines) : après 5 semaines, au palier final.
        models.Habit(user_id=uid, key="marche", label="Marche", habit_type="sport", progressive_rhythm="normal",
                     progressive_start_value=2, progressive_target_value=6, progressive_start_date=depart,
                     target="6x / semaine"),
        # Plan sur 15 semaines : semaine 6 avant, semaine 1 après.
        models.Habit(user_id=uid, key="course", label="Course", habit_type="sport", progressive_weeks=15,
                     progressive_unit="km / semaine", progressive_start_value=5, progressive_target_value=12,
                     progressive_start_date=depart, target="9 km / semaine"),
        # Habitude non progressive : intacte.
        models.Habit(user_id=uid, key="lire", label="Lire", target="20 pages"),
    ])
    db.commit()
    marche = db.query(models.Habit).filter_by(user_id=uid, key="marche").one()
    course = db.query(models.Habit).filter_by(user_id=uid, key="course").one()
    assert effective_habit_target(marche, RESET) == "6x / semaine"
    assert semaine_du_plan(course, RESET) == (6, 15)
    db.close()

    _reinitialiser(client, h, mdp)

    db = SessionLocal()
    marche = db.query(models.Habit).filter_by(user_id=uid, key="marche").one()
    course = db.query(models.Habit).filter_by(user_id=uid, key="course").one()
    lire = db.query(models.Habit).filter_by(user_id=uid, key="lire").one()
    assert aware(marche.progressive_start_date) == RESET
    assert marche.target == "2x / semaine"
    assert effective_habit_target(marche, RESET) == "2x / semaine"
    assert course.target == "5 km / semaine"
    assert semaine_du_plan(course, RESET) == (1, 15)
    assert lire.target == "20 pages"
    db.close()


def test_reduction_progressive_revient_au_palier_un(client, nouveau_compte, monkeypatch):
    _figer(monkeypatch, RESET)
    _, mdp, h, uid = nouveau_compte()
    db = SessionLocal()
    sub = _substance(db, uid)
    sub.reduction_start_value = 10
    sub.reduction_step_per_week = 2
    sub.reduction_start_date = (RESET - timedelta(weeks=3)).date()
    sans = db.query(models.Substance).filter(models.Substance.user_id == uid, models.Substance.id != sub.id).first()
    db.commit()
    assert limite_du_jour(sub, RESET.date()) == 4 and palier_courant(sub, RESET.date()) == 4
    sub_id, sans_id = sub.id, sans.id
    db.close()

    _reinitialiser(client, h, mdp)

    db = SessionLocal()
    sub = db.get(models.Substance, sub_id)
    assert sub.reduction_start_date == RESET.date()
    assert limite_du_jour(sub, RESET.date()) == 10 and palier_courant(sub, RESET.date()) == 1
    # Une consommation sans réduction configurée n'en gagne pas une.
    assert db.get(models.Substance, sans_id).reduction_start_date is None
    db.close()


def test_cagnottes_et_habitudes_a_perdre_repartent_de_zero(client, nouveau_compte, monkeypatch):
    _figer(monkeypatch, RESET)
    _, mdp, h, uid = nouveau_compte()
    _, _, _, autre = nouveau_compte()
    db = SessionLocal()
    db.add_all([
        models.SavingsPot(user_id=uid, label="Vacances", target_amount=100, current_amount=100,
                          achieved_at=RESET - timedelta(days=2)),
        models.SavingsPot(user_id=autre, label="Voiture", target_amount=100, current_amount=40),
        models.BadHabit(user_id=uid, label="Ongles", last_occurrence_at=RESET - timedelta(days=30)),
    ])
    db.commit()
    db.close()

    _reinitialiser(client, h, mdp)

    db = SessionLocal()
    cagnotte = db.query(models.SavingsPot).filter_by(user_id=uid).one()
    assert cagnotte.current_amount == 0 and cagnotte.achieved_at is None
    mauvaise = db.query(models.BadHabit).filter_by(user_id=uid).one()
    assert aware(mauvaise.last_occurrence_at) == RESET
    # Le compte voisin n'est pas touché.
    assert db.query(models.SavingsPot).filter_by(user_id=autre).one().current_amount == 40
    db.close()


def test_les_deux_niveaux_notent_le_debut_du_suivi(client, nouveau_compte, monkeypatch):
    _figer(monkeypatch, RESET)
    for niveau in ("progression", "tout"):
        _, mdp, h, uid = nouveau_compte()
        _creation_du_compte(uid, CREATION)
        db = SessionLocal()
        assert db.get(models.User, uid).progress_reset_at is None
        assert debut_suivi(db.get(models.User, uid)) == CREATION
        db.close()

        _reinitialiser(client, h, mdp, niveau)

        db = SessionLocal()
        user = db.get(models.User, uid)
        assert aware(user.progress_reset_at) == RESET
        assert debut_suivi(user) == RESET
        db.close()


def _jours(client, h, monkeypatch, maintenant):
    monkeypatch.setattr(routeur_journal, "now_utc", lambda: maintenant)
    r = client.get("/history", headers=h)
    assert r.status_code == 200, r.text
    return {j["day"]: j["status"] for j in r.json()["days"] if j}


def test_calendrier_compte_neuf_rien_avant_la_creation(client, nouveau_compte, monkeypatch):
    _, _, h, uid = nouveau_compte()
    _creation_du_compte(uid, datetime(2026, 3, 10, 9, tzinfo=timezone.utc))
    db = SessionLocal()
    sub = _substance(db, uid)
    db.add(models.ConsumptionEntry(user_id=uid, substance_id=sub.id, quantity=1,
                                   occurred_at=datetime(2026, 3, 12, 20, tzinfo=timezone.utc)))
    db.commit()
    db.close()

    jours = _jours(client, h, monkeypatch, MAINTENANT)
    assert all(jours[d] == "none" for d in range(1, 10))      # avant la création
    assert jours[10] == "clean" and jours[11] == "clean"
    assert jours[12] == "partial"
    assert jours[13] == "clean" and jours[15] == "clean"      # aujourd'hui compris
    assert all(jours[d] == "none" for d in range(16, 32))     # à venir


def test_calendrier_apres_reinitialisation_rien_avant_elle(client, nouveau_compte, monkeypatch):
    _figer(monkeypatch, RESET)
    _, mdp, h, uid = nouveau_compte()
    _creation_du_compte(uid, CREATION)
    db = SessionLocal()
    sub = _substance(db, uid)
    db.add(models.ConsumptionEntry(user_id=uid, substance_id=sub.id, quantity=1,
                                   occurred_at=datetime(2026, 3, 5, 20, tzinfo=timezone.utc)))
    db.commit()
    db.close()
    avant = _jours(client, h, monkeypatch, MAINTENANT)
    assert avant[5] == "partial" and avant[1] == "clean"

    _reinitialiser(client, h, mdp)

    jours = _jours(client, h, monkeypatch, MAINTENANT)
    assert all(jours[d] == "none" for d in range(1, 12))      # le passé d'avant n'est plus affiché
    assert all(jours[d] == "clean" for d in range(12, 16))
    assert all(jours[d] == "none" for d in range(16, 32))


def test_record_et_benefices_repartent_de_zero(client, nouveau_compte, monkeypatch):
    _figer(monkeypatch, RESET)
    _, mdp, h, uid = nouveau_compte()
    _creation_du_compte(uid, datetime(2026, 1, 1, 9, tzinfo=timezone.utc))
    db = SessionLocal()
    sub = _substance(db, uid)
    db.add(models.ConsumptionEntry(user_id=uid, substance_id=sub.id, quantity=1,
                                   occurred_at=datetime(2026, 1, 20, 20, tzinfo=timezone.utc)))
    db.commit()
    assert personal_best_days(db, sub, now=MAINTENANT) == 53     # 20 janvier -> 15 mars
    db.close()

    _reinitialiser(client, h, mdp)

    db = SessionLocal()
    sub = _substance(db, uid)
    # Série en cours et record : 12 mars -> 15 mars midi = 3 jours, pas
    # l'ancienneté du compte (73 jours).
    assert current_streak_days(db, sub, now=MAINTENANT) == 3
    assert personal_best_days(db, sub, now=MAINTENANT) == 3
    db.close()

    monkeypatch.setattr(routeur_goals, "now_utc", lambda: MAINTENANT)
    r = client.get("/benefits", headers=h)
    assert r.status_code == 200, r.text
    for substance in r.json()["substances"]:
        etat = {m["key"]: m["reached"] for m in substance["milestones"]}
        # 84 h écoulées depuis le 12 mars minuit : 24 h et 72 h, pas 2 semaines.
        assert etat == {"24h": True, "72h": True, "2sem": False, "1mois": False, "3mois": False}, substance


def test_record_sans_consommation_egale_la_serie_en_cours(client, nouveau_compte):
    _, _, _, uid = nouveau_compte()
    _creation_du_compte(uid, CREATION)
    db = SessionLocal()
    sub = _substance(db, uid)
    assert current_streak_days(db, sub, now=MAINTENANT) == 14
    assert personal_best_days(db, sub, now=MAINTENANT) == 14
    # Date d'arrêt déclarée : même référence pour la série et pour le record.
    sub.quit_date = "2026-03-10"
    db.commit()
    assert current_streak_days(db, sub, now=MAINTENANT) == 5
    assert personal_best_days(db, sub, now=MAINTENANT) == 5
    db.close()


def test_record_garde_l_historique_apres_une_nouvelle_date_d_arret(client, nouveau_compte):
    """Déclarer une date d'arrêt après une rechute ne doit pas effacer un
    ancien record : seule une remise à zéro repart de rien."""
    _, _, _, uid = nouveau_compte()
    _creation_du_compte(uid, datetime(2026, 1, 1, 9, tzinfo=timezone.utc))
    db = SessionLocal()
    sub = _substance(db, uid)
    for jour in (datetime(2026, 1, 10, 20, tzinfo=timezone.utc), datetime(2026, 2, 20, 20, tzinfo=timezone.utc)):
        db.add(models.ConsumptionEntry(user_id=uid, substance_id=sub.id, quantity=1, occurred_at=jour))
    sub.quit_date = "2026-03-10"
    db.commit()
    # 10 janvier -> 20 février = 41 jours, plus long que la série en cours
    # (20 février -> 15 mars = 22 jours pleins).
    assert current_streak_days(db, sub, now=MAINTENANT) == 22
    assert personal_best_days(db, sub, now=MAINTENANT) == 41
    db.close()


def test_tout_effacer_recree_les_consommations_par_defaut(client, nouveau_compte, nouveau_compte_avec_modules):
    _, mdp, h, uid = nouveau_compte()
    db = SessionLocal()
    avant = {s.category: (s.label, s.unit, s.unit_cost) for s in db.query(models.Substance).filter_by(user_id=uid)}
    ancien_ids = {s.id for s in db.query(models.Substance).filter_by(user_id=uid)}
    db.close()
    assert set(avant) == {models.SubstanceCategory.ALCOHOL, models.SubstanceCategory.TOBACCO}

    _reinitialiser(client, h, mdp, "tout")

    db = SessionLocal()
    apres = db.query(models.Substance).filter_by(user_id=uid).all()
    assert {s.category: (s.label, s.unit, s.unit_cost) for s in apres} == avant
    assert not ({s.id for s in apres} & ancien_ids)          # recréées, pas conservées
    db.close()
    # Compte utilisable : le tableau de bord retrouve ses consommations.
    assert client.get("/me/dashboard", headers=h).status_code == 200

    # Sans le module addictions, rien n'est recréé (comme à l'inscription).
    _, mdp2, h2, uid2 = nouveau_compte_avec_modules(["sport"])
    _reinitialiser(client, h2, mdp2, "tout")
    db = SessionLocal()
    assert db.query(models.Substance).filter_by(user_id=uid2).count() == 0
    db.close()
