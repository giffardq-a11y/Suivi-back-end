"""Catalogue de recettes : chargement, calcul des macros, contrôle de cohérence.

Une recette n'écrit **jamais** ses kcal ni ses macros : elle liste des
ingrédients quantifiés en grammes, et tout est calculé ici à partir de
app/data/ingredients.json (table CIQUAL, voir tools/extraire_ciqual.py). Une
valeur fausse vient donc soit d'une quantité, soit de la table — jamais d'un
chiffre saisi à la louche.

    python tools/valider_recettes.py            # contrôle le catalogue livré
    python tools/valider_recettes.py fichier.json

Les recettes vivent dans app/data/recettes.json (versionné) plutôt qu'en base :
c'est un catalogue commun à tous les utilisateurs, qui se relit et se corrige
comme du code.
"""
import json
from functools import lru_cache
from pathlib import Path

DOSSIER_DONNEES = Path(__file__).resolve().parent / "data"
FICHIER_INGREDIENTS = DOSSIER_DONNEES / "ingredients.json"
FICHIER_RECETTES = DOSSIER_DONNEES / "recettes.json"

TYPES_REPAS = ("petit-dejeuner", "dejeuner", "diner", "collation")

# Fourchettes de contrôle : une recette hors bornes est probablement une
# erreur de quantité (200 g d'huile, 20 g de poulet...). Ce n'est pas une
# règle nutritionnelle, juste un garde-fou de saisie.
BORNES_KCAL = {
    "petit-dejeuner": (250, 700),
    "dejeuner": (400, 950),
    "diner": (350, 900),
    "collation": (100, 400),
}
PROTEINES_MINI = {"petit-dejeuner": 10, "dejeuner": 25, "diner": 22, "collation": 5}


@lru_cache(maxsize=1)
def ingredients() -> dict[str, dict]:
    """Table des ingrédients, indexée par clé."""
    donnees = json.loads(FICHIER_INGREDIENTS.read_text(encoding="utf-8"))
    return {i["cle"]: i for i in donnees["ingredients"]}


@lru_cache(maxsize=1)
def recettes() -> list[dict]:
    """Catalogue complet, chaque recette enrichie de ses macros calculées."""
    if not FICHIER_RECETTES.exists():
        return []
    donnees = json.loads(FICHIER_RECETTES.read_text(encoding="utf-8"))
    return [enrichir(r) for r in donnees["recettes"]]


def macros_recette(recette: dict) -> dict:
    """kcal et macros d'une portion, sommées sur les ingrédients."""
    table = ingredients()
    totaux = {"calories": 0.0, "proteines": 0.0, "glucides": 0.0, "lipides": 0.0, "fibres": 0.0}
    for ligne in recette["ingredients"]:
        ingredient = table.get(ligne["cle"])
        if ingredient is None:
            continue
        part = ligne["quantite_g"] / 100
        totaux["calories"] += ingredient["kcal_100g"] * part
        totaux["proteines"] += ingredient["proteines_100g"] * part
        totaux["glucides"] += ingredient["glucides_100g"] * part
        totaux["lipides"] += ingredient["lipides_100g"] * part
        totaux["fibres"] += ingredient["fibres_100g"] * part
    portions = recette.get("portions", 1) or 1
    return {cle: round(valeur / portions) for cle, valeur in totaux.items()}


def enrichir(recette: dict) -> dict:
    """Recette + macros calculées + libellés d'ingrédients prêts à afficher."""
    table = ingredients()
    lignes = []
    for ligne in recette["ingredients"]:
        ingredient = table.get(ligne["cle"])
        lignes.append({
            **ligne,
            "nom": ingredient["nom"] if ingredient else ligne["cle"],
            "rayon": ingredient["rayon"] if ingredient else "divers",
        })
    return {**recette, "ingredients": lignes, "macros": macros_recette(recette)}


def valider(donnees: dict) -> list[str]:
    """Liste des anomalies du catalogue — vide si tout va bien."""
    table = ingredients()
    erreurs: list[str] = []
    vus: set[str] = set()

    for recette in donnees.get("recettes", []):
        identifiant = recette.get("id", "?")
        prefixe = f"[{identifiant}]"

        for champ in ("id", "nom", "type", "ingredients", "etapes"):
            if not recette.get(champ):
                erreurs.append(f"{prefixe} champ obligatoire manquant : {champ}")
        if identifiant in vus:
            erreurs.append(f"{prefixe} identifiant en double")
        vus.add(identifiant)

        type_repas = recette.get("type")
        if type_repas not in TYPES_REPAS:
            erreurs.append(f"{prefixe} type inconnu : {type_repas}")
            continue

        lignes = recette.get("ingredients") or []
        if not 2 <= len(lignes) <= 12:
            erreurs.append(f"{prefixe} {len(lignes)} ingrédients (attendu entre 2 et 12)")
        cles_vues = set()
        for ligne in lignes:
            cle = ligne.get("cle")
            if cle not in table:
                erreurs.append(f"{prefixe} ingrédient inconnu : {cle}")
                continue
            if cle in cles_vues:
                erreurs.append(f"{prefixe} ingrédient en double : {cle}")
            cles_vues.add(cle)
            quantite = ligne.get("quantite_g")
            if not isinstance(quantite, (int, float)) or not 1 <= quantite <= 600:
                erreurs.append(f"{prefixe} quantité invalide pour {cle} : {quantite}")

        etapes = recette.get("etapes") or []
        if len(etapes) < 2:
            erreurs.append(f"{prefixe} {len(etapes)} étape(s), il en faut au moins 2")
        for etape in etapes:
            if len(etape) > 220:
                erreurs.append(f"{prefixe} étape trop longue ({len(etape)} caractères)")

        if any(e.startswith(prefixe) for e in erreurs):
            continue  # macros non contrôlées si la recette est déjà fautive

        macros = macros_recette(recette)
        mini, maxi = BORNES_KCAL[type_repas]
        if not mini <= macros["calories"] <= maxi:
            erreurs.append(f"{prefixe} {macros['calories']} kcal hors de [{mini}, {maxi}] pour un {type_repas}")
        if macros["proteines"] < PROTEINES_MINI[type_repas]:
            erreurs.append(f"{prefixe} {macros['proteines']} g de protéines, minimum {PROTEINES_MINI[type_repas]}")

    return erreurs
