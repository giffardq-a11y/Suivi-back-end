"""Gestion des modules actifs d'un compte : consultation, activation/
désactivation, purge des données d'un module — voir app/modules.py pour le
registre (clés, tables, SOCLE) et la sémantique NULL = tout actif.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..modules import MODULES, TOUS, modules_actifs, supprimer_donnees

router = APIRouter(prefix="/me/modules", tags=["modules"])


class ModulesIn(BaseModel):
    enabled: list[str]


def _etat(user: models.User) -> dict:
    return {
        "enabled": modules_actifs(user),
        "available": [{"key": cle, "label": MODULES[cle]["label"]} for cle in TOUS],
    }


@router.get("")
def get_modules(user: models.User = Depends(get_current_user)):
    return _etat(user)


@router.put("")
def update_modules(
    payload: ModulesIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    inconnues = [m for m in payload.enabled if m not in MODULES]
    if inconnues:
        raise HTTPException(status_code=422, detail=f"Module(s) inconnu(s) : {', '.join(inconnues)}")
    # Dédoublonne en gardant l'ordre envoyé. Une liste vide est valide
    # (aucun module optionnel actif) : le SOCLE, lui, n'est pas dans la
    # liste des modules désactivables et n'est donc jamais concerné ici.
    user.enabled_modules = list(dict.fromkeys(payload.enabled))
    db.commit()
    db.refresh(user)
    return _etat(user)


@router.post("/{module}/supprimer-donnees")
def supprimer_donnees_module(
    module: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Efface les données du module (sans le désactiver : un second appel à
    PUT /me/modules s'en charge si besoin)."""
    if module not in MODULES:
        raise HTTPException(status_code=404, detail="Module inconnu")
    compte = supprimer_donnees(db, user.id, module)
    return {"module": module, "deleted": compte}
