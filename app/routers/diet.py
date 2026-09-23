from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..generateur_repas import generer_plan
from ..liste_courses import liste_de_courses
from ..plan_alimentation import JOURS, PLAN_NOM, SEMAINE_TYPE
from ..services.common import now_utc, to_ms, relative_time, is_same_day
from ..services.sport import calories_burned_on
from .profile import _current_weight_kg, _get_or_create_profile, _suggested_calorie_budget

router = APIRouter(prefix="/diet", tags=["diet"])

MEAL_TYPE_LABEL = {
    "petit-dejeuner": "Petit-déjeuner",
    "dejeuner": "Déjeuner",
    "diner": "Dîner",
    "collation": "Collation",
}
# Ordre d'affichage d'une journée, pour que le plan se lise dans l'ordre où on
# mange même si les repas arrivent en vrac de la base.
MEAL_TYPE_ORDER = ["petit-dejeuner", "dejeuner", "collation", "diner"]


class MealCreate(BaseModel):
    label: str
    calories: int
    type: str
    proteines: int = 0
    glucides: int = 0
    lipides: int = 0


class PlanEntryIn(BaseModel):
    day_index: int  # 0 = lundi ... 6 = dimanche
    meal_type: str
    label: str
    calories: int
    proteines: int = 0
    glucides: int = 0
    lipides: int = 0
    week_index: int = 0
    recipe_id: str | None = None
    portions: float = 1.0


class PlanIn(BaseModel):
    plan_name: str = PLAN_NOM
    entries: list[PlanEntryIn]
    date_debut: str | None = None  # lundi de la semaine 0, 'YYYY-MM-DD'
    nb_personnes: int | None = None


class GenerationIn(BaseModel):
    """Réglages de génération. cible_kcal/cible_proteines sont optionnelles :
    sans elles, on reprend le budget du profil (Mifflin-St Jeor + activité +
    objectif de poids) et 1,8 g de protéines par kg."""
    semaines: int = 1
    avec_petit_dejeuner: bool = True
    avec_collation: bool = True
    max_repetitions_semaine: int = 2
    repetitions_entre_semaines: bool = True
    nb_personnes: int = 1
    cible_kcal: int | None = None
    cible_proteines: int | None = None
    # Grammes de protéines par kilo de poids de corps : 1,4 suffit en
    # maintien, 1,8 est le réglage par défaut, 2,2 vise une sèche ou une prise
    # de masse. Ignoré si cible_proteines est donnée directement.
    proteines_par_kg: float = 1.8
    graine: int | None = None


class PlanGenereIn(BaseModel):
    """Le plan renvoyé par /diet/plan/generate, tel quel, pour l'enregistrer."""
    plan_name: str = "Plan généré"
    semaines: list[dict]
    nb_personnes: int = 1
    date_debut: str | None = None


def _meals_calories_on(db: Session, user_id: str, date_dt) -> int:
    meals = db.query(models.Meal).filter(models.Meal.user_id == user_id).all()
    return sum(m.calories for m in meals if is_same_day(m.occurred_at, date_dt))


def _serialize_meal(m: models.Meal) -> dict:
    return {
        "id": m.id, "label": m.label, "calories": m.calories, "type": m.type,
        "occurredAt": to_ms(m.occurred_at),
        "type_label": MEAL_TYPE_LABEL.get(m.type, m.type),
        "relativeTime": relative_time(m.occurred_at),
        "proteines": m.proteines or 0,
        "glucides": m.glucides or 0,
        "lipides": m.lipides or 0,
    }


def _macros_totales(meals) -> dict:
    return {
        "proteines": sum(m.proteines or 0 for m in meals),
        "glucides": sum(m.glucides or 0 for m in meals),
        "lipides": sum(m.lipides or 0 for m in meals),
    }


def _semaine_courante(db: Session, user_id: str, profile: models.Profile | None,
                      aujourdhui) -> int:
    """Index de la semaine du plan à appliquer aujourd'hui.

    Un plan d'une seule semaine se répète (toujours 0). Un plan de plusieurs
    semaines tourne à partir de la date de début enregistrée dans le profil ;
    sans date de début, on reste sur la semaine 0."""
    nb_semaines = (db.query(func.max(models.MealPlanEntry.week_index))
                     .filter(models.MealPlanEntry.user_id == user_id)
                     .scalar())
    if not nb_semaines:
        return 0
    nb_semaines += 1
    debut = getattr(profile, "plan_start_date", None)
    if not debut:
        return 0
    try:
        depart = date.fromisoformat(debut)
    except ValueError:
        return 0
    semaines_ecoulees = (aujourdhui.date() - depart).days // 7
    return max(0, semaines_ecoulees) % nb_semaines


