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
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/recipes", tags=["recipes"])

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
