"""Placard / frigo : ce qu'on a, ce qu'on peut cuisiner avec, ce qui manque.

Logique pure (pas de base ni de réseau) pour pouvoir la tester seule ; les
routes sont dans routers/pantry.py.

Quantités. Deux façons de connaître le stock d'un ingrédient :
- `quantity_g` : grammes connus (ticket de courses, saisie, reste après une
  recette) — c'est la référence quand elle existe ;
- `level` : niveau vu sur une photo du placard ou du frigo (plein / entamé /
  presque fini), converti en grammes estimés à partir du conditionnement
  habituel de l'ingrédient (app/data/ingredients.json). Une photo ne permet
  pas mieux : on ne voit pas ce qui reste dans un paquet fermé.

Liquides : 1 ml est compté comme 1 g, comme dans liste_courses.py. Ingrédients
à la pièce (œufs, bananes) : conditionnement = nombre de pièces, converti en
grammes par poids_piece_g.
"""
import math
import re
import unicodedata

from .recettes import ingredients, recettes

EMPLACEMENTS = ("placard", "frigo", "congelateur")
NIVEAUX = ("plein", "entame", "presque_fini")
PART_NIVEAU = {"plein": 1.0, "entame": 0.5, "presque_fini": 0.15}

# En dessous de ce besoin (pincée d'épices, filet d'huile, cuillère de
# moutarde), un ingrédient présent en stock suffit toujours, quel que soit son
# niveau : inutile de refuser une recette pour 5 g de cumin « presque fini ».
BESOIN_NEGLIGEABLE_G = 15

# Toujours supposés disponibles : ne bloquent jamais une recette et ne vont
# jamais sur la liste de courses. Le catalogue ne les contient pas encore
# (ni sel, ni poivre, ni eau), la liste est là pour le jour où il les aura.
TOUJOURS_DISPONIBLES = {"sel", "poivre", "eau"}

# Une recette « presque faisable » : il manque au plus ce nombre d'ingrédients.
MANQUANTS_MAX_PRESQUE = 2


def poids_conditionnement(ingredient: dict) -> float:
    """Poids en grammes d'un conditionnement habituel (un paquet, un pot...)."""
    cond = ingredient.get("conditionnement") or 0
    if ingredient.get("unite") == "piece" and ingredient.get("poids_piece_g"):
        return cond * ingredient["poids_piece_g"]
    return float(cond)


def grammes_estimes(item: dict, table: dict | None = None) -> float:
    """Grammes en stock d'un article (dict avec ingredient_key, quantity_g, level, packages)."""
    if item.get("quantity_g") is not None:
        return max(0.0, float(item["quantity_g"]))
    table = table or ingredients()
    ingredient = table.get(item.get("ingredient_key") or "")
    if ingredient is None:
        return 0.0
    paquets = item.get("packages") or 1
    return poids_conditionnement(ingredient) * PART_NIVEAU.get(item.get("level") or "plein", 1.0) * paquets


def stock_par_ingredient(items: list[dict]) -> dict[str, float]:
    """Grammes disponibles par clé d'ingrédient, tous emplacements confondus.
    Les articles non reconnus (sans clé) ne servent pas aux recettes."""
    table = ingredients()
    stock: dict[str, float] = {}
    for item in items:
        cle = item.get("ingredient_key")
        if cle and cle in table:
            stock[cle] = stock.get(cle, 0.0) + grammes_estimes(item, table)
    return stock


# ---------- Correspondance libellé -> ingrédient du catalogue ----------

def _normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return " ".join(sans_accents.lower().replace("_", " ").replace("-", " ").replace("'", " ").split())


def _mots(texte: str) -> set[str]:
    # Singulier grossier : « tomates » -> « tomate », « oeufs » -> « oeuf ».
    return {m[:-1] if len(m) > 3 and m.endswith(("s", "x")) else m for m in _normaliser(texte).split()}


def correspondance(libelle: str, table: dict | None = None) -> str | None:
    """Clé du catalogue qui correspond le mieux à un libellé libre (« Pâtes
    Barilla 500g », « OEUFS X6 »), ou None. Sert de filet quand Gemini ne
    renvoie pas de clé valide, et pour les saisies manuelles."""
    table = table or ingredients()
    cible = _mots(libelle)
    if not cible:
        return None
    meilleure, meilleur_score = None, (0.0, 0)
    for cle, ing in table.items():
        # Nom sans ses précisions entre parenthèses (« Pâtes (crues) »), et la
        # clé, souvent plus courte : on garde la meilleure des deux.
        nom = re.sub(r"\(.*?\)", " ", ing["nom"])
        score = (0.0, 0)
        for mots_ing in (_mots(nom), _mots(cle)):
            communs = cible & mots_ing
            if communs:
                # Part du nom retrouvée dans le libellé : « pâtes » trouve pates
                # (1/1) avant pates_completes (1/2). À part égale, le plus de
                # mots en commun : « tomates cerises » -> tomate_cerise, pas tomate.
                score = max(score, (len(communs) / len(mots_ing), len(communs)))
        if score > meilleur_score:
            meilleure, meilleur_score = cle, score
    # Moitié du nom retrouvée : acceptée seulement avec au moins 2 mots en
    # commun (« sauce piquante » ne doit pas devenir « sauce soja »).
    part, communs = meilleur_score
    return meilleure if part > 0.5 or (part == 0.5 and communs >= 2) else None


# ---------- Recettes faisables avec le stock ----------

def besoins_recette(recette: dict, portions: float = 1.0) -> dict[str, float]:
    """Grammes par ingrédient pour `portions` fois la recette telle qu'écrite."""
    besoins: dict[str, float] = {}
    for ligne in recette["ingredients"]:
        besoins[ligne["cle"]] = besoins.get(ligne["cle"], 0.0) + ligne["quantite_g"] * portions
    return besoins


