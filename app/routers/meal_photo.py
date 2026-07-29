"""Estimation de calories d'un repas à partir d'une photo — deux fournisseurs
au choix, proposés à l'utilisateur dans l'app (écran Paramètres) :

- "gemini_fatsecret" (natif, par défaut) : combo gratuite — Gemini API
  (Google, gratuit pour l'analyse d'image) identifie le plat, puis
  FatSecret Platform API (Basic, gratuit en auto-inscription, 5000
  appels/jour) cherche ses calories. Activée pour tout le monde par
  défaut, sans configuration ni abonnement demandé à l'utilisateur.
- "logmeal" (au choix, option "précision supérieure") : LogMeal API,
  service spécialisé en reconnaissance alimentaire. Plus précis sur les
  plats composés, mais payant au-delà de l'essai gratuit — dans l'app,
  ce choix s'accompagne d'un rappel des limites et d'un lien vers les
  tarifs LogMeal (voir SettingsScreen.js côté mobile).

STATUT : les deux intégrations sont structurellement correctes (endpoints,
authentification et enchaînement vérifiés dans la documentation officielle
de chaque service, à jour en juillet 2026), mais PAS testées en conditions
réelles — pas d'accès réseau ni de clés API dans l'environnement où ce
projet a été généré.

Le fournisseur utilisé se choisit via la variable d'environnement
MEAL_PHOTO_PROVIDER ("gemini_fatsecret" ou "logmeal", "gemini_fatsecret"
par défaut), ou en surchargeant au cas par cas avec ?provider=... sur
l'appel — c'est ce que fait l'app mobile selon la préférence choisie par
l'utilisateur dans Paramètres.

=== Activer Gemini + FatSecret (déjà le défaut) ===
1. Gemini : crée une clé sur https://aistudio.google.com/apikey (gratuit)
   → GEMINI_API_KEY=<la clé> dans backend/.env
2. FatSecret : inscription développeur sur https://platform.fatsecret.com/register
   (édition "Basic", gratuite, auto-inscription, 5000 appels/jour)
   → récupère Client ID et Client Secret dans ton tableau de bord
   → FATSECRET_CLIENT_ID=... et FATSECRET_CLIENT_SECRET=... dans backend/.env

=== Activer LogMeal (option payante) ===
1. Crée un compte sur https://logmeal.com/signup/form?next=/signup/plan
2. Récupère le token "APIUser" de test sur https://www.logmeal.com/api/users
3. LOGMEAL_API_KEY=<ce token> dans backend/.env

Limite connue de la combo gratuite : FatSecret cherche le plat par son nom
(texte), donc la qualité du résultat dépend de la formulation renvoyée par
Gemini — moins fiable que LogMeal sur des plats composés ou peu communs.
C'est précisément pour ça que LogMeal reste proposé comme option "précision
supérieure" plutôt que d'être retiré.
"""
import base64
import os

import httpx
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/meals", tags=["meals"])


class MealPhotoEstimate(BaseModel):
    label: str
    calories: int
    confidence: float | None = None
    provider: str


# ---------- LogMeal ----------

LOGMEAL_BASE_URL = "https://api.logmeal.com/v2"


def _extract_logmeal_calories(nutritional_info: dict) -> int:
    """TODO à vérifier avec un vrai appel — voir le même avertissement que
    dans les versions précédentes de ce fichier : le nom exact du champ
    d'énergie n'a pas pu être confirmé sans y être connecté. Se référer à
    l'exemple "Nutritional Info Example" sur
    https://docs.logmeal.com/reference/post_v2-nutrition-recipe-nutritionalinfo
    """
    energy = nutritional_info.get("ENERC_KCAL") or nutritional_info.get("energy") or nutritional_info.get("calories")
    if isinstance(energy, dict):
        return round(energy.get("quantity", 0))
    if isinstance(energy, (int, float)):
        return round(energy)
    raise HTTPException(status_code=502, detail="Réponse LogMeal inattendue : impossible de trouver la valeur calorique.")


async def _estimate_via_logmeal(image_bytes: bytes, filename: str, content_type: str) -> MealPhotoEstimate:
    api_key = os.environ.get("LOGMEAL_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=501,
            detail="LogMeal pas configuré côté serveur : variable LOGMEAL_API_KEY manquante (voir le haut de ce fichier).",
        )

    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=30) as client:
        recognition = await client.post(
            f"{LOGMEAL_BASE_URL}/image/segmentation/complete",
            headers=headers,
            files={"image": (filename, image_bytes, content_type)},
            params={"language": "fre"},
        )
        if recognition.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Échec de la reconnaissance LogMeal : {recognition.text}")

        recognition_data = recognition.json()
        image_id = recognition_data.get("imageId")
        if not image_id:
            raise HTTPException(status_code=502, detail="Réponse LogMeal inattendue : imageId manquant.")

        best_label = "Plat non identifié"
        best_confidence = None
        for item in recognition_data.get("segmentation_results", []):
            for candidate in item.get("recognition_results", []):
                if best_confidence is None or candidate.get("prob", 0) > best_confidence:
                    best_label = candidate.get("name", best_label)
                    best_confidence = candidate.get("prob")

        nutrition = await client.post(
            f"{LOGMEAL_BASE_URL}/nutrition/recipe/nutritionalInfo",
            headers=headers,
            json={"imageId": image_id},
        )
        if nutrition.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Échec de la récupération nutritionnelle LogMeal : {nutrition.text}")

        nutrition_data = nutrition.json()
        if not nutrition_data.get("hasNutritionalInfo", True):
            raise HTTPException(status_code=422, detail="LogMeal n'a pas trouvé d'information nutritionnelle pour ce plat.")

        calories = _extract_logmeal_calories(nutrition_data.get("nutritional_info", {}))

    return MealPhotoEstimate(label=best_label, calories=calories, confidence=best_confidence, provider="logmeal")