def _plan_du_jour(db: Session, user_id: str, day_index: int,
                  week_index: int = 0) -> tuple[str, str, list[dict]]:
    """Repas prévus ce jour-là : le plan enregistré dans le compte s'il existe,
    sinon la semaine type livrée avec l'app (models.MealPlanEntry vs
    plan_alimentation.SEMAINE_TYPE). Renvoie (nom du plan, origine, repas)."""
    entries = (
        db.query(models.MealPlanEntry)
        .filter(models.MealPlanEntry.user_id == user_id,
                models.MealPlanEntry.day_index == day_index,
                models.MealPlanEntry.week_index == week_index)
        .all()
    )
    if entries:
        nom = entries[0].plan_name
        repas = [
            {
                "id": e.id, "type": e.meal_type, "label": e.label, "calories": e.calories,
                "proteines": e.proteines or 0, "glucides": e.glucides or 0,
                "lipides": e.lipides or 0,
                "recipe_id": e.recipe_id, "portions": e.portions or 1,
            }
            for e in entries
        ]
        origine = "compte"
    else:
        repas = [
            {
                # Identifiant stable du repli : pas de ligne en base à pointer,
                # mais /plan/{id}/log doit pouvoir le retrouver.
                "id": f"modele-{day_index}-{meal_type}",
                "type": meal_type, "label": label, "calories": kcal,
                "proteines": p, "glucides": g, "lipides": l,
            }
            for meal_type, label, kcal, p, g, l in SEMAINE_TYPE.get(day_index, [])
        ]
        nom, origine = PLAN_NOM, "modele"

    ordre = {t: i for i, t in enumerate(MEAL_TYPE_ORDER)}
    repas.sort(key=lambda r: ordre.get(r["type"], len(MEAL_TYPE_ORDER)))
    for r in repas:
        r["type_label"] = MEAL_TYPE_LABEL.get(r["type"], r["type"])
    return nom, origine, repas


def _totaux(repas: list[dict]) -> dict:
    return {
        "calories": sum(r["calories"] for r in repas),
        "proteines": sum(r["proteines"] for r in repas),
        "glucides": sum(r["glucides"] for r in repas),
        "lipides": sum(r["lipides"] for r in repas),
    }


