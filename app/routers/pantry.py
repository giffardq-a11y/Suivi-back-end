"""Placard / frigo : stock, scans (photo et ticket de courses), recettes
faisables, déduction quand on cuisine. La logique est dans app/placard.py.

Scans. Deux lectures d'image par Gemini (même clé GEMINI_API_KEY que
l'estimation de repas en photo, voir meal_photo.py) :
- photo du placard / frigo : Gemini liste ce qu'il voit, avec un niveau
  (plein / entamé / presque fini) et le nombre de paquets ;
- ticket de courses : Gemini lit les lignes alimentaires et leur poids.
Dans les deux cas, Gemini reçoit la liste des ingrédients du catalogue et
renvoie leur clé ; une clé inconnue est rattrapée par placard.correspondance.
Rien n'est enregistré au scan : l'app affiche la proposition, l'utilisateur
corrige, et c'est POST /diet/pantry/apply qui écrit.

Les photos partent chez Google (Gemini) le temps de l'analyse.
"""
import base64
import json
import os

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..placard import (
    EMPLACEMENTS, NIVEAUX, besoins_recette, correspondance, deduire, grammes_estimes,
    poids_conditionnement, stock_par_ingredient, suggestions,
)
from ..recettes import ingredients, recettes
from ..services.common import now_utc, to_ms, relative_time
from ..services import gemini

router = APIRouter(prefix="/diet/pantry", tags=["pantry"])

TAILLE_MAX_IMAGE = 8 * 1024 * 1024

# Emplacement par défaut d'un produit acheté, selon son rayon.
EMPLACEMENT_PAR_RAYON = {
    "boucherie": "frigo", "charcuterie": "frigo", "poissonnerie": "frigo", "frais": "frigo",
    "surgeles": "congelateur",
}


# ---------- Schémas ----------

class ItemIn(BaseModel):
    label: str
    ingredient_key: str | None = None
    location: str = "placard"
    level: str | None = "plein"
    packages: int = 1
    quantity_g: float | None = None


class ApplyIn(BaseModel):
    # inventaire : remplace tout le contenu de `location` (scan photo) ;
    # ajout : ajoute aux articles existants (ticket de courses).
    mode: str
    location: str | None = None
    items: list[ItemIn]
    source: str = "photo"


class CookIn(BaseModel):
    recipe_id: str
    portions: float = 1.0


# ---------- Sérialisation ----------

def _items(db: Session, user: models.User) -> list[models.PantryItem]:
    return db.query(models.PantryItem).filter(models.PantryItem.user_id == user.id).all()


def _as_dict(item: models.PantryItem) -> dict:
    return {
        "id": item.id, "ingredient_key": item.ingredient_key, "label": item.label,
        "location": item.location, "level": item.level, "packages": item.packages,
        "quantity_g": item.quantity_g,
    }


def _serialize(item: models.PantryItem, table: dict) -> dict:
    ing = table.get(item.ingredient_key or "")
    grammes = grammes_estimes(_as_dict(item), table)
    return {
        **_as_dict(item),
        "nom": ing["nom"] if ing else item.label,
        "reconnu": ing is not None,
        "unite": ing["unite"] if ing else None,
        "estime_g": round(grammes),
        "epuise": item.quantity_g is not None and item.quantity_g <= 0,
        "updatedAt": to_ms(item.updated_at),
    }


def _valider_item(item: ItemIn, table: dict) -> ItemIn:
    if item.location not in EMPLACEMENTS:
        raise HTTPException(status_code=422, detail=f"Emplacement inconnu : {item.location}")
    if item.level is not None and item.level not in NIVEAUX:
        raise HTTPException(status_code=422, detail=f"Niveau inconnu : {item.level}")
    cle = item.ingredient_key if item.ingredient_key in table else correspondance(item.label, table)
    return item.model_copy(update={"ingredient_key": cle, "packages": max(1, item.packages)})


# ---------- Stock ----------

