"""Tableau partagé (écran de salon) : les catégories de suivi de Tanren, par
personne et par jour.

Une catégorie n'apparaît que si son module est actif pour la personne
(app/modules.py). Catégories montrées, avec leur règle « fait » :

- sport       : au moins une séance enregistrée (course, muscu, autre sport,
                souplesse), ou PAS_JOUR_ACTIF pas ou plus.
- nutrition   : au moins un repas enregistré et un total de calories qui ne
                dépasse pas le budget du profil de plus de TOLERANCE_CALORIES.
- addictions  : aucune consommation d'alcool ni de tabac enregistrée.
- hydratation : total bu au moins égal à l'objectif.
- sommeil     : nuit (rattachée au jour du réveil) au moins égale à la cible.
- habitudes   : toutes les habitudes prévues ce jour-là validées ; la
                catégorie est absente un jour sans habitude prévue.

Cycle, humeur, budget, langues et personnage ne sont jamais montrés : ce
tableau s'affiche sans connexion dans une pièce commune.

Un point par catégorie faite. La série compte les jours d'affilée où toutes
les catégories du socle (sport, nutrition, addictions, selon les modules
actifs) sont faites ; la journée en cours ne casse pas la série tant qu'elle
n'est pas finie.

Les jours sont découpés dans le fuseau de l'utilisateur (User.timezone), pas
en UTC : une séance à 23 h 30 doit compter pour le jour où elle a été faite.
Rien n'est stocké : tout est recalculé à la lecture.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import models, modules
from . import streaks
from .common import aware, fuseau_utilisateur, now_utc
from .habit_progress import jours_actifs

PAS_JOUR_ACTIF = 8000
TOLERANCE_CALORIES = 1.05
JOURS_HISTORIQUE = 140  # pesées et série : un peu plus que 16 semaines
SOCLE_SERIE = ("sport", "nutrition", "addictions")
NOM_PAR_DEFAUT = "Sans nom"
LIBELLES = {
    "sport": "Sport", "nutrition": "Nutrition", "addictions": "Alcool et tabac",
    "hydratation": "Hydratation", "sommeil": "Sommeil", "habitudes": "Habitudes",
}


def nom_affiche(user: models.User) -> str:
    """Nom montré sur l'écran commun. À l'inscription, un compte sans nom
    reçoit le début de son e-mail comme nom affiché (routers/auth.py) : ce
    nom-là n'est jamais repris ici, l'e-mail ne doit pas s'afficher."""
    nom = (user.display_name or "").strip()
    if not nom or nom.lower() == user.email.split("@")[0].lower():
        return NOM_PAR_DEFAUT
    return nom


def _jour_local(dt: datetime, fuseau) -> date:
    return aware(dt).astimezone(fuseau).date()


def _heures(minutes: float) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m:02d}"


