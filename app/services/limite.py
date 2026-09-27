"""Limite de tentatives (connexion, inscription, mot de passe oublié,
demande de suppression), en mémoire.

En mémoire plutôt que slowapi + Redis : une seule instance tourne sur Render,
et un redémarrage qui remet les compteurs à zéro est sans conséquence. À
revoir si le service passe à plusieurs instances.

Adresse IP : derrière le proxy de Render, request.client.host est celle du
proxy. On lit X-Forwarded-For, en prenant l'adresse la plus à DROITE : c'est
celle qu'a vue le proxy de Render ; celles de gauche peuvent être inventées
par le client.
"""
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_fenetres: dict[str, deque] = defaultdict(deque)


def ip_client(request: Request) -> str:
    transmis = request.headers.get("x-forwarded-for", "")
    if transmis:
        return transmis.split(",")[-1].strip()
    return request.client.host if request.client else "inconnue"


def verifier(cle: str, maximum: int, fenetre_s: int) -> None:
    """Lève 429 si `cle` a déjà servi `maximum` fois dans la fenêtre."""
    if os.environ.get("LIMITES_DESACTIVEES") == "1":
        return
    maintenant = time.monotonic()
    file = _fenetres[cle]
    while file and maintenant - file[0] > fenetre_s:
        file.popleft()
    if len(file) >= maximum:
        attente = int(fenetre_s - (maintenant - file[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Trop de tentatives. Réessaie dans {max(1, attente // 60)} min.",
            headers={"Retry-After": str(attente)},
        )
    file.append(maintenant)


def reinitialiser() -> None:
    """Pour les tests."""
    _fenetres.clear()


# Réglages par action : (maximum, fenêtre en secondes).
CONNEXION_PAR_IP = (20, 15 * 60)
CONNEXION_PAR_COMPTE = (8, 15 * 60)     # par adresse e-mail visée, toutes IP confondues
INSCRIPTION_PAR_IP = (10, 60 * 60)
OUBLI_PAR_IP = (10, 60 * 60)
SUPPRESSION_WEB_PAR_IP = (10, 60 * 60)
RAFRAICHISSEMENT_PAR_IP = (120, 15 * 60)
