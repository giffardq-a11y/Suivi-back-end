"""Page d'affichage du tableau partagé, pour un écran (PC, TV du salon).

    GET /tableau#<jeton>

Une page HTML statique (app/tableau/tableau.html) qui lit GET /board/{jeton}
(routers/board.py) et se relit seule. Le jeton est dans le fragment de
l'adresse : le navigateur ne l'envoie pas avec la page, il n'apparaît donc ni
dans les journaux de cette route ni dans un en-tête Referer. La page ne touche
pas à la base et ne montre que ce que /board/{jeton} renvoie déjà (données
agrégées, jamais l'e-mail ni le détail des consommations ou des repas).
"""
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["board"])

PAGE = Path(__file__).resolve().parent.parent / "tableau" / "tableau.html"

ENTETES = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    # Script et style intégrés à la page ; seules lectures permises : l'API
    # de ce même serveur. Pas d'inclusion dans un cadre d'un autre site.
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
}


@lru_cache
def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


@router.get("/tableau", response_class=HTMLResponse, include_in_schema=False)
def page_tableau():
    return HTMLResponse(_page(), headers=ENTETES)
