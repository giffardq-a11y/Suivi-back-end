"""Tableau partagé (écran de salon) : trois cases par jour et par personne.

- bouger : au moins une séance enregistrée ce jour-là (course, muscu, autre
  sport, souplesse), ou PAS_JOUR_ACTIF pas ou plus (jour de repos actif).
- manger : au moins un repas enregistré et un total de calories qui ne
  dépasse pas le budget du profil de plus de TOLERANCE_CALORIES.
- sobre : aucune consommation d'alcool ni de tabac enregistrée.

Un point par case : 3 par jour, 21 par semaine (lundi à dimanche). La série
compte les jours d'affilée où les trois cases sont cochées ; la journée en
cours ne casse pas la série tant qu'elle n'est pas finie.

Les jours sont découpés dans le fuseau de l'utilisateur (User.timezone), pas
en UTC : une séance à 23 h 30 doit compter pour le jour où elle a été faite.
Rien n'est stocké : tout est recalculé à la lecture.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import models
from .common import aware, fuseau_utilisateur, now_utc

PAS_JOUR_ACTIF = 8000
TOLERANCE_CALORIES = 1.05
JOURS_HISTORIQUE = 140  # pesées et série : un peu plus que 16 semaines


def _jour_local(dt: datetime, fuseau) -> date:
    return aware(dt).astimezone(fuseau).date()


def _jours_avec(db: Session, modele, user_id: str, depuis: datetime, fuseau) -> set[date]:
    lignes = db.query(modele.occurred_at).filter(modele.user_id == user_id, modele.occurred_at >= depuis).all()
    return {_jour_local(l[0], fuseau) for l in lignes}


def etat_personne(db: Session, user: models.User, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or now_utc()
    fuseau = fuseau_utilisateur(user)
    aujourd_hui = _jour_local(maintenant, fuseau)
    debut = aujourd_hui - timedelta(days=JOURS_HISTORIQUE)
    # Un jour de marge : le découpage local peut déborder sur la veille en UTC.
    depuis = maintenant - timedelta(days=JOURS_HISTORIQUE + 1)

    jours_sport: set[date] = set()
    for modele in (models.Run, models.StrengthSession, models.OtherSportLog, models.FlexibilitySession):
        jours_sport |= _jours_avec(db, modele, user.id, depuis, fuseau)
    pas = {
        l.date_key: l.steps
        for l in db.query(models.DailySteps).filter(
            models.DailySteps.user_id == user.id, models.DailySteps.date_key >= debut.isoformat()).all()
    }

    calories: dict[date, int] = defaultdict(int)
    for occurred_at, cal in db.query(models.Meal.occurred_at, models.Meal.calories).filter(
            models.Meal.user_id == user.id, models.Meal.occurred_at >= depuis).all():
        calories[_jour_local(occurred_at, fuseau)] += cal or 0
    profil = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
    budget = (profil.daily_calorie_budget if profil else None) or 2000

    jours_conso = {
        _jour_local(l[0], fuseau)
        for l in db.query(models.ConsumptionEntry.occurred_at)
        .join(models.Substance, models.Substance.id == models.ConsumptionEntry.substance_id)
        .filter(
            models.ConsumptionEntry.user_id == user.id,
            models.ConsumptionEntry.occurred_at >= depuis,
            models.ConsumptionEntry.type == models.EntryType.CONSUMPTION,
            models.Substance.category.in_([models.SubstanceCategory.ALCOHOL, models.SubstanceCategory.TOBACCO]),
        ).all()
    }

    def cases(jour: date) -> dict:
        bouger = jour in jours_sport or pas.get(jour.isoformat(), 0) >= PAS_JOUR_ACTIF
        manger = jour in calories and calories[jour] <= budget * TOLERANCE_CALORIES
        sobre = jour not in jours_conso
        return {"date": jour.isoformat(), "move": bouger, "eat": manger, "clean": sobre}

    lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday())
    semaine = [cases(lundi + timedelta(days=i)) for i in range(aujourd_hui.weekday() + 1)]
    points = sum(j["move"] + j["eat"] + j["clean"] for j in semaine)

    def complet(jour: date) -> bool:
        c = cases(jour)
        return c["move"] and c["eat"] and c["clean"]

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
        "name": user.display_name or user.email.split("@")[0],
        "today": cases(aujourd_hui),
        "week": semaine,
        "points": points,
        "pointsMax": 21,
        "streakDays": serie,
        "weights": [{"date": j.isoformat(), "kg": round(kg, 1)} for j, kg in sorted(pesees.items())],
    }