# ---------- Gemini (reconnaissance) + FatSecret (calories) ----------

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


async def _identify_dish_with_gemini(image_bytes: bytes, mime_type: str, client: httpx.AsyncClient) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=501, detail="Gemini pas configuré côté serveur : variable GEMINI_API_KEY manquante.")

    b64_image = base64.b64encode(image_bytes).decode()
    resp = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": b64_image}},
                    {"text": "Identifie le plat principal sur cette photo. Réponds uniquement par son nom (2 à 4 mots), sans phrase ni ponctuation."},
                ]
            }]
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de la reconnaissance Gemini : {resp.text}")

    try:
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="Réponse Gemini inattendue : impossible d'extraire le nom du plat.")


async def _get_fatsecret_token(client: httpx.AsyncClient) -> str:
    client_id = os.environ.get("FATSECRET_CLIENT_ID")
    client_secret = os.environ.get("FATSECRET_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=501,
            detail="FatSecret pas configuré côté serveur : FATSECRET_CLIENT_ID / FATSECRET_CLIENT_SECRET manquants.",
        )

    # NOTE production : ce token est valable un moment (voir expires_in
    # dans la réponse) — le mettre en cache plutôt que de le redemander à
    # chaque appel. Simplifié ici pour la clarté du scaffold.
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = await client.post(
        "https://oauth.fatsecret.com/connect/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "basic"},
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec d'authentification FatSecret : {resp.text}")
    return resp.json()["access_token"]


async def _lookup_calories_with_fatsecret(dish_name: str, client: httpx.AsyncClient) -> tuple[int, str]:
    token = await _get_fatsecret_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    search = await client.get(
        "https://platform.fatsecret.com/rest/server.api",
        headers=headers,
        params={"method": "foods.search", "search_expression": dish_name, "format": "json", "max_results": 1},
    )
    if search.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de la recherche FatSecret : {search.text}")

    results = search.json().get("foods", {}).get("food")
    if not results:
        raise HTTPException(status_code=422, detail=f"Aucun résultat FatSecret pour \u00ab {dish_name} \u00bb.")
    first = results[0] if isinstance(results, list) else results
    food_id = first["food_id"]
    matched_name = first.get("food_name", dish_name)

    detail_resp = await client.get(
        "https://platform.fatsecret.com/rest/server.api",
        headers=headers,
        params={"method": "food.get.v4", "food_id": food_id, "format": "json"},
    )
    if detail_resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de la fiche FatSecret : {detail_resp.text}")

    servings = detail_resp.json().get("food", {}).get("servings", {}).get("serving")
    serving = servings[0] if isinstance(servings, list) else servings
    if not serving or "calories" not in serving:
        raise HTTPException(status_code=422, detail=f"Pas d'information calorique FatSecret pour \u00ab {dish_name} \u00bb.")

    return round(float(serving["calories"])), matched_name


async def _estimate_via_gemini_fatsecret(image_bytes: bytes, content_type: str) -> MealPhotoEstimate:
    async with httpx.AsyncClient(timeout=30) as client:
        dish_name = await _identify_dish_with_gemini(image_bytes, content_type or "image/jpeg", client)
        calories, matched_name = await _lookup_calories_with_fatsecret(dish_name, client)
    return MealPhotoEstimate(label=matched_name, calories=calories, confidence=None, provider="gemini_fatsecret")


# ---------- Endpoint ----------

DEFAULT_PROVIDER = os.environ.get("MEAL_PHOTO_PROVIDER", "gemini_fatsecret")
VALID_PROVIDERS = {"logmeal", "gemini_fatsecret"}


@router.post("/estimate-from-photo", response_model=MealPhotoEstimate)
async def estimate_from_photo(photo: UploadFile = File(...), provider: str | None = Query(None)):
    chosen = provider or DEFAULT_PROVIDER
    if chosen not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Fournisseur inconnu : {chosen}. Options : {sorted(VALID_PROVIDERS)}")

    image_bytes = await photo.read()

    if chosen == "logmeal":
        return await _estimate_via_logmeal(image_bytes, photo.filename or "meal.jpg", photo.content_type or "image/jpeg")
    return await _estimate_via_gemini_fatsecret(image_bytes, photo.content_type or "image/jpeg")
