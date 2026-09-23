"""Semaine type du plan d'alimentation « 80 kg, oct.-déc. ».

Données recopiées de « Plan_Alimentation_80kg_Oct-Dec.xlsx » (feuille « Mois
type alimentation »), dont les 4 semaines sont identiques : une seule semaine
est donc conservée, répétée à l'identique toutes les semaines.

Ce module sert le catalogue de recettes (routers/recipes.py) et le repli quand
l'utilisateur n'a pas encore importé le plan dans son compte. Le plan importé,
lui, vit en base (models.MealPlanEntry) et est écrit par
importer_alimentation.py, qui relit le classeur : c'est le classeur qui fait
foi, ce fichier n'en est qu'une copie pour l'app.

Macros en grammes. Le plan ne comporte pas de petit-déjeuner.
"""

PLAN_NOM = "Plan alimentation 80 kg (oct.-déc.)"

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# day_index (0 = lundi) -> repas prévus, dans l'ordre de la journée.
# Chaque repas : (type, libellé, kcal, protéines, glucides, lipides).
SEMAINE_TYPE = {
    0: [  # Lundi
        ("dejeuner", "Poulet 220g + patate douce 300g + brocolis 200g + huile 10g", 779, 78, 72, 19),
        ("collation", "Skyr 250g + banane", 255, 26, 37, 0),
        ("diner", "Saumon 200g + courgettes 250g + carottes 150g + PDT 150g + huile 10g", 721, 51, 47, 37),
    ],
    1: [  # Mardi
        ("dejeuner", "Chili 200g boeuf + haricots rouges + riz", 800, 60, 85, 18),
        ("collation", "Fromage blanc 250g + amandes 25g", 300, 25, 10, 15),
        ("diner", "Omelette 4 oeufs + champignons + pain complet", 700, 40, 40, 30),
    ],
    2: [  # Mercredi
        ("dejeuner", "Dinde 220g + haricots verts 300g + PDT 250g", 700, 65, 55, 15),
        ("collation", "Skyr + poire", 250, 25, 30, 0),
        ("diner", "Cabillaud + ratatouille + riz", 750, 55, 75, 12),
    ],
    3: [  # Jeudi
        ("dejeuner", "Poulet mediterraneen + courgette aubergine tomate", 740, 70, 50, 20),
        ("collation", "Fromage blanc + kiwi", 220, 22, 20, 0),
        ("diner", "Steak 200g + brocolis + PDT au four", 760, 55, 50, 25),
    ],
    4: [  # Vendredi
        ("dejeuner", "Pates complètes bolognaise light", 820, 60, 90, 18),
        ("collation", "Skyr + orange", 230, 25, 20, 0),
        ("diner", "Colin + carottes rôties + haricots verts", 650, 50, 35, 18),
    ],
    5: [  # Samedi
        ("dejeuner", "Burger maison + PDT four", 850, 55, 80, 28),
        ("collation", "Fromage blanc + noix", 300, 22, 12, 18),
        ("diner", "Wok de poulet + nouilles + poivrons", 750, 55, 60, 20),
    ],
    6: [  # Dimanche
        ("dejeuner", "Roti de dinde + carottes + courgettes + PDT", 780, 65, 60, 18),
        ("collation", "Skyr + banane", 255, 26, 37, 0),
        ("diner", "Soupe legumes + poisson blanc", 600, 50, 25, 12),
    ],
}


def totaux_du_jour(day_index: int) -> dict:
    """Somme kcal/macros des repas prévus ce jour-là."""
    repas = SEMAINE_TYPE.get(day_index, [])
    return {
        "calories": sum(r[2] for r in repas),
        "proteines": sum(r[3] for r in repas),
        "glucides": sum(r[4] for r in repas),
        "lipides": sum(r[5] for r in repas),
    }
