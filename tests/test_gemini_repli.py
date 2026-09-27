"""Repli Gemini : un modèle saturé (503) ou retiré (404) passe au suivant."""
import asyncio

import httpx

from app.services import gemini


def _client(statuts: dict[str, int], appels: list[str]) -> httpx.AsyncClient:
    def repondre(requete: httpx.Request) -> httpx.Response:
        modele = requete.url.path.split("/models/")[1].split(":")[0]
        appels.append(modele)
        return httpx.Response(statuts.get(modele, 200), json={"ok": modele})
    return httpx.AsyncClient(transport=httpx.MockTransport(repondre))


def _lancer(statuts, monkeypatch, modele_env=None):
    async def sans_pause(_s):
        return None
    monkeypatch.setattr(gemini.asyncio, "sleep", sans_pause)
    if modele_env:
        monkeypatch.setenv("GEMINI_MODEL", modele_env)
    else:
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
    appels: list[str] = []

    async def go():
        async with _client(statuts, appels) as c:
            return await gemini.generer(c, "cle", {})
    return asyncio.run(go()), appels


def test_sature_passe_au_modele_inferieur(monkeypatch):
    resp, appels = _lancer({"gemini-flash-latest": 503}, monkeypatch)
    assert resp.status_code == 200
    assert appels == ["gemini-flash-latest", "gemini-flash-latest", "gemini-2.5-flash"]


def test_modele_retire_passe_au_suivant(monkeypatch):
    resp, appels = _lancer({"ancien": 404}, monkeypatch, modele_env="ancien")
    assert resp.status_code == 200
    assert appels == ["ancien", "gemini-flash-latest"]


def test_tous_satures_renvoie_503(monkeypatch):
    statuts = {m: 503 for m in gemini.REPLIS}
    resp, appels = _lancer(statuts, monkeypatch)
    assert resp.status_code == 503
    assert len(appels) == 2 * len(gemini.REPLIS)


def test_erreur_de_cle_ne_change_pas_de_modele(monkeypatch):
    resp, appels = _lancer({"gemini-flash-latest": 400}, monkeypatch)
    assert resp.status_code == 400
    assert appels == ["gemini-flash-latest"]