@router.get("")
def get_pantry(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    table = ingredients()
    items = sorted(_items(db, user), key=lambda i: (i.label or "").lower())
    par_emplacement = {e: [] for e in EMPLACEMENTS}
    for item in items:
        par_emplacement.setdefault(item.location, []).append(_serialize(item, table))
    return {
        "emplacements": par_emplacement,
        "nb_articles": len(items),
        "catalogue": [{"cle": c, "nom": i["nom"], "rayon": i["rayon"]} for c, i in sorted(table.items(), key=lambda x: x[1]["nom"])],
    }


@router.post("/items", status_code=201)
def add_item(payload: ItemIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = _valider_item(payload, ingredients())
    db.add(models.PantryItem(user_id=user.id, source="manuel", updated_at=now_utc(), **item.model_dump()))
    db.commit()
    return {"ok": True}


@router.put("/items/{item_id}")
def update_item(item_id: str, payload: ItemIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    item = db.query(models.PantryItem).filter(models.PantryItem.id == item_id,
                                              models.PantryItem.user_id == user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Article introuvable.")
    for champ, valeur in _valider_item(payload, ingredients()).model_dump().items():
        setattr(item, champ, valeur)
    item.updated_at = now_utc()
    db.commit()
    return {"ok": True}


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    (db.query(models.PantryItem)
       .filter(models.PantryItem.id == item_id, models.PantryItem.user_id == user.id)
       .delete(synchronize_session=False))
    db.commit()


@router.post("/apply")
def apply_scan(payload: ApplyIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Enregistre une proposition de scan relue par l'utilisateur."""
    table = ingredients()
    items = [_valider_item(i, table) for i in payload.items]
    if payload.mode == "inventaire":
        if payload.location not in EMPLACEMENTS:
            raise HTTPException(status_code=422, detail="Emplacement requis pour un inventaire.")
        (db.query(models.PantryItem)
           .filter(models.PantryItem.user_id == user.id, models.PantryItem.location == payload.location)
           .delete(synchronize_session=False))
        for item in items:
            db.add(models.PantryItem(user_id=user.id, source=payload.source, updated_at=now_utc(),
                                     **{**item.model_dump(), "location": payload.location}))
    elif payload.mode == "ajout":
        existants = _items(db, user)
        for item in items:
            meme = next((e for e in existants if item.ingredient_key
                         and e.ingredient_key == item.ingredient_key and e.location == item.location), None)
            if meme is not None:
                # Le stock connu (ou estimé) + ce qui vient d'être acheté,
                # désormais en grammes.
                ajout = grammes_estimes(item.model_dump(), table)
                meme.quantity_g = grammes_estimes(_as_dict(meme), table) + ajout
                meme.level = None
                meme.updated_at = now_utc()
                meme.source = payload.source
            else:
                nouveau = models.PantryItem(user_id=user.id, source=payload.source, updated_at=now_utc(),
                                            **item.model_dump())
                db.add(nouveau)
                existants.append(nouveau)
    else:
        raise HTTPException(status_code=422, detail=f"Mode inconnu : {payload.mode}")
    db.commit()
    return {"ok": True, "count": len(items)}


# ---------- Scans (Gemini) ----------

def _catalogue_pour_prompt(table: dict) -> str:
    return "\n".join(f"{c}: {i['nom']}" for c, i in sorted(table.items()))


async def _gemini_json(image: bytes, mime: str, consigne: str) -> list[dict]:
    cle_api = os.environ.get("GEMINI_API_KEY")
    if not cle_api:
        raise HTTPException(status_code=501, detail="Gemini pas configuré côté serveur : variable GEMINI_API_KEY manquante.")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await gemini.generer(client, cle_api, {
            "contents": [{"parts": [
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode()}},
                {"text": consigne},
            ]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        })
    if resp.status_code in gemini.SURCHARGE:
        raise HTTPException(status_code=503, detail="Gemini est saturé en ce moment : réessaie dans une minute.")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de l'analyse Gemini : {resp.text[:300]}")
    try:
        texte = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        donnees = json.loads(texte)
    except (KeyError, IndexError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail="Réponse Gemini illisible : réessaie avec une photo plus nette.")
    if isinstance(donnees, dict):
        donnees = next((v for v in donnees.values() if isinstance(v, list)), [])
    return [d for d in donnees if isinstance(d, dict)]


async def _lire_image(photo: UploadFile) -> tuple[bytes, str]:
    image = await photo.read()
    if not image:
        raise HTTPException(status_code=422, detail="Photo vide.")
    if len(image) > TAILLE_MAX_IMAGE:
        raise HTTPException(status_code=413, detail="Photo trop lourde (8 Mo maximum).")
    return image, photo.content_type or "image/jpeg"


def proposition_depuis_photo(lignes: list[dict], location: str, table: dict) -> list[dict]:
    """Réponse Gemini d'une photo -> articles proposés (ItemIn en dict)."""
    proposes = []
    for ligne in lignes:
        nom = str(ligne.get("nom") or ligne.get("cle") or "").strip()
        if not nom:
            continue
        cle = ligne.get("cle") if ligne.get("cle") in table else correspondance(nom, table)
        niveau = ligne.get("niveau") if ligne.get("niveau") in NIVEAUX else "plein"
        try:
            paquets = max(1, int(ligne.get("nombre") or 1))
        except (TypeError, ValueError):
            paquets = 1
        proposes.append({"label": nom, "ingredient_key": cle, "location": location,
                         "level": niveau, "packages": paquets, "quantity_g": None})
    return proposes


def proposition_depuis_ticket(lignes: list[dict], table: dict) -> list[dict]:
    """Réponse Gemini d'un ticket -> articles proposés, en grammes."""
    proposes = []
    for ligne in lignes:
        libelle = str(ligne.get("libelle") or "").strip()
        if not libelle:
            continue
        cle = ligne.get("cle") if ligne.get("cle") in table else correspondance(libelle, table)
        ing = table.get(cle or "")
        try:
            nombre = max(1, int(ligne.get("nombre") or 1))
        except (TypeError, ValueError):
            nombre = 1
        try:
            poids = float(ligne.get("poids_unitaire_g")) if ligne.get("poids_unitaire_g") else None
        except (TypeError, ValueError):
            poids = None
        if poids is None and ing is not None:
            if ing["unite"] == "piece" and ing.get("poids_piece_g"):
                poids = ing["poids_piece_g"]  # « OEUFS X6 » : nombre = pièces
            else:
                poids = poids_conditionnement(ing)  # poids non imprimé : paquet habituel
        emplacement = EMPLACEMENT_PAR_RAYON.get(ing["rayon"], "placard") if ing else "placard"
        proposes.append({
            "label": ing["nom"] if ing else libelle, "ingredient_key": cle, "location": emplacement,
            "level": None, "packages": 1,
            "quantity_g": round(poids * nombre) if poids else None,
            "libelle_ticket": libelle,
        })
    return proposes


@router.post("/scan-photo")
async def scan_photo(photo: UploadFile = File(...), location: str = Query("placard"),
                     user: models.User = Depends(get_current_user)):
    if location not in EMPLACEMENTS:
        raise HTTPException(status_code=422, detail=f"Emplacement inconnu : {location}")
    image, mime = await _lire_image(photo)
    table = ingredients()
    consigne = (
        f"Photo de l'intérieur d'un {location}. Liste tous les aliments et produits alimentaires visibles. "
        "Réponds par un tableau JSON d'objets {\"cle\", \"nom\", \"niveau\", \"nombre\"} : "
        "`cle` = la clé exacte du catalogue ci-dessous qui correspond au produit, ou null si aucune ; "
        "`nom` = nom court du produit en français ; "
        "`niveau` = \"plein\", \"entame\" ou \"presque_fini\" selon ce qu'on voit (plein si fermé ou impossible à dire) ; "
        "`nombre` = nombre de paquets, pots ou pièces identiques visibles. "
        "N'invente rien : ignore ce qui n'est pas lisible.\n\nCatalogue :\n" + _catalogue_pour_prompt(table)
    )
    lignes = await _gemini_json(image, mime, consigne)
    return {"location": location, "items": proposition_depuis_photo(lignes, location, table)}


@router.post("/scan-receipt")
async def scan_receipt(photo: UploadFile = File(...), user: models.User = Depends(get_current_user)):
    image, mime = await _lire_image(photo)
    table = ingredients()
    consigne = (
        "Photo d'un ticket de caisse de supermarché. Liste uniquement les lignes alimentaires "
        "(ignore sacs, produits d'entretien, hygiène, remises, totaux). "
        "Réponds par un tableau JSON d'objets {\"libelle\", \"cle\", \"nombre\", \"poids_unitaire_g\"} : "
        "`libelle` = le texte de la ligne tel qu'imprimé ; "
        "`cle` = la clé exacte du catalogue ci-dessous qui correspond, ou null ; "
        "`nombre` = quantité achetée (1 par défaut ; pour un lot « x6 », le nombre de pièces) ; "
        "`poids_unitaire_g` = poids ou volume d'une unité en grammes ou ml s'il est écrit (500G, 1L -> 1000), sinon null. "
        "Pour un produit pesé, mets nombre = 1 et poids_unitaire_g = le poids pesé.\n\nCatalogue :\n"
        + _catalogue_pour_prompt(table)
    )
    lignes = await _gemini_json(image, mime, consigne)
    return {"items": proposition_depuis_ticket(lignes, table)}


# ---------- Recettes et cuisine ----------

@router.get("/suggestions")
def get_suggestions(type: str | None = None, portions: float = 1.0,
                    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    stock = stock_par_ingredient([_as_dict(i) for i in _items(db, user)])
    return {**suggestions(stock, type_repas=type, portions=portions), "stock_vide": not stock}


def cuisiner(db: Session, user: models.User, recipe_id: str, portions: float) -> dict:
    """Retire du stock les ingrédients d'une recette ; partagé avec le journal
    d'un repas du plan (routers/diet.py)."""
    recette = next((r for r in recettes() if r["id"] == recipe_id), None)
    if recette is None:
        raise HTTPException(status_code=404, detail="Recette introuvable.")
    items = _items(db, user)
    changements = deduire([_as_dict(i) for i in items], besoins_recette(recette, portions))
    par_id = {i.id: i for i in items}
    for c in changements:
        item = par_id[c["id"]]
        item.quantity_g = c["quantity_g_apres"]
        item.level = None
        item.source = "recette"
        item.updated_at = now_utc()
    log = models.CookingLog(user_id=user.id, recipe_id=recipe_id, recipe_name=recette["nom"],
                            portions=portions, changes=changements, occurred_at=now_utc())
    db.add(log)
    db.commit()
    return {"ok": True, "log_id": log.id, "articles_modifies": len(changements)}


@router.post("/cook", status_code=201)
def cook(payload: CookIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if payload.portions <= 0:
        raise HTTPException(status_code=422, detail="Nombre de portions invalide.")
    return cuisiner(db, user, payload.recipe_id, payload.portions)


@router.post("/cook/{log_id}/undo")
def undo_cook(log_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    log = db.query(models.CookingLog).filter(models.CookingLog.id == log_id,
                                             models.CookingLog.user_id == user.id).first()
    if log is None:
        raise HTTPException(status_code=404, detail="Recette cuisinée introuvable.")
    if log.undone:
        return {"ok": True, "deja_annule": True}
    par_id = {i.id: i for i in _items(db, user)}
    for c in log.changes or []:
        item = par_id.get(c["id"])
        if item is None:
            continue  # article supprimé entre-temps : rien à restaurer
        item.quantity_g = c["quantity_g_avant"]
        item.level = c["level_avant"]
        item.updated_at = now_utc()
    log.undone = True
    db.commit()
    return {"ok": True}


@router.get("/cooked")
def get_cooked(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    logs = (db.query(models.CookingLog)
              .filter(models.CookingLog.user_id == user.id)
              .order_by(models.CookingLog.occurred_at.desc())
              .limit(10).all())
    return [{"id": l.id, "recipe_id": l.recipe_id, "nom": l.recipe_name, "portions": l.portions,
             "undone": l.undone, "relativeTime": relative_time(l.occurred_at)} for l in logs]
