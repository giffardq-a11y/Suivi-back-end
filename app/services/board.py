"""Tableau partagé (écran de salon) : les catégories de suivi de Tanren, par
personne et par jour.

Une catégorie n'apparaît que si son module est actif pour la personne
(app/modules.py). Catégories montrées, avec leur règle « fait » :

- sport       : au moins une séance enregistrée (course, muscu, autre sport,
                souplesse), ou PAS_JOUR_ACTIF pas ou plus.
- nutrition   : au moins un repas enregistré et un total NET (mangé moins
                dépensé en sport, comme GET /diet) qui ne dépasse pas le
                budget du profil de plus de TOLERANCE_CALORIES.
- addictions  : aucune consommation d'alcool ni de tabac, ou consommation
                dans la limite du jour d'une réduction progressive.
- hydratation : total bu au moins égal à l'objectif.
- sommeil     : nuit retenue (une par jour de réveil, l'importée prime sur la
                saisie) au moins égale à la cible.
- habitudes   : toutes les habitudes attendues ce jour-là validées (dues ce
                jour-là, plus celles validées un jour libre) ; une habitude
                hebdomadaire n'est jamais due un jour sans jours fixes ; la
                catégorie est absente un jour où rien n'est attendu.

Cycle, humeur, budget, langues et personnage ne sont jamais montrés : ce
tableau s'affiche sans connexion dans une pièce commune.

Chaque membre peut masquer certaines de ses cases sur un tableau (masquees) :
elles disparaissent de tout, séries et points compris.

Détail des habitudes (detail_habitudes, choisi par le membre, faux par
défaut) : la liste de ses habitudes actives avec leur nom, faite ou non
aujourd'hui et la progression de la semaine (même calcul que l'onglet
Habitudes, habit_progress.progression_semaine). Les prévues non faites
d'abord, MAX_HABITUDES au plus, le reste compté dans habitsMore. Jamais la
note, l'heure de rappel ni les motifs de saut. Rien si la case « habitudes »
est masquée.

Un point par catégorie faite. La série compte les jours d'affilée où toutes
les catégories du socle (sport, nutrition, addictions, selon les modules
actifs) sont faites ; la journée en cours ne casse pas la série tant qu'elle
n'est pas finie. Sans case du socle affichée, la série vaut None.

Les jours sont découpés comme dans le compte, en UTC (jour_du_compte) : ce que
le tableau affiche pour un jour doit être ce que montre l'app pour ce jour.
Rien n'est stocké : tout est recalculé à la lecture.
"""
import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import models, modules
from . import streaks
from .common import jour_du_compte, now_utc
from .habit_progress import effective_habit_target, est_hebdo, jours_actifs, progression_semaine
from .sommeil import nuit_retenue_par_jour
from .substance_progress import limite_du_jour

PAS_JOUR_ACTIF = 8000
TOLERANCE_CALORIES = 1.05
JOURS_HISTORIQUE = 140  # série : un peu plus que 16 semaines
SOCLE_SERIE = ("sport", "nutrition", "addictions")
NOM_PAR_DEFAUT = "Sans nom"
MAX_HABITUDES = 6           # par personne : lisible sur une TV, le reste est compté
LONGUEUR_HABITUDE = 40
LIBELLES = {
    "sport": "Sport", "nutrition": "Nutrition", "addictions": "Alcool et tabac",
    "hydratation": "Hydratation", "sommeil": "Sommeil", "habitudes": "Habitudes",
}


def hacher_jeton(jeton: str) -> str:
    """Seul ce hachage du jeton d'un lien d'écran est stocké (boards.token_hash)."""
    return hashlib.sha256(jeton.encode()).hexdigest()


def nom_affiche(user: models.User) -> str:
    """Nom montré sur l'écran commun. À l'inscription, un compte sans nom
    reçoit le début de son e-mail comme nom affiché (routers/auth.py) : ce
    nom-là n'est jamais repris ici, l'e-mail ne doit pas s'afficher."""
    nom = (user.display_name or "").strip()
    if not nom or nom.lower() == user.email.split("@")[0].lower():
        return NOM_PAR_DEFAUT
    return nom


