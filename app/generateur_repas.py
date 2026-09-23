"""Génère un plan de repas à partir du catalogue de recettes.

Entrées : une cible calorique journalière (celle du profil, Mifflin-St Jeor +
activité + objectif de poids — voir routers/profile.py), une cible protéines,
un horizon d'une à quatre semaines et deux réglages de répétition :

- `max_repetitions_semaine` : combien de fois un même plat peut revenir dans
  une semaine (1 = tout différent, 2-3 = batch cooking, courses moins chères) ;
- `repetitions_entre_semaines` : sur un plan d'un mois, autoriser ou non qu'une
  semaine reprenne des plats d'une autre.

Méthode : pour chaque repas de chaque jour, on tire une recette parmi les
meilleures d'un score qui combine l'écart à la cible calorique du créneau, une
pénalité de répétition et un bonus protéines, puis on ajuste les portions du
jour pour tomber sur la cible. Un tirage aléatoire parmi les meilleures (et non
la meilleure) évite que deux semaines se ressemblent.

Rien n'est écrit en base ici : le générateur propose, l'utilisateur valide, et
c'est seulement le PUT /diet/plan qui enregistre.
"""
import random

from .recettes import recettes

# Part du budget calorique de la journée par créneau, renormalisée selon les
# créneaux retenus (un plan sans petit-déjeuner reporte sa part sur les autres).
PARTS = {"petit-dejeuner": 0.25, "dejeuner": 0.35, "collation": 0.10, "diner": 0.30}

# Marge d'ajustement des portions : au-delà, on préfère changer de recette
# plutôt que de servir une assiette deux fois trop grosse.
PORTION_MINI, PORTION_MAXI = 0.85, 1.25
TOLERANCE_KCAL = 0.07  # 7 % d'écart accepté sur la journée
TIRAGES_PAR_JOUR = 12  # combinaisons essayées, la meilleure est gardée


# Au-delà de ce budget, trois repas et une collation ne suffisent plus à tenir
# la cible sans servir des assiettes démesurées : on ajoute une 2e collation.
SEUIL_DEUXIEME_COLLATION = 2600


def _creneaux(avec_petit_dejeuner: bool, avec_collation: bool,
              cible_kcal: int) -> list[tuple[str, float]]:
    """Créneaux de la journée et part du budget de chacun. Une liste et non un
    dict : la collation peut apparaître deux fois."""
    actifs = ["dejeuner", "diner"]
    if avec_petit_dejeuner:
        actifs.insert(0, "petit-dejeuner")
    if avec_collation:
        actifs.append("collation")
        if cible_kcal >= SEUIL_DEUXIEME_COLLATION:
            actifs.append("collation")
    total = sum(PARTS[c] for c in actifs)
    return [(c, PARTS[c] / total) for c in actifs]


def _par_type() -> dict[str, list[dict]]:
    catalogue: dict[str, list[dict]] = {}
    for recette in recettes():
        catalogue.setdefault(recette["type"], []).append(recette)
    return catalogue


def _score(recette: dict, cible_creneau: float, utilisations: int,
           deficit_proteines: float) -> float:
    macros = recette["macros"]
    ecart = abs(macros["calories"] - cible_creneau) / max(cible_creneau, 1)
    penalite = 0.20 * utilisations  # revenir une 2e fois coûte, sans l'interdire
    bonus = 0.0
    if deficit_proteines > 0:
        # Journée en retard sur les protéines : on favorise les plats qui en
        # apportent beaucoup par calorie.
        densite = macros["proteines"] / max(macros["calories"], 1)
        bonus = min(0.30, densite * 15)
    return ecart + penalite - bonus


def _choisir(candidats: list[dict], cible_creneau: float, compteurs: dict[str, int],
             interdits: set[str], max_repetitions: int, deficit_proteines: float,
             tirage: random.Random) -> dict | None:
    eligibles = [r for r in candidats
                 if r["id"] not in interdits
                 and compteurs.get(r["id"], 0) < max_repetitions]
    if not eligibles:
        # Contrainte de répétition intenable (catalogue trop petit pour
        # l'horizon demandé) : on la relâche plutôt que de rendre un plan
        # incomplet — l'appelant en est informé par `assouplissements`.
        eligibles = [r for r in candidats if r["id"] not in interdits] or candidats
    classes = sorted(eligibles, key=lambda r: _score(
        r, cible_creneau, compteurs.get(r["id"], 0), deficit_proteines))
    return tirage.choice(classes[:6]) if classes else None


def _macros_ajustees(recette: dict, portions: float) -> dict:
    macros = recette["macros"]
    return {cle: round(valeur * portions) for cle, valeur in macros.items()}


