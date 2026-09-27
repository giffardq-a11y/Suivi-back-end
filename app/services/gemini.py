"""Appel Gemini tolérant à la surcharge.

Google répond 503 (« high demand ») ou 429 quand un modèle est saturé. On
réessaie une fois après une courte pause, puis on passe au modèle suivant :
GEMINI_MODEL (variable Render) d'abord, puis des modèles de repli.
"""
import asyncio
import os

import httpx

REPLIS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]
SURCHARGE = {429, 500, 503}


def modeles() -> list[str]:
    choisi = os.environ.get("GEMINI_MODEL")
    return ([choisi] if choisi else []) + [m for m in REPLIS if m != choisi]


async def generer(client: httpx.AsyncClient, cle_api: str, corps: dict) -> httpx.Response:
    """Renvoie la première réponse 200, sinon la dernière réponse reçue."""
    resp = None
    for modele in modeles():
        for essai in range(2):
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent",
                headers={"x-goog-api-key": cle_api, "Content-Type": "application/json"},
                json=corps,
            )
            if resp.status_code not in SURCHARGE:
                break
            if essai == 0:
                await asyncio.sleep(1.5)
        if resp.status_code == 200 or resp.status_code not in SURCHARGE | {404}:
            return resp
    return resp