def _heures(minutes: float) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m:02d}"


def categories_actives(user: models.User) -> list[str]:
    """Clés de LIBELLES dont le module est actif pour la personne, dans l'ordre."""
    return [m for m in LIBELLES if modules.est_actif(user, m)]


def etat_personne(db: Session, user: models.User, maintenant: datetime | None = None,
                  masquees=frozenset(), detail_habitudes: bool = False) -> dict:
    """État du jour et de la semaine d'une personne. `masquees` : cases que ce
    membre cache sur ce tableau ; elles sont retirées dès le départ, donc
    absentes des catégories, des points, de la bande de la semaine et de la
    série (rien ne permet de les déduire)."""
    maintenant = maintenant or now_utc()
    aujourd_hui = jour_du_compte(maintenant)
    debut = aujourd_hui - timedelta(days=JOURS_HISTORIQUE)
    # Un jour de marge sur la fenêtre de lecture.
    depuis = maintenant - timedelta(days=JOURS_HISTORIQUE + 1)
    actifs = [m for m in categories_actives(user) if m not in masquees]

    # --- sport
    minutes_sport: dict[date, float] = defaultdict(float)
    pas: dict[str, int] = {}
    if "sport" in actifs:
        for modele in (models.Run, models.StrengthSession, models.OtherSportLog, models.FlexibilitySession):
            for occurred_at, duree in db.query(modele.occurred_at, modele.duration_min).filter(
                    modele.user_id == user.id, modele.occurred_at >= depuis).all():
                minutes_sport[jour_du_compte(occurred_at)] += duree or 0
        pas = {
            l.date_key: l.steps
            for l in db.query(models.DailySteps).filter(
                models.DailySteps.user_id == user.id, models.DailySteps.date_key >= debut.isoformat()).all()
        }

    # --- nutrition
    calories: dict[date, int] = defaultdict(int)
    depense: dict[date, int] = defaultdict(int)  # sport, comme calories_burned_on
    budget = 2000
    if "nutrition" in actifs:
        for occurred_at, cal in db.query(models.Meal.occurred_at, models.Meal.calories).filter(
                models.Meal.user_id == user.id, models.Meal.occurred_at >= depuis).all():
            calories[jour_du_compte(occurred_at)] += cal or 0
        # Une requête par modèle sur la fenêtre, sans regarder si le module
        # sport est actif (comme le compte).
        for modele in (models.Run, models.StrengthSession, models.OtherSportLog, models.FlexibilitySession):
            for occurred_at, brulees in db.query(modele.occurred_at, modele.calories_burned).filter(
                    modele.user_id == user.id, modele.occurred_at >= depuis).all():
                depense[jour_du_compte(occurred_at)] += brulees or 0
        profil = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
        budget = (profil.daily_calorie_budget if profil else None) or 2000

    # --- alcool et tabac
    conso: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    suivies: list[models.Substance] = []
    jours_sans: int | None = None
    if "addictions" in actifs:
        suivies = db.query(models.Substance).filter(
            models.Substance.user_id == user.id,
            models.Substance.category.in_([models.SubstanceCategory.ALCOHOL, models.SubstanceCategory.TOBACCO]),
        ).all()
        if suivies:
            for occurred_at, substance_id, quantite in db.query(
                    models.ConsumptionEntry.occurred_at, models.ConsumptionEntry.substance_id,
                    models.ConsumptionEntry.quantity).filter(
                    models.ConsumptionEntry.user_id == user.id,
                    models.ConsumptionEntry.substance_id.in_([s.id for s in suivies]),
                    models.ConsumptionEntry.occurred_at >= depuis,
                    models.ConsumptionEntry.type == models.EntryType.CONSUMPTION).all():
                conso[jour_du_compte(occurred_at)][substance_id] += quantite or 1
            jours_sans = min(streaks.current_streak_days(db, s, maintenant) for s in suivies)

    # --- hydratation
    eau: dict[date, int] = defaultdict(int)
    objectif_eau = 2000
    if "hydratation" in actifs:
        for occurred_at, ml in db.query(models.WaterLog.occurred_at, models.WaterLog.amount_ml).filter(
                models.WaterLog.user_id == user.id, models.WaterLog.occurred_at >= depuis).all():
            eau[jour_du_compte(occurred_at)] += ml or 0
        from ..routers.hydration import _objectif_suggere  # import tardif : le router importe les services
        reglages = db.query(models.HydrationSettings).filter(models.HydrationSettings.user_id == user.id).first()
        objectif_eau = (reglages.daily_goal_ml if reglages else None) or _objectif_suggere(db, user)

    # --- sommeil
    nuits: dict[str, float] = {}
    cible_sommeil = 8.0
    if "sommeil" in actifs:
        retenues = nuit_retenue_par_jour(
            db.query(models.SleepLog).filter(
                models.SleepLog.user_id == user.id, models.SleepLog.date_key >= debut.isoformat(),
            ).order_by(models.SleepLog.ended_at.asc()).all())
        nuits = {cle: n.duration_min or 0 for cle, n in retenues.items()}
        reglages_sommeil = db.query(models.SleepSettings).filter(models.SleepSettings.user_id == user.id).first()
        cible_sommeil = (reglages_sommeil.target_hours if reglages_sommeil else None) or 8.0

    # --- habitudes
    habitudes: list[models.Habit] = []
    faites: dict[date, set[str]] = defaultdict(set)
    if "habitudes" in actifs:
        habitudes = db.query(models.Habit).filter(models.Habit.user_id == user.id, models.Habit.active.is_(True)).all()
        if habitudes:
            for habit_id, occurred_at in db.query(models.HabitLog.habit_id, models.HabitLog.occurred_at).filter(
                    models.HabitLog.habit_id.in_([h.id for h in habitudes]), models.HabitLog.occurred_at >= depuis).all():
                faites[jour_du_compte(occurred_at)].add(habit_id)

    def categories(jour: date) -> list[dict]:
        cle = jour.isoformat()
        sortie = []
        for module in actifs:
            if module == "sport":
                nb_pas = pas.get(cle, 0)
                fait = jour in minutes_sport or nb_pas >= PAS_JOUR_ACTIF
                if jour in minutes_sport:
                    minutes = int(round(minutes_sport[jour]))
                    valeur = f"{minutes} min" if minutes else "séance faite"
                else:
                    valeur = f"{nb_pas} pas" if nb_pas else "rien"
            elif module == "nutrition":
                net = calories.get(jour, 0) - depense.get(jour, 0)
                fait = jour in calories and net <= budget * TOLERANCE_CALORIES
                valeur = f"{net} / {budget} kcal"
            elif module == "addictions":
                du_jour = conso.get(jour, {})
                a_consomme = any(q > 0 for q in du_jour.values())
                fait = True
                for s in suivies:
                    limite = limite_du_jour(s, jour)
                    total = du_jour.get(s.id, 0)
                    if total > 0 and (limite is None or total > limite):
                        fait = False
                if not a_consomme:
                    valeur = f"{jours_sans} j sans" if jours_sans is not None else "aucune"
                else:
                    valeur = "dans la limite" if fait else "consommation"
            elif module == "hydratation":
                fait = eau.get(jour, 0) >= objectif_eau
                valeur = f"{eau.get(jour, 0) / 1000:.1f} / {objectif_eau / 1000:.1f} L"
            elif module == "sommeil":
                fait = nuits.get(cle, 0) >= cible_sommeil * 60
                valeur = f"{_heures(nuits[cle])} / {_heures(cible_sommeil * 60)}" if cle in nuits else "non saisi"
            else:  # habitudes
                validees = faites.get(jour, set())

                def due(h) -> bool:
                    fixes = jours_actifs(h)
                    return jour.weekday() in fixes if fixes is not None else not est_hebdo(h)

                # Une hebdomadaire faite un jour libre compte pour, jamais contre.
                attendues = [h for h in habitudes if due(h) or h.id in validees]
                if not attendues:
                    continue
                nb = sum(1 for h in attendues if h.id in validees)
                fait = nb == len(attendues)
                valeur = f"{nb} / {len(attendues)}"
            sortie.append({"key": module, "label": LIBELLES[module], "done": bool(fait), "value": valeur})
        return sortie

    lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday())
    semaine = []
    points = points_max = 0
    for i in range(7):
        jour = lundi + timedelta(days=i)
        cats = categories(jour)
        points_max += len(cats)
        if jour <= aujourd_hui:
            nb = sum(c["done"] for c in cats)
            points += nb
            semaine.append({"date": jour.isoformat(), "done": nb, "total": len(cats)})

    socle = [m for m in SOCLE_SERIE if m in actifs]

    def complet(jour: date) -> bool:
        etat = {c["key"]: c["done"] for c in categories(jour)}
        return bool(socle) and all(etat.get(m, False) for m in socle)

    # Aucune case du socle affichée : la série n'a pas de sens à l'écran.
    serie: int | None = None
    if socle:
        serie = 1 if complet(aujourd_hui) else 0
        jour = aujourd_hui - timedelta(days=1)
        while jour >= debut and complet(jour):
            serie += 1
            jour -= timedelta(days=1)

    sortie = {
        "name": nom_affiche(user),
        "today": {"date": aujourd_hui.isoformat(), "categories": categories(aujourd_hui)},
        "week": semaine,
        "points": points,
        "pointsMax": points_max,
        "streakDays": serie,
    }
    if detail_habitudes and "habitudes" in actifs:
        detail = _detail_habitudes(db, habitudes, faites.get(aujourd_hui, set()), aujourd_hui, maintenant)
        sortie["habits"] = detail[:MAX_HABITUDES]
        sortie["habitsMore"] = max(0, len(detail) - MAX_HABITUDES)
    return sortie


