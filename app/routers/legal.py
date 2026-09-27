"""Pages légales publiques (politique de confidentialité, suppression de
compte), exigées par la Play Console. Sources HTML dans app/legal/, reprises
du kit de publication Tanren puis corrigées pour coller au code (voir le
commit qui les introduit).

L'adresse de contact vient de CONTACT_EMAIL (Render) : tant qu'elle n'est pas
posée, le repère [ADRESSE-CONTACT] reste visible, ce qui rappelle que les
pages ne sont pas prêtes à être déclarées.
"""
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["legal"])

DOSSIER = Path(__file__).resolve().parent.parent / "legal"
PAGES = {"privacy.html", "delete-account.html"}
REPERE = "[ADRESSE-CONTACT]"


@lru_cache
def _source(nom: str) -> str:
    return (DOSSIER / nom).read_text(encoding="utf-8")


@router.get("/legal/{nom}", response_class=HTMLResponse)
def page_legale(nom: str):
    if nom not in PAGES:
        raise HTTPException(status_code=404)
    contact = os.environ.get("CONTACT_EMAIL", "").strip()
    html = _source(nom)
    if contact:
        html = html.replace(REPERE, contact)
    return HTMLResponse(html)


# Adresses courtes, plus faciles à saisir dans la Play Console.
@router.get("/confidentialite", include_in_schema=False)
@router.get("/privacy", include_in_schema=False)
def raccourci_confidentialite():
    return RedirectResponse("/legal/privacy.html")


@router.get("/suppression-compte", include_in_schema=False)
@router.get("/delete-account", include_in_schema=False)
def raccourci_suppression():
    return RedirectResponse("/legal/delete-account.html")