def _construire_jour(catalogue, parts, cible_kcal, cible_proteines, compteurs,
                     interdits, max_repetitions, tirage):
    """Meilleure combinaison de repas pour une journée, portions ajustées."""
    meilleure, meilleur_ecart = None, None

    for _ in range(TIRAGES_PAR_JOUR):
        choix, proteines_cumulees = [], 0.0
        for creneau, part in parts:
            deficit = cible_proteines - proteines_cumulees - (cible_proteines * part)
            recette = _choisir(catalogue.get(creneau, []), cible_kcal * part, compteurs,
                               interdits, max_repetitions, deficit, tirage)
            if recette is None:
                break
            choix.append((creneau, recette))
            proteines_cumulees += recette["macros"]["proteines"]
        if len(choix) != len(parts):
            continue

        brut = sum(r["macros"]["calories"] for _, r in choix)
        portions = min(PORTION_MAXI, max(PORTION_MINI, cible_kcal / max(brut, 1)))
        portions = round(portions * 20) / 20  # pas de 0,05
        ecart = abs(brut * portions - cible_kcal) / cible_kcal
        # Une journée trop pauvre en protéines est pénalisée comme un écart
        # calorique : mieux vaut retirer que livrer un plan sous-protéiné.
        if proteines_cumulees * portions < cible_proteines * 0.85:
            ecart += 0.10

        if meilleur_ecart is None or ecart < meilleur_ecart:
            meilleure, meilleur_ecart = (choix, portions), ecart
        if ecart <= TOLERANCE_KCAL:
            break

    return meilleure, meilleur_ecart


def generer_plan(
    cible_kcal: int,
    cible_proteines: int,
    nb_semaines: int = 1,
    avec_petit_dejeuner: bool = True,
    avec_collation: bool = True,
    max_repetitions_semaine: int = 2,
    repetitions_entre_semaines: bool = True,
    graine: int | None = None,
) -> dict:
    """Plan proposé, non enregistré. Voir l'en-tête du module pour la méthode."""
    if not 1 <= nb_semaines <= 4:
        raise ValueError("nb_semaines doit être compris entre 1 et 4")
    if max_repetitions_semaine < 1:
        raise ValueError("max_repetitions_semaine doit valoir au moins 1")

    catalogue = _par_type()
    parts = _creneaux(avec_petit_dejeuner, avec_collation, cible_kcal)
    manquants = [c for c, _ in parts if not catalogue.get(c)]
    if manquants:
        raise ValueError(f"aucune recette pour : {', '.join(manquants)}")

    tirage = random.Random(graine)
    semaines, ecarts, assouplissements = [], [], 0
    deja_vues: set[str] = set()  # tous plans confondus, si pas de répétition entre semaines

    for semaine in range(nb_semaines):
        compteurs: dict[str, int] = {}
        interdits = set(deja_vues) if not repetitions_entre_semaines else set()
        jours = []
        for jour in range(7):
            resultat, ecart = _construire_jour(
                catalogue, parts, cible_kcal, cible_proteines, compteurs,
                interdits, max_repetitions_semaine, tirage)
            if resultat is None:
                raise ValueError("catalogue insuffisant pour générer ce plan")
            (choix, portions) = resultat
            ecarts.append(ecart)

            repas = []
            for creneau, recette in choix:
                if compteurs.get(recette["id"], 0) >= max_repetitions_semaine:
                    assouplissements += 1
                compteurs[recette["id"]] = compteurs.get(recette["id"], 0) + 1
                deja_vues.add(recette["id"])
                repas.append({
                    "meal_type": creneau,
                    "recipe_id": recette["id"],
                    "label": recette["nom"],
                    "portions": portions,
                    "temps_min": recette.get("temps_min"),
                    **_macros_ajustees(recette, portions),
                })
            jours.append({
                "day_index": jour,
                "repas": repas,
                "totaux": {
                    cle: sum(r[cle] for r in repas)
                    for cle in ("calories", "proteines", "glucides", "lipides")
                },
            })
        semaines.append({"week_index": semaine, "jours": jours})

    return {
        "cible": {"calories": cible_kcal, "proteines": cible_proteines},
        "semaines": semaines,
        "ecart_moyen_pourcent": round(100 * sum(ecarts) / len(ecarts), 1),
        "ecart_maxi_pourcent": round(100 * max(ecarts), 1),
        # Nombre de fois où la contrainte de répétition a dû être relâchée faute
        # de recettes disponibles : à remonter à l'utilisateur, c'est le signe
        # qu'il demande plus de variété que le catalogue n'en contient.
        "assouplissements": assouplissements,
    }
