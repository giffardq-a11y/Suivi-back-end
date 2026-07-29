"""Recherche d'aliments dans la base USDA FoodData Central (FDC) —
alternative gratuite à Nutritionix (qui a supprimé son offre gratuite,
vérifié en juillet 2026 : leur documentation renvoie désormais une erreur
402 Paiement requis).

Contrairement à un "import" depuis une app tierce (ce que faisait
MyFitnessPal, dont l'API est fermée aux nouveaux développeurs), ceci est
une recherche dans une base nutritionnelle ouverte : l'utilisateur tape
le nom d'un aliment, choisit le bon résultat, les calories se remplissent
automatiquement. Ça ne récupère pas un journal existant, mais ça rend la
saisie manuelle d'un repas beaucoup plus rapide et fiable qu'un chiffre
tapé à l'estime.

STATUT : structurellement correct (endpoints et format de réponse vérifiés
dans la documentation officielle, à jour), mais pas testé en conditions
réelles — pas d'accès réseau dans l'environnement où ce projet a été
généré. Le format exact de `foodNutrients` sur l'endpoint /search a pu
évoluer légèrement ; `_extract_calories` gère les deux variantes connues,
mais vérifie avec un vrai appel si le résultat semble faux.

Pour l'activer :
1. Va sur https://fdc.nal.usda.gov/api-key-signup.html (gratuit, aucune
   carte bancaire, confirmation par email en quelques minutes)
2. FDC_API_KEY=<ta clé> dans backend/.env
   (à défaut, "DEMO_KEY" fonctionne pour tester mais avec une limite de
   débit plus basse que ta propre clé — jamais recommandé au-delà du test)

Limite de débit avec ta propre clé : 1000 appels/heure par adresse IP —
largement suffisant pour un usage personnel.
"""
import os

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/foods", tags=["foods"])

FDC_BASE_URL = "https://api.nal.usda.gov/fdc/v1"


class FoodSearchResult(BaseModel):
    fdc_id: int
    name: str
    calories: int | None
    serving_description: str | None


def _extract_calories(food_nutrients: list) -> int | None:
    """Cherche l'énergie en kcal (nutrientId USDA 1008) dans la liste de
    nutriments — gère les deux formats de réponse connus de l'API FDC
    (search vs food/{id})."""
    for n in food_nutrients:
        nutrient_id = n.get("nutrientId") or n.get("nutrient", {}).get("id")
        unit = (n.get("unitName") or n.get("nutrient", {}).get("unitName") or "").upper()
        if nutrient_id == 1008 and unit == "KCAL":
            value = n.get("value", n.get("amount"))
            if value is not None:
                return round(value)
    return None


@router.get("/search", response_model=list[FoodSearchResult])
async def search_foods(query: str = Query(..., min_length=2), max_results: int = Query(8, ge=1, le=20)):
    api_key = os.environ.get("FDC_API_KEY", "DEMO_KEY")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{FDC_BASE_URL}/foods/search",
            params={"query": query, "api_key": api_key, "pageSize": max_results},
        )
    if resp.status_code == 403:
        raise HTTPException(
            status_code=501,
            detail="Clé FDC_API_KEY invalide ou manquante — voir les instructions en haut de app/routers/food_search.py.",
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de la recherche USDA FoodData Central : {resp.text}")

    data = resp.json()
    results = []
    for food in data.get("foods", []):
        serving = None
        if food.get("servingSize") and food.get("servingSizeUnit"):
            serving = f"{food['servingSize']} {food['servingSizeUnit']}"
        results.append(FoodSearchResult(
            fdc_id=food["fdcId"],
            name=food.get("description", "Aliment sans nom"),
            calories=_extract_calories(food.get("foodNutrients", [])),
            serving_description=serving,
        ))
    return results