def _detail_habitudes(db: Session, habitudes: list, validees: set, jour: date, maintenant: datetime) -> list[dict]:
    """Nom, fait aujourd'hui et progression de la semaine de chaque habitude
    active ; prévues non faites, puis faites, puis non prévues ce jour-là."""
    if not habitudes:
        return []
    lundi = datetime.combine(jour - timedelta(days=jour.weekday()), datetime.min.time(), tzinfo=maintenant.tzinfo)
    logs: dict[str, list] = defaultdict(list)
    for log in db.query(models.HabitLog).filter(
            models.HabitLog.habit_id.in_([h.id for h in habitudes]), models.HabitLog.occurred_at >= lundi).all():
        logs[log.habit_id].append(log)

    lignes = []
    for h in habitudes:
        fixes = jours_actifs(h)
        prevue = jour.weekday() in fixes if fixes is not None else not est_hebdo(h)
        faite = h.id in validees
        nb, volume, _ = progression_semaine(h, logs.get(h.id, []))
        if volume is not None:
            avancement = f"{volume:g} / {h.weekly_volume_target:g} {h.unit or ''}".strip()
        else:
            avancement = f"{nb} / {h.weekly_target or 7} cette semaine"
        cible = effective_habit_target(h, maintenant)
        rang = 0 if prevue and not faite else (1 if faite else 2)
        lignes.append((rang, (h.label or "").lower(), {
            "label": (h.label or "")[:LONGUEUR_HABITUDE],
            "done": faite,
            "progress": f"{cible} · {avancement}" if cible else avancement,
        }))
    return [ligne for _, _, ligne in sorted(lignes, key=lambda x: (x[0], x[1]))]