def etat_personne(db: Session, user: models.User, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or now_utc()
    fuseau = fuseau_utilisateur(user)
    aujourd_hui = _jour_local(maintenant, fuseau)
    debut = aujourd_hui - timedelta(days=JOURS_HISTORIQUE)
    # Un jour de marge : le découpage local peut déborder sur la veille en UTC.
    depuis = maintenant - timedelta(days=JOURS_HISTORIQUE + 1)
    actifs = [m for m in LIBELLES if modules.est_actif(user, m)]

    # --- sport
    minutes_sport: dict[date, float] = defaultdict(float)
    pas: dict[str, int] = {}
    if "sport" in actifs:
        for modele in (models.Run, models.StrengthSession, models.OtherSportLog, models.FlexibilitySession):
            for occurred_at, duree in db.query(modele.occurred_at, modele.duration_min).filter(
                    modele.user_id == user.id, modele.occurred_at >= depuis).all():
                minutes_sport[_jour_local(occurred_at, fuseau)] += duree or 0
        pas = {
            l.date_key: l.steps
            for l in db.query(models.DailySteps).filter(
                models.DailySteps.user_id == user.id, models.DailySteps.date_key >= debut.isoformat()).all()
        }

    # --- nutrition
    calories: dict[date, int] = defaultdict(int)
    budget = 2000
    if "nutrition" in actifs:
        for occurred_at, cal in db.query(models.Meal.occurred_at, models.Meal.calories).filter(
                models.Meal.user_id == user.id, models.Meal.occurred_at >= depuis).all():
            calories[_jour_local(occurred_at, fuseau)] += cal or 0
        profil = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
        budget = (profil.daily_calorie_budget if profil else None) or 2000

    # --- alcool et tabac
    jours_conso: set[date] = set()
    jours_sans: int | None = None
    if "addictions" in actifs:
        suivies = db.query(models.Substance).filter(
            models.Substance.user_id == user.id,
            models.Substance.category.in_([models.SubstanceCategory.ALCOHOL, models.SubstanceCategory.TOBACCO]),
        ).all()
        if suivies:
            ids = [s.id for s in suivies]
            jours_conso = {
                _jour_local(l[0], fuseau)
                for l in db.query(models.ConsumptionEntry.occurred_at).filter(
                    models.ConsumptionEntry.user_id == user.id,
                    models.ConsumptionEntry.substance_id.in_(ids),
                    models.ConsumptionEntry.occurred_at >= depuis,
                    models.ConsumptionEntry.type == models.EntryType.CONSUMPTION,
                ).all()
            }
            jours_sans = min(streaks.current_streak_days(db, s, maintenant) for s in suivies)

    # --- hydratation
    eau: dict[date, int] = defaultdict(int)
    objectif_eau = 2000
    if "hydratation" in actifs:
        for occurred_at, ml in db.query(models.WaterLog.occurred_at, models.WaterLog.amount_ml).filter(
                models.WaterLog.user_id == user.id, models.WaterLog.occurred_at >= depuis).all():
            eau[_jour_local(occurred_at, fuseau)] += ml or 0
        from ..routers.hydration import _objectif_suggere  # import tardif : le router importe les services
        reglages = db.query(models.HydrationSettings).filter(models.HydrationSettings.user_id == user.id).first()
        objectif_eau = (reglages.daily_goal_ml if reglages else None) or _objectif_suggere(db, user)

    # --- sommeil
    nuits: dict[str, float] = defaultdict(float)
    cible_sommeil = 8.0
    if "sommeil" in actifs:
        for cle, duree in db.query(models.SleepLog.date_key, models.SleepLog.duration_min).filter(
                models.SleepLog.user_id == user.id, models.SleepLog.date_key >= debut.isoformat()).all():
            nuits[cle] += duree or 0
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
                faites[_jour_local(occurred_at, fuseau)].add(habit_id)

    def categories(jour: date) -> list[dict]:
        cle = jour.isoformat()
        sortie = []
        for module in actifs:
            if module == "sport":
                nb_pas = pas.get(cle, 0)
                fait = jour in minutes_sport or nb_pas >= PAS_JOUR_ACTIF
                if jour in minutes_sport:
                    valeur = f"{int(round(minutes_sport[jour]))} min"
                else:
                    valeur = f"{nb_pas} pas" if nb_pas else "rien"
            elif module == "nutrition":
                fait = jour in calories and calories[jour] <= budget * TOLERANCE_CALORIES
                valeur = f"{calories.get(jour, 0)} / {budget} kcal"
            elif module == "addictions":
                fait = jour not in jours_conso
                valeur = "consommation" if not fait else (f"{jours_sans} j sans" if jours_sans is not None else "aucune")
            elif module == "hydratation":
                fait = eau.get(jour, 0) >= objectif_eau
                valeur = f"{eau.get(jour, 0) / 1000:.1f} / {objectif_eau / 1000:.1f} L"
            elif module == "sommeil":
                fait = nuits.get(cle, 0) >= cible_sommeil * 60
                valeur = f"{_heures(nuits[cle])} / {_heures(cible_sommeil * 60)}" if cle in nuits else "non saisi"
            else:  # habitudes
                prevues = [h for h in habitudes if jours_actifs(h) is None or jour.weekday() in jours_actifs(h)]
                if not prevues:
                    continue
                nb = sum(1 for h in prevues if h.id in faites.get(jour, set()))
                fait = nb == len(prevues)
                valeur = f"{nb} / {len(prevues)}"
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

    serie = 1 if complet(aujourd_hui) else 0
    jour = aujourd_hui - timedelta(days=1)
    while jour >= debut and complet(jour):
        serie += 1
        jour -= timedelta(days=1)

    # Une pesée par jour (la dernière), de la plus ancienne à la plus récente.
    pesees: dict[date, float] = {}
    for occurred_at, kg in db.query(models.WeightEntry.occurred_at, models.WeightEntry.weight_kg).filter(
            models.WeightEntry.user_id == user.id, models.WeightEntry.occurred_at >= depuis,
    ).order_by(models.WeightEntry.occurred_at.asc()).all():
        pesees[_jour_local(occurred_at, fuseau)] = kg

    return {
        "name": nom_affiche(user),
        "today": {"date": aujourd_hui.isoformat(), "categories": categories(aujourd_hui)},
        "week": semaine,
        "points": points,
        "pointsMax": points_max,
        "streakDays": serie,
        "weights": [{"date": j.isoformat(), "kg": round(kg, 1)} for j, kg in sorted(pesees.items())],
    }
