"""Recherche de recettes réelles (ingrédients avec quantités + étapes de
préparation) via TheMealDB — vérifié à jour en juillet 2026.

STATUT : endpoints vérifiés dans la documentation officielle
(themealdb.com/api.php), structurellement corrects, mais pas testés en
conditions réelles dans cet environnement (pas d'accès réseau).

IMPORTANT — à savoir avant de publier l'app :
La clé de test "1" utilisée ici est gratuite mais réservée au
développement. TheMealDB l'indique explicitement : "you must become a
supporter if releasing publicly on an appstore." Avant de publier sur le
Play Store, il faudra devenir "supporter" (offre payante ponctuelle via
PayPal, voir https://www.themealdb.com/api.php) et remplacer MEALDB_API_KEY
par la vraie clé obtenue.

Limite connue : TheMealDB ne fournit pas de données caloriques — cette
recherche n'est donc PAS filtrable par "kcal restantes" comme les 18
recettes internes déjà en place (voir mockData.js côté app). Les deux
cohabitent : les recettes internes pour le filtre calorique, TheMealDB
pour une vraie base externe avec quantités précises et étapes détaillées.
"""
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..plan_alimentation import JOURS, SEMAINE_TYPE
from ..services.common import now_utc, is_same_day
from ..services.sport import calories_burned_on
from .profile import _get_or_create_profile

router = APIRouter(prefix="/recipes", tags=["recipes"])

# Catalogue interne — statique, filtrable par kcal restantes (contrairement
# à TheMealDB ci-dessous, qui ne fournit pas de données caloriques). Mêmes
# 18 recettes que mockData.js/RECIPES.
INTERNAL_RECIPES = [
    {"id": "r1", "label": "Omelette aux légumes", "mealType": "petit-dejeuner", "kcal": 320, "ingredients": "Œufs, poivron, épinards, fromage"},
    {"id": "r2", "label": "Porridge avoine-banane", "mealType": "petit-dejeuner", "kcal": 380, "ingredients": "Flocons d’avoine, lait, banane, miel"},
    {"id": "r3", "label": "Yaourt grec, granola, fruits rouges", "mealType": "petit-dejeuner", "kcal": 290, "ingredients": "Yaourt grec, granola, fruits rouges"},
    {"id": "r4", "label": "Tartines avocat-œuf poché", "mealType": "petit-dejeuner", "kcal": 410, "ingredients": "Pain complet, avocat, œuf"},
    {"id": "r5", "label": "Salade de poulet grillé", "mealType": "dejeuner", "kcal": 450, "ingredients": "Blanc de poulet, salade verte, tomates, vinaigrette légère"},
    {"id": "r6", "label": "Bol de riz sauté aux légumes et tofu", "mealType": "dejeuner", "kcal": 520, "ingredients": "Riz, tofu, brocolis, carottes, sauce soja"},
    {"id": "r7", "label": "Wrap dinde-crudités", "mealType": "dejeuner", "kcal": 470, "ingredients": "Tortilla, dinde, salade, tomate, sauce yaourt"},
    {"id": "r8", "label": "Pâtes complètes au pesto et courgettes", "mealType": "dejeuner", "kcal": 560, "ingredients": "Pâtes complètes, pesto, courgettes grillées"},
    {"id": "r9", "label": "Poke bowl saumon", "mealType": "dejeuner", "kcal": 540, "ingredients": "Riz, saumon, avocat, edamame, sauce soja"},
    {"id": "r10", "label": "Soupe de légumes maison", "mealType": "diner", "kcal": 220, "ingredients": "Carottes, poireaux, pommes de terre, bouillon"},
    {"id": "r11", "label": "Filet de poisson vapeur, légumes verts", "mealType": "diner", "kcal": 380, "ingredients": "Cabillaud, brocolis, haricots verts, citron"},
    {"id": "r12", "label": "Curry de légumes au lait de coco", "mealType": "diner", "kcal": 490, "ingredients": "Pois chiches, légumes de saison, lait de coco, riz"},
    {"id": "r13", "label": "Omelette légère et salade", "mealType": "diner", "kcal": 310, "ingredients": "Œufs, salade verte, tomates cerises"},
    {"id": "r14", "label": "Steak haché 5%, purée de patate douce", "mealType": "diner", "kcal": 470, "ingredients": "Steak haché maigre, patate douce, haricots verts"},
    {"id": "r15", "label": "Pomme et amandes", "mealType": "collation", "kcal": 180, "ingredients": "Pomme, une poignée d’amandes"},
    {"id": "r16", "label": "Fromage blanc et miel", "mealType": "collation", "kcal": 150, "ingredients": "Fromage blanc 0-20%, miel"},
    {"id": "r17", "label": "Barre de céréales maison", "mealType": "collation", "kcal": 200, "ingredients": "Flocons d’avoine, miel, fruits secs"},
    {"id": "r18", "label": "Smoothie fruits rouges", "mealType": "collation", "kcal": 170, "ingredients": "Fruits rouges surgelés, lait, banane"},
]
RECIPE_MEAL_TYPE_LABEL = {
    "petit-dejeuner": "Petit-déjeuner", "dejeuner": "Déjeuner", "diner": "Dîner", "collation": "Collation",
}