@router.get("")
def get_diet(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    profile = _get_or_create_profile(db, user)
    now = now_utc()

    all_meals = (
        db.query(models.Meal)
        .filter(models.Meal.user_id == user.id)
        .order_by(models.Meal.occurred_at.desc())
        .all()
    )
    meals_today = [m for m in all_meals if is_same_day(m.occurred_at, now)]
    consumed_today = sum(m.calories for m in meals_today)
    burned_today = calories_burned_on(db, user.id, now)
    net_today = consumed_today - burned_today

    semaine = _semaine_courante(db, user.id, profile, now)
    _, _, repas_prevus = _plan_du_jour(db, user.id, now.weekday(), semaine)

    return {
        "budget": profile.daily_calorie_budget,
        "consumed_today": consumed_today,
        "burned_today": burned_today,
        "net_today": net_today,
        "remaining_today": profile.daily_calorie_budget - net_today,
        "meals_today": [_serialize_meal(m) for m in meals_today],
        "recent_meals": [_serialize_meal(m) for m in all_meals[:15]],
        # Macros consommées aujourd'hui et cibles du plan du jour (voir
        # GET /diet/plan pour le détail repas par repas).
        "macros_today": _macros_totales(meals_today),
        "macros_target": {k: v for k, v in _totaux(repas_prevus).items() if k != "calories"},
    }


@router.post("/meals", status_code=201)
def add_meal(
    payload: MealCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    db.add(models.Meal(
        user_id=user.id, label=payload.label, calories=payload.calories, type=payload.type,
        occurred_at=now_utc(),
        proteines=payload.proteines, glucides=payload.glucides, lipides=payload.lipides,
    ))
    db.commit()
    return {"ok": True}


@router.get("/plan")
def get_plan(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Les repas prévus aujourd'hui par le plan d'alimentation, et ce qui en a
    déjà été journalisé (un repas prévu compte comme pris dès qu'un repas du
    même libellé est enregistré dans la journée)."""
    now = now_utc()
    day_index = now.weekday()
    profile = _get_or_create_profile(db, user)
    semaine = _semaine_courante(db, user.id, profile, now)
    nom, origine, repas = _plan_du_jour(db, user.id, day_index, semaine)

    meals = db.query(models.Meal).filter(models.Meal.user_id == user.id).all()
    libelles_du_jour = {m.label for m in meals if is_same_day(m.occurred_at, now)}
    for r in repas:
        r["logged"] = r["label"] in libelles_du_jour

    return {
        "plan_name": nom,
        "source": origine,
        "day_index": day_index,
        "day_label": JOURS[day_index],
        "week_index": semaine,
        "meals": repas,
        "totals": _totaux(repas),
    }


@router.get("/plan/week")
def get_plan_week(semaine: int | None = None, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    """Une semaine complète du plan. Par défaut celle en cours."""
    profile = _get_or_create_profile(db, user)
    if semaine is None:
        semaine = _semaine_courante(db, user.id, profile, now_utc())
    jours, noms, origines = [], set(), set()
    for day_index in range(7):
        nom, origine, repas = _plan_du_jour(db, user.id, day_index, semaine)
        noms.add(nom)
        origines.add(origine)
        jours.append({
            "day_index": day_index, "day_label": JOURS[day_index],
            "meals": repas, "totals": _totaux(repas),
        })
    # "compte" seulement si toute la semaine vient du plan importé : un plan
    # partiel retombe sur la semaine type pour les jours manquants.
    origine = "compte" if origines == {"compte"} else "modele"
    nb_semaines = (db.query(func.max(models.MealPlanEntry.week_index))
                     .filter(models.MealPlanEntry.user_id == user.id).scalar())
    return {
        "plan_name": sorted(noms)[0] if noms else PLAN_NOM,
        "source": origine,
        "week_index": semaine,
        "nb_semaines": (nb_semaines or 0) + 1,
        "days": jours,
    }


@router.post("/plan/{entry_id}/log", status_code=201)
def log_plan_meal(
    entry_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Journalise un repas prévu : calories ET macros sont reprises du plan,
    inutile de les ressaisir."""
    entry = (
        db.query(models.MealPlanEntry)
        .filter(models.MealPlanEntry.id == entry_id,
                models.MealPlanEntry.user_id == user.id)
        .first()
    )
    if entry is not None:
        repas = {
            "type": entry.meal_type, "label": entry.label, "calories": entry.calories,
            "proteines": entry.proteines or 0, "glucides": entry.glucides or 0,
            "lipides": entry.lipides or 0,
        }
    else:
        # Repli : identifiant "modele-{jour}-{type}" de la semaine type livrée
        # avec l'app, quand aucun plan n'a été importé dans le compte.
        repas = None
        if entry_id.startswith("modele-"):
            _, jour, meal_type = entry_id.split("-", 2)
            for t, label, kcal, p, g, l in SEMAINE_TYPE.get(int(jour), []):
                if t == meal_type:
                    repas = {"type": t, "label": label, "calories": kcal,
                             "proteines": p, "glucides": g, "lipides": l}
                    break
        if repas is None:
            raise HTTPException(status_code=404, detail="Repas du plan introuvable.")

    db.add(models.Meal(
        user_id=user.id, label=repas["label"], calories=repas["calories"], type=repas["type"],
        occurred_at=now_utc(),
        proteines=repas["proteines"], glucides=repas["glucides"], lipides=repas["lipides"],
    ))
    db.commit()
    return {"ok": True, "meal": repas}


@router.put("/plan")
def replace_plan(
    payload: PlanIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Remplace en bloc le plan de l'utilisateur (appelé par
    importer_alimentation.py). Une liste vide efface le plan et fait
    retomber l'app sur la semaine type livrée avec elle."""
    for e in payload.entries:
        if not 0 <= e.day_index <= 6:
            raise HTTPException(status_code=422, detail=f"day_index hors semaine : {e.day_index}")
        if e.meal_type not in MEAL_TYPE_LABEL:
            raise HTTPException(status_code=422, detail=f"Type de repas inconnu : {e.meal_type}")

    profile = _get_or_create_profile(db, user)
    (db.query(models.MealPlanEntry)
       .filter(models.MealPlanEntry.user_id == user.id)
       .delete(synchronize_session=False))
    for e in payload.entries:
        db.add(models.MealPlanEntry(
            user_id=user.id, plan_name=payload.plan_name, day_index=e.day_index,
            week_index=e.week_index, meal_type=e.meal_type, label=e.label,
            recipe_id=e.recipe_id, portions=e.portions, calories=e.calories,
            proteines=e.proteines, glucides=e.glucides, lipides=e.lipides,
        ))
    profile.plan_start_date = payload.date_debut or _lundi_de_la_semaine()
    if payload.nb_personnes:
        profile.plan_persons = payload.nb_personnes
    db.commit()
    return {"ok": True, "count": len(payload.entries), "plan_name": payload.plan_name}


def _lundi_de_la_semaine() -> str:
    aujourdhui = now_utc().date()
    return (aujourdhui - timedelta(days=aujourdhui.weekday())).isoformat()


def _cibles(db: Session, user: models.User, payload: GenerationIn) -> tuple[int, int]:
    """Cible calorique et protéique de la journée.

    Par défaut : le budget calculé depuis le profil (Mifflin-St Jeor, activité,
    objectif de poids) ou, à défaut, le budget saisi ; et `proteines_par_kg`
    grammes de protéines par kilo de poids (1,8 par défaut). Sans pesée
    enregistrée, on retient 75 kg plutôt que de refuser de générer."""
    profile = _get_or_create_profile(db, user)
    poids = _current_weight_kg(db, user)
    cible_kcal = (payload.cible_kcal
                  or _suggested_calorie_budget(profile, poids)
                  or profile.daily_calorie_budget)
    par_kg = payload.proteines_par_kg or 1.8
    cible_proteines = payload.cible_proteines or round(par_kg * (poids or 75))
    return int(cible_kcal), int(cible_proteines)


@router.post("/plan/generate")
def generate_plan(
    payload: GenerationIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Propose un plan à partir du catalogue de recettes. **N'enregistre rien** :
    l'app affiche la proposition, l'utilisateur valide, puis POST /diet/plan/apply."""
    cible_kcal, cible_proteines = _cibles(db, user, payload)
    try:
        plan = generer_plan(
            cible_kcal=cible_kcal,
            cible_proteines=cible_proteines,
            nb_semaines=payload.semaines,
            avec_petit_dejeuner=payload.avec_petit_dejeuner,
            avec_collation=payload.avec_collation,
            max_repetitions_semaine=payload.max_repetitions_semaine,
            repetitions_entre_semaines=payload.repetitions_entre_semaines,
            graine=payload.graine,
        )
    except ValueError as erreur:
        raise HTTPException(status_code=422, detail=str(erreur))

    for semaine in plan["semaines"]:
        for jour in semaine["jours"]:
            jour["day_label"] = JOURS[jour["day_index"]]
            for repas in jour["repas"]:
                repas["type_label"] = MEAL_TYPE_LABEL.get(repas["meal_type"], repas["meal_type"])
    plan["nb_personnes"] = payload.nb_personnes
    return plan


@router.post("/plan/apply")
def apply_plan(
    payload: PlanGenereIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Enregistre un plan généré (remplace le précédent)."""
    profile = _get_or_create_profile(db, user)
    (db.query(models.MealPlanEntry)
       .filter(models.MealPlanEntry.user_id == user.id)
       .delete(synchronize_session=False))

    nombre = 0
    for semaine in payload.semaines:
        for jour in semaine.get("jours", []):
            for repas in jour.get("repas", []):
                db.add(models.MealPlanEntry(
                    user_id=user.id,
                    plan_name=payload.plan_name,
                    week_index=semaine.get("week_index", 0),
                    day_index=jour["day_index"],
                    meal_type=repas["meal_type"],
                    label=repas["label"],
                    recipe_id=repas.get("recipe_id"),
                    portions=repas.get("portions", 1),
                    calories=repas["calories"],
                    proteines=repas.get("proteines", 0),
                    glucides=repas.get("glucides", 0),
                    lipides=repas.get("lipides", 0),
                ))
                nombre += 1
    if not nombre:
        raise HTTPException(status_code=422, detail="Plan vide : rien à enregistrer.")

    profile.plan_start_date = payload.date_debut or _lundi_de_la_semaine()
    profile.plan_persons = payload.nb_personnes or 1
    db.commit()
    return {"ok": True, "count": nombre, "plan_name": payload.plan_name,
            "date_debut": profile.plan_start_date}


@router.get("/plan/shopping-list")
def get_shopping_list(
    semaine: int | None = None,
    nb_personnes: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Liste de courses d'une semaine du plan, groupée par rayon.

    Seuls les repas venant d'une recette du catalogue sont décomposables en
    ingrédients ; les autres sont listés dans `repas_sans_recette`."""
    profile = _get_or_create_profile(db, user)
    if semaine is None:
        semaine = _semaine_courante(db, user.id, profile, now_utc())

    entries = (
        db.query(models.MealPlanEntry)
        .filter(models.MealPlanEntry.user_id == user.id,
                models.MealPlanEntry.week_index == semaine)
        .all()
    )
    repas = [{"recipe_id": e.recipe_id, "portions": e.portions or 1, "label": e.label}
             for e in entries]
    resultat = liste_de_courses(repas, nb_personnes or profile.plan_persons or 1)
    resultat["week_index"] = semaine
    return resultat