def manques(besoins: dict[str, float], stock: dict[str, float]) -> dict[str, float]:
    """Grammes manquants par ingrédient (seulement ceux qui manquent)."""
    resultat = {}
    for cle, besoin in besoins.items():
        if cle in TOUJOURS_DISPONIBLES:
            continue
        dispo = stock.get(cle, 0.0)
        if dispo > 0 and besoin <= BESOIN_NEGLIGEABLE_G:
            continue
        if dispo + 1e-6 < besoin:
            resultat[cle] = besoin - dispo
    return resultat


def suggestions(stock: dict[str, float], type_repas: str | None = None,
                portions: float = 1.0, limite: int = 30) -> dict:
    """Recettes classées selon ce qu'on a : faisables tout de suite, puis
    presque faisables (1 ou 2 ingrédients à acheter), les autres écartées.

    À manques égaux, on préfère la recette qui utilise le plus de grammes du
    stock : c'est elle qui vide le frigo."""
    table = ingredients()
    faisables, presque = [], []
    for recette in recettes():
        if type_repas and recette["type"] != type_repas:
            continue
        besoins = besoins_recette(recette, portions)
        manquants = manques(besoins, stock)
        if len(manquants) > MANQUANTS_MAX_PRESQUE:
            continue
        utilise = sum(min(b, stock.get(c, 0.0)) for c, b in besoins.items())
        fiche = {
            "id": recette["id"], "nom": recette["nom"], "type": recette["type"],
            "temps_min": recette.get("temps_min"), "macros": recette["macros"],
            "portions": portions,
            "utilise_g": round(utilise),
            "manquants": [
                {"cle": c, "nom": table[c]["nom"] if c in table else c, "grammes": math.ceil(g)}
                for c, g in sorted(manquants.items())
            ],
        }
        (presque if manquants else faisables).append(fiche)
    tri = lambda f: (len(f["manquants"]), -f["utilise_g"])  # noqa: E731
    return {
        "faisables": sorted(faisables, key=tri)[:limite],
        "presque": sorted(presque, key=tri)[:limite],
    }


def bonus_stock(stock: dict[str, float]) -> dict[str, float]:
    """Bonus de score par recette pour le générateur de plan (0 à 0,4) : part
    des besoins de la recette déjà couverte par le stock. Le générateur
    retranche ce bonus à son score, comme le bonus protéines."""
    bonus = {}
    for recette in recettes():
        besoins = besoins_recette(recette)
        total = sum(besoins.values())
        if not total:
            continue
        couvert = sum(min(b, stock.get(c, 0.0)) for c, b in besoins.items())
        if couvert:
            bonus[recette["id"]] = round(0.4 * couvert / total, 3)
    return bonus


# ---------- Déduction après une recette ----------

def deduire(items: list[dict], besoins: dict[str, float]) -> list[dict]:
    """Retire les besoins d'une recette du stock. Renvoie, pour chaque article
    touché, {id, quantity_g_avant, level_avant, quantity_g_apres} : de quoi
    appliquer le changement ET l'annuler.

    Un article connu par niveau passe en grammes après déduction (estimation
    du niveau moins ce qui a été utilisé). On puise d'abord dans l'article le
    moins rempli, pour finir les paquets entamés avant d'en ouvrir un neuf."""
    table = ingredients()
    changements = []
    for cle, besoin in besoins.items():
        restant = besoin
        candidats = sorted(
            (i for i in items if i.get("ingredient_key") == cle),
            key=lambda i: grammes_estimes(i, table),
        )
        for item in candidats:
            if restant <= 0:
                break
            dispo = grammes_estimes(item, table)
            pris = min(dispo, restant)
            restant -= pris
            changements.append({
                "id": item["id"],
                "quantity_g_avant": item.get("quantity_g"),
                "level_avant": item.get("level"),
                "quantity_g_apres": round(dispo - pris, 1),
            })
    return changements


# ---------- Liste de courses moins le stock ----------

def retrancher_stock(liste: dict, stock: dict[str, float]) -> dict:
    """Prend le résultat de liste_courses.liste_de_courses et retire ce qu'on a
    déjà. Les lignes entièrement couvertes partent dans `deja_en_stock`."""
    table = ingredients()
    rayons, deja = [], []
    for rayon in liste["rayons"]:
        lignes = []
        for ligne in rayon["lignes"]:
            dispo = stock.get(ligne["cle"], 0.0)
            reste = ligne["grammes"] - dispo
            if reste <= 0 or (dispo > 0 and ligne["grammes"] <= BESOIN_NEGLIGEABLE_G):
                deja.append({"cle": ligne["cle"], "nom": ligne["nom"]})
                continue
            if dispo > 0:
                ing = table.get(ligne["cle"], {})
                if ing.get("unite") == "piece" and ing.get("poids_piece_g"):
                    quantite = max(1, math.ceil(reste / ing["poids_piece_g"]))
                    ligne = {**ligne, "quantite": quantite, "unite": "pièce" if quantite == 1 else "pièces"}
                else:
                    ligne = {**ligne, "quantite": int(math.ceil(reste / 5) * 5)}
                ligne = {**ligne, "grammes": round(reste), "en_stock_g": round(dispo)}
            lignes.append(ligne)
        if lignes:
            rayons.append({**rayon, "lignes": lignes})
    return {
        **liste,
        "rayons": rayons,
        "nb_lignes": sum(len(r["lignes"]) for r in rayons),
        "deja_en_stock": sorted(deja, key=lambda d: d["nom"]),
    }