def _recettes_du_plan() -> list[dict]:
    """Les repas de la semaine type d'alimentation, ajoutés au catalogue pour
    pouvoir les choisir hors du jour prévu. Dédoublonnés par libellé (le même
    repas revient plusieurs fois dans la semaine) et enrichis des macros, que
    les 18 recettes historiques ci-dessus n'ont pas."""
    vus, recettes = set(), []
    for day_index, repas in sorted(SEMAINE_TYPE.items()):
        for meal_type, label, kcal, p, g, l in repas:
            if label in vus:
                continue
            vus.add(label)
            recettes.append({
                "id": f"plan-{day_index}-{meal_type}",
                "label": label,
                "mealType": meal_type,
                "kcal": kcal,
                "ingredients": label,
                "source": "plan",
                "day_label": JOURS[day_index],
                "proteines": p, "glucides": g, "lipides": l,
            })
    return recettes


INTERNAL_RECIPES = INTERNAL_RECIPES + _recettes_du_plan()

MEALDB_BASE_URL = "https://www.themealdb.com/api/json/v1"


def _api_key() -> str:
    # "1" = clé de test publique de TheMealDB, gratuite mais non autorisée
    # pour une app publiée sur un app store (voir avertissement en haut).
    return os.environ.get("MEALDB_API_KEY", "1")


class RecipeSummary(BaseModel):
    id: str
    name: str
    category: str | None
    area: str | None
    thumbnail: str | None


class RecipeDetail(BaseModel):
    id: str
    name: str
    category: str | None
    area: str | None
    thumbnail: str | None
    youtube_url: str | None
    ingredients: list[str]  # ex. "200g de riz", déjà combiné quantité + nom
    instructions_steps: list[str]


def _meal_to_summary(meal: dict) -> RecipeSummary:
    return RecipeSummary(
        id=meal["idMeal"],
        name=meal["strMeal"],
        category=meal.get("strCategory"),
        area=meal.get("strArea"),
        thumbnail=meal.get("strMealThumb"),
    )


def _meal_to_detail(meal: dict) -> RecipeDetail:
    ingredients = []
    for i in range(1, 21):
        name = (meal.get(f"strIngredient{i}") or "").strip()
        measure = (meal.get(f"strMeasure{i}") or "").strip()
        if not name:
            continue
        ingredients.append(f"{measure} {name}".strip() if measure else name)

    raw_instructions = meal.get("strInstructions") or ""
    # TheMealDB renvoie un bloc de texte, parfois numéroté, parfois juste
    # séparé par des retours à la ligne — on découpe au mieux plutôt que
    # d'afficher un pavé de texte brut.
    steps = [s.strip() for s in raw_instructions.replace("\r\n", "\n").split("\n") if s.strip()]

    return RecipeDetail(
        id=meal["idMeal"],
        name=meal["strMeal"],
        category=meal.get("strCategory"),
        area=meal.get("strArea"),
        thumbnail=meal.get("strMealThumb"),
        youtube_url=meal.get("strYoutube") or None,
        ingredients=ingredients,
        instructions_steps=steps,
    )


@router.get("/catalog")
def get_recipe_catalog(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    profile = _get_or_create_profile(db, user)
    now = now_utc()
    meals = db.query(models.Meal).filter(models.Meal.user_id == user.id).all()
    consumed_today = sum(m.calories for m in meals if is_same_day(m.occurred_at, now))
    burned_today = calories_burned_on(db, user.id, now)
    remaining_kcal = profile.daily_calorie_budget - (consumed_today - burned_today)

    recipes = sorted(
        [
            {
                **r,
                "meal_type_label": RECIPE_MEAL_TYPE_LABEL.get(r["mealType"], r["mealType"]),
                "fits_remaining": r["kcal"] <= remaining_kcal,
            }
            for r in INTERNAL_RECIPES
        ],
        key=lambda r: r["kcal"],
    )
    return {"remaining_kcal": remaining_kcal, "recipes": recipes}


@router.get("/search-external", response_model=list[RecipeSummary])
async def search_external(query: str = Query(..., min_length=2)):
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{MEALDB_BASE_URL}/{_api_key()}/search.php", params={"s": query})
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de la recherche TheMealDB : {resp.text}")
    meals = resp.json().get("meals") or []
    return [_meal_to_summary(m) for m in meals]


@router.get("/external/{meal_id}", response_model=RecipeDetail)
async def get_external_detail(meal_id: str):
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{MEALDB_BASE_URL}/{_api_key()}/lookup.php", params={"i": meal_id})
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de la récupération TheMealDB : {resp.text}")
    meals = resp.json().get("meals") or []
    if not meals:
        raise HTTPException(status_code=404, detail="Recette introuvable.")
    return _meal_to_detail(meals[0])


@router.get("/external-random", response_model=RecipeDetail)
async def get_random_external():
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{MEALDB_BASE_URL}/{_api_key()}/random.php")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec TheMealDB : {resp.text}")
    meals = resp.json().get("meals") or []
    if not meals:
        raise HTTPException(status_code=502, detail="Réponse TheMealDB inattendue.")
    return _meal_to_detail(meals[0])
