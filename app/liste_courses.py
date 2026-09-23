"""Liste de courses d'une semaine planifiée.

On additionne les ingrédients de toutes les recettes de la semaine, en tenant
compte des portions choisies par le générateur et du nombre de personnes, puis
on convertit en quantités achetables : des pièces pour ce qui se vend à l'unité
(œufs, bananes), des grammes ou millilitres arrondis pour le reste, le tout
groupé par rayon pour suivre l'ordre d'un magasin.

Un repas du plan qui ne vient pas du catalogue (plan importé d'un classeur, qui
n'a qu'un libellé) ne peut pas être décomposé en ingrédients : il est renvoyé à
part dans `repas_sans_recette` plutôt qu'ignoré en silence.
"""
import math

from .recettes import ingredients, recettes

ORDRE_RAYONS = ["primeur", "boucherie", "charcuterie", "poissonnerie", "frais",
                "surgeles", "boulangerie", "epicerie", "divers"]

LIBELLE_RAYON = {
    "primeur": "Fruits et légumes",
    "boucherie": "Boucherie",
    "charcuterie": "Charcuterie",
    "poissonnerie": "Poissonnerie",
    "frais": "Produits frais",
    "surgeles": "Surgelés",
    "boulangerie": "Boulangerie",
    "epicerie": "Épicerie",
    "divers": "Divers",
}


def _arrondir(grammes: float) -> int:
    """Arrondi à ce qu'on sait peser ou acheter : au pas de 5 g en dessous de
    100 g, de 10 g jusqu'à 1 kg, de 50 g au-delà."""
    if grammes < 100:
        pas = 5
    elif grammes < 1000:
        pas = 10
    else:
        pas = 50
    return int(math.ceil(grammes / pas) * pas)


def liste_de_courses(repas: list[dict], nb_personnes: int = 1) -> dict:
    """`repas` : dicts avec recipe_id, portions et label (les entrées du plan)."""
    catalogue = {r["id"]: r for r in recettes()}
    table = ingredients()

    totaux: dict[str, float] = {}
    sans_recette: list[str] = []
    for ligne in repas:
        recette = catalogue.get(ligne.get("recipe_id"))
        if recette is None:
            sans_recette.append(ligne.get("label", "?"))
            continue
        facteur = (ligne.get("portions") or 1) * nb_personnes
        for ingredient in recette["ingredients"]:
            totaux[ingredient["cle"]] = totaux.get(ingredient["cle"], 0) + ingredient["quantite_g"] * facteur

    par_rayon: dict[str, list[dict]] = {}
    for cle, grammes in totaux.items():
        ingredient = table.get(cle)
        if ingredient is None:
            continue
        if ingredient["unite"] == "piece" and ingredient.get("poids_piece_g"):
            quantite = max(1, math.ceil(grammes / ingredient["poids_piece_g"]))
            unite = "pièce" if quantite == 1 else "pièces"
        else:
            quantite = _arrondir(grammes)
            # Les liquides sont comptés en millilitres : on assimile 1 g à 1 ml,
            # l'écart est négligeable devant l'arrondi d'achat.
            unite = "ml" if ingredient["unite"] == "ml" else "g"
        par_rayon.setdefault(ingredient["rayon"], []).append({
            "cle": cle,
            "nom": ingredient["nom"],
            "quantite": quantite,
            "unite": unite,
            "grammes": round(grammes),
            "conditionnement": ingredient.get("conditionnement"),
        })

    rayons = [
        {
            "rayon": rayon,
            "libelle": LIBELLE_RAYON.get(rayon, rayon.capitalize()),
            "lignes": sorted(par_rayon[rayon], key=lambda l: l["nom"]),
        }
        for rayon in ORDRE_RAYONS if rayon in par_rayon
    ]
    return {
        "nb_personnes": nb_personnes,
        "rayons": rayons,
        "nb_lignes": sum(len(r["lignes"]) for r in rayons),
        "repas_sans_recette": sorted(set(sans_recette)),
    }
