"""Convertit pdj_collations_raw.json (Jow, eatthismuch, BBC Good Food, Jamie Oliver) en lot suivi-app.

Même méthode que convertir_autres.py : 1 portion, clés CIQUAL, poids standard des pièces,
densités des cuillères, comparaison aux macros du site (huile « de placard » Jow testée avec et sans).
Le cottage cheese, absent de CIQUAL, devient du fromage blanc 3 % (les noms le disent).
"""
import json
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
BACKEND = ICI.parent.parent
sys.path.insert(0, str(BACKEND))
from app.recettes import macros_recette  # noqa: E402

HUILE = 0.92
# nom -> (clé, g par unité non-gramme [densité ml ou poids pièce], facteur, grammes si quantité absente)
C = {
    # Jow
    "Tortilla (blé)": ("tortilla", 45, 1, None), "Pain de campagne (tranché)": ("pain_campagne", 40, 1, None), "Avocat": ("avocat", 150, 1, None),
    "Œuf": ("oeuf", 50, 1, None), "Jambon cru (Prosciutto)": ("jambon_cru", 15, 1, None),
    "Coriandre (frais)": (None,), "Huile d'olive": ("huile_olive", HUILE, 1, None),
    "Tartine de seigle": ("pain_seigle", 25, 1, None), "Fromage frais": ("fromage_frais", 1, 1, None),
    "Jambon blanc": ("jambon_blanc", 40, 1, None), "Salade (Mélange)": ("salade", 1, 1, 30),
    "Ciboulette": (None,), "Kiwi jaune": ("kiwi", 75, 1, None),
    "Avoine (flocons)": ("flocons_avoine", 1, 1, None), "Lait": ("lait_demi", 1, 1, None),
    "Sirop d'érable": ("sirop_erable", 1.33, 1, None), "Chocolat noir": ("chocolat_noir", 1, 1, None),
    "Noix": ("noix", 1, 1, None), "English muffin": ("muffin_anglais", 60, 1, None),
    "Beurre demi-sel": ("beurre", 1, 1, None), "Comté": ("comte", 1, 1, None),
    "Crème fraîche": ("creme_legere", 1, 1, None), "Saumon (fumé)": ("saumon_fume", 25, 1, None),
    "Salade (mâche)": ("salade", 1, 1, 30), "Pain de mie": ("pain_mie", 25, 1, None),
    "Thon à l'ail": ("thon_naturel", 1, 1, None), "Radis": ("radis", 1, 1, None),
    "Concombre": ("concombre", 300, 1, None), "Feta": ("feta", 1, 1, None),
    "Galette bretonne": ("galette_sarrasin", 60, 1, None), "Fromage râpé": ("gruyere", 1, 1, None),
    "Beurre": ("beurre", 1, 1, 5), "Patate douce": ("patate_douce", 1, 1, None),
    "Ail": ("ail", 5, 1, None), "Piment d'Espelette": (None,), "Persil (frais)": (None,),
    "Pain bagel": ("bagel", 90, 1, None), "Cheddar (tranches)": ("cheddar", 20, 1, None),
    "Lard (tranches)": ("lardons", 15, 1, None), "Épinard (frais)": ("epinard", 1, 1, 30),
    "Citron jaune": ("citron", 60, 1, None), "Tomate": ("tomate", 120, 1, None),
    "Mozzarella (boule)": ("mozzarella", 125, 1, None), "Sauce pesto": ("pesto", 1, 1, None),
    "Crème balsamique": ("vinaigre_balsamique", 1.3, 1, None),
    "Pois chiches (cuits)": ("pois_chiches", 1, 1, None), "Cumin (moulu)": (None,),
    "Betterave (cuite)": ("betterave", 150, 1, None), "Tahini": ("tahin", 1, 1, None),
    "Truite fumée": ("truite_fumee", 25, 1, None), "Cottage cheese": ("fromage_blanc_3", 1, 1, None),
    "Tomates séchées": ("tomate_sechee", 1, 1, None),
    "Filet de maquereau aux tomates séchées (boîte)": ("maquereau", 1, 1, None),
    "Feuille de brick": ("feuille_brick", 12, 1, None),
    "Petits pois (surgelés)": ("petit_pois", 1, 1, None), "Oignon rouge": ("oignon", 120, 1, None),
    "Pâte de curry (vert)": (None,), "Lait de coco": ("lait_coco", 1, 1, None),
    "Yaourt Grec": ("yaourt_grec", 1.03, 1, None), "Miel (liquide)": ("miel", 1.4, 1, None),
    "Pistaches (émondées)": ("pistache", 1, 1, None),
    # eatthismuch (grammes)
    "Whole wheat bread": ("pain_complet", 1, 1, None), "Cottage cheese (1% milkfat)": ("fromage_blanc_3", 1, 1, None),
    "Tomatoes (red, raw)": ("tomate", 1, 1, None), "Ham (sliced, regular, 11% fat)": ("jambon_blanc", 1, 1, None),
    "Avocado (raw)": ("avocat", 1, 1, None), "Cayenne pepper": (None,),
    "Rolled oats (dry oatmeal, Quaker brand)": ("flocons_avoine", 1, 1, None),
    "Rolled oats (dry oatmeal)": ("flocons_avoine", 1, 1, None),
    "Almond milk": ("boisson_amande", 1, 1, None), "Greek yogurt (plain, nonfat)": ("skyr", 1, 1, None),
    "Peanut butter (smooth, unsalted)": ("beurre_cacahuete", 1, 1, None), "Banana": ("banane", 1, 1, None),
    "Semisweet chocolate chips": ("chocolat_noir", 1, 1, None), "Egg (whole)": ("oeuf", 1, 1, None),
    "Yellow mustard": ("moutarde", 1, 1, None), "Mayonnaise (regular, salted)": ("mayonnaise", 1, 1, None),
    "Whole wheat pita bread": ("pain_pita", 1, 1, None),
    "Mozzarella cheese (part-skim)": ("mozzarella", 1, 1, None), "Spinach (raw)": ("epinard", 1, 1, None),
    "Salt (table)": (None,), "Black pepper (ground)": (None,), "Oregano (dried)": (None,),
    "Parmesan cheese (shredded)": ("parmesan", 1, 1, None),
    "Hummus (commercially prepared)": ("houmous", 1, 1, None), "Coconut oil": ("huile_colza", 1, 1, None),
    "Peach": ("peche", 1, 1, None), "Honey": ("miel", 1, 1, None), "Cinnamon (ground)": ("cannelle", 1, 1, None),
    "2% milk": ("lait_demi", 1, 1, None), "Ice cubes": (None,),
    "European grapes (raw, red or green)": ("raisin", 1, 1, None), "Apple (with skin)": ("pomme", 1, 1, None),
    "English walnuts": ("noix", 1, 1, None),
    "Light tuna (canned in water, drained)": ("thon_naturel", 1, 1, None),
    "Dill pickles": (None,), "Jalapeno peppers (raw)": (None,), "Sriracha": (None,),
    "Onion (raw)": ("oignon", 1, 1, None), "Curry powder": (None,),
    "Pears (raw)": ("poire", 1, 1, None), "Ricotta cheese (part-skim milk)": ("ricotta", 1, 1, None),
    "Cream cheese (low fat)": ("fromage_frais", 1, 1, None),
    "Turkey (deli-sliced, rotisserie, white meat)": ("blanc_dinde", 1, 1, None),
    "Cucumber (raw, with peel)": ("concombre", 1, 1, None), "Cucumber (raw, peeled)": ("concombre", 1, 1, None),
    "Chickpeas (canned)": ("pois_chiches", 1, 1, None), "Red bell pepper (raw)": ("poivron", 1, 1, None),
    "Pistachios (raw)": ("pistache", 1, 1, None),
    "Dark chocolate (70-85% cacao solids)": ("chocolat_noir", 1, 1, None),
    "Strawberries (raw)": ("fraise", 1, 1, None), "Blueberries (raw)": ("myrtille", 1, 1, None),
    "Carrots (raw)": ("carotte", 1, 1, None), "Cheddar cheese": ("cheddar", 1, 1, None),
    "Almonds (raw)": ("amande", 1, 1, None), "Brown sugar": (None,),
    "Flour tortillas": ("tortilla", 1, 1, None), "Marinara sauce": ("sauce_tomate", 1, 1, None),
    "Smoked salmon (Chinook salmon)": ("saumon_fume", 1, 1, None),
    # BBC Good Food / Jamie Oliver
    "porridge oat": ("flocons_avoine", 1, 1, None),
    "0% fat probiotic yogurt (pot)": ("yaourt_nature", 1, 1, None),
    "chickpeas (can)": ("pois_chiches", 1, 0.6, None),  # boîte de 400 g, ~240 g égouttés
    "olive oil": ("huile_olive", HUILE, 1, 2), "ground cumin": (None,), "paprika": (None,),
    "large eggs": ("oeuf", 60, 1, None), "basil": (None,),
    "pitted Kalamata olives": ("olive_noire", 4, 1, None),
    "extra virgin olive oil": ("huile_olive", HUILE, 1, None), "cider vinegar": ("vinaigre_cidre", 1, 1, None),
    "wholemeal pitta bread": ("pain_pita", 60, 1, None),
    "cooked skinless chicken breast": ("poulet_filet", 1, 1.33, None),  # cuit -> cru
    "cucumber cut into chunks": ("concombre", 300, 1, None),
    "cherry tomatoes halved": ("tomate_cerise", 15, 1, None),
    "rye bread": ("pain_seigle", 1, 1, None), "free-range eggs (medium)": ("oeuf", 50, 1, None),
    "baby spinach": ("epinard", 1, 1, None),
    "smoked salmon, from sustainable sources": ("saumon_fume", 1, 1, None),
    "lemon": ("citron", 60, 1, None), "cottage cheese": ("fromage_blanc_3", 1, 1, None), "chives": (None,),
}

F = {
    0: ("pdj-tacos-oeufs-avocat-jambon-cru-jow", "Tacos du matin : œufs brouillés, avocat et jambon cru", "petit-dejeuner",
        ["poele", "sale", "rapide"], [
        "Réchauffer la tortilla 30 s de chaque côté à la poêle.",
        "Écraser l'avocat sur la tortilla, brouiller les œufs dans un filet d'huile.",
        "Garnir d'œufs brouillés et de jambon cru, parsemer de coriandre."]),
    1: ("pdj-tartines-seigle-oeufs-fromage-frais-jambon-jow", "Tartines de seigle, œufs brouillés, fromage frais et jambon", "petit-dejeuner",
        ["poele", "sale", "rapide"], [
        "Battre les œufs avec sel et poivre, les cuire 4 à 5 min à feu doux en remuant.",
        "Tartiner le fromage frais sur le pain de seigle, ajouter les œufs, le jambon et la ciboulette."]),
    2: ("pdj-porridge-chocolat-kiwi-jow", "Porridge au chocolat noir, kiwi et noix", "petit-dejeuner",
        ["sucre", "vegetarien", "rapide"], [
        "Chauffer le lait, ajouter les flocons et cuire 3 à 4 min à feu doux.",
        "Servir avec le kiwi en rondelles, le chocolat noir et les noix concassées, et un filet de sirop d'érable."]),
    3: ("pdj-oeuf-coque-mouillettes-comte-jow", "Œuf à la coque, mouillettes beurrées et comté", "petit-dejeuner",
        ["sale", "vegetarien", "rapide"], [
        "Plonger l'œuf 3 à 4 min dans l'eau bouillante.",
        "Toaster le muffin, le beurrer et le couper en mouillettes ; servir avec le comté."]),
    4: ("pdj-oeufs-cocotte-saumon-fume-jow", "Œufs cocotte au saumon fumé", "petit-dejeuner",
        ["four", "sale", "poisson"], [
        "Préchauffer le four à 180 °C et huiler 2 ramequins.",
        "Y répartir le saumon fumé et la crème, casser un œuf par-dessus, poivrer.",
        "Cuire 10 à 15 min, jusqu'à ce que le blanc soit pris. Servir avec le pain grillé et la salade."]),
    5: ("pdj-sandwich-jambon-fromage-blanc-tomate-etm", "Sandwich complet jambon, fromage blanc et tomate", "petit-dejeuner",
        ["sans-cuisson", "rapide", "transportable"], [
        "Griller le pain et tartiner chaque tranche de fromage blanc.",
        "Garnir de jambon et de rondelles de tomate, refermer."]),
    7: ("pdj-omelette-saumon-fume-seigle-jamie", "Omelette roulée au saumon fumé et pain de seigle", "petit-dejeuner",
        ["poele", "sale", "poisson"], [
        "Émietter le pain de seigle dans une poêle avec un filet d'huile et le faire dorer, ajouter les épinards jusqu'à ce qu'ils tombent.",
        "Verser les œufs battus, cuire 1 à 2 min, garnir de saumon fumé et de fromage blanc, rouler et servir avec du citron."]),
    8: ("pdj-overnight-oats-banane-cacahuete-etm", "Overnight oats banane, beurre de cacahuète et chocolat", "petit-dejeuner",
        ["prepare-la-veille", "sans-cuisson", "sucre", "vegetarien"], [
        "Mélanger flocons, boisson d'amande, fromage blanc 0 %, beurre de cacahuète, banane et chocolat dans un bocal.",
        "Couvrir et laisser au frais une nuit (au moins 4 h), mélanger avant de servir."]),
    9: ("pdj-tartine-thon-fromage-frais-radis-jow", "Tartine thon, fromage frais, radis et feta", "petit-dejeuner",
        ["sans-cuisson", "rapide", "poisson"], [
        "Griller le pain et le tartiner de fromage frais.",
        "Ajouter concombre et radis en fines rondelles, le thon émietté et la feta, un filet d'huile d'olive."]),
    10: ("pdj-galette-complete-jow", "Galette complète jambon, œuf et fromage", "petit-dejeuner",
         ["poele", "sale", "rapide"], [
        "Faire fondre un peu de beurre dans une grande poêle, poser la galette et casser l'œuf au centre.",
        "Quand le blanc prend, ajouter le jambon et le fromage râpé, replier les bords et servir."]),
    11: ("pdj-tartines-oeuf-mimosa-moutarde-etm", "Tartines d'œuf dur écrasé à la moutarde", "petit-dejeuner",
         ["sale", "vegetarien", "rapide"], [
        "Cuire l'œuf 10 min, le refroidir, l'écaler et l'écraser.",
        "Mélanger avec la moutarde et la mayonnaise, étaler sur le pain grillé."]),
    12: ("pdj-pizza-pita-oeuf-epinards-etm", "Pita façon pizza à l'œuf et aux épinards", "petit-dejeuner",
         ["four", "sale", "vegetarien"], [
        "Parsemer les pitas de mozzarella et d'origan, disposer les épinards en nid.",
        "Casser un œuf au centre et passer 6 à 8 min sous le gril, puis parsemer de parmesan."]),
    13: ("pdj-oeufs-brouilles-houmous-etm", "Œufs brouillés au houmous", "petit-dejeuner",
         ["poele", "sale", "vegetarien", "rapide"], [
        "Brouiller les œufs battus dans l'huile chaude en ramenant les bords vers le centre.",
        "Incorporer le houmous en fin de cuisson et servir aussitôt."]),
    14: ("pdj-smoothie-peche-yaourt-etm", "Smoothie pêche, fromage blanc et cannelle", "petit-dejeuner",
         ["sans-cuisson", "sucre", "vegetarien", "rapide"], [
        "Mettre la pêche, le miel, la cannelle, le lait, le fromage blanc 0 % et quelques glaçons dans un blender.",
        "Mixer jusqu'à obtenir une texture lisse et servir aussitôt."]),
    15: ("pdj-fromage-blanc-raisin-pomme-noix-etm", "Fromage blanc au raisin, pomme, noix et cannelle", "petit-dejeuner",
         ["sans-cuisson", "sucre", "vegetarien", "rapide"], [
        "Couper la pomme en dés.",
        "Mélanger le fromage blanc avec le raisin, la pomme, les noix et la cannelle."]),
    16: ("pdj-poelee-patate-douce-feta-oeuf-jow", "Poêlée de patate douce, feta et œuf au plat", "petit-dejeuner",
         ["poele", "sale", "vegetarien"], [
        "Faire revenir la patate douce en dés 10 à 12 min dans l'huile, ajouter l'ail et un fond d'eau, couvrir 10 min.",
        "Cuire l'œuf au plat dans un peu de beurre.",
        "Servir la patate douce avec la feta émiettée, l'œuf et le piment d'Espelette."]),
    17: ("pdj-bagel-oeufs-lard-cheddar-jow", "Bagel aux œufs, lard grillé et cheddar", "petit-dejeuner",
         ["poele", "sale"], [
        "Griller les tranches de lard 2 min par face, puis cuire les œufs battus dans la même poêle et y faire fondre le cheddar.",
        "Toaster le bagel et le garnir de lard et d'œufs au fromage."]),
    18: ("pdj-wrap-saumon-fume-fromage-frais-jow", "Wrap de saumon fumé, fromage frais et épinards", "petit-dejeuner",
         ["sans-cuisson", "rapide", "poisson", "transportable"], [
        "Tartiner la tortilla de fromage frais.",
        "Ajouter le saumon fumé, les pousses d'épinards, le concombre en rondelles et un trait de citron, puis rouler."]),
    19: ("pdj-tartine-caprese-pesto-jow", "Tartine caprese au pesto", "petit-dejeuner",
         ["sans-cuisson", "vegetarien", "rapide"], [
        "Griller le pain et le tartiner de pesto.",
        "Ajouter tomate et mozzarella en tranches, un filet d'huile d'olive et de crème balsamique."]),
    20: ("col-porridge-yaourt-cremeux-bbc", "Porridge crémeux au yaourt", "collation",
         ["sucre", "vegetarien", "rapide"], [
        "Cuire les flocons dans 20 cl d'eau à feu doux jusqu'à épaississement.",
        "Incorporer le yaourt et servir."]),
    21: ("col-houmous-betterave-jow", "Houmous à la betterave", "collation",
         ["sans-cuisson", "vegetalien", "vegetarien"], [
        "Mixer pois chiches, ail, huile d'olive, tahin, cumin et betterave jusqu'à obtenir une texture lisse, en ajoutant un peu d'eau si besoin.",
        "Assaisonner et servir avec un filet d'huile d'olive."]),
    22: ("col-pois-chiches-grilles-epices-bbc", "Pois chiches grillés au cumin et paprika", "collation",
         ["four", "croquant", "vegetalien", "vegetarien", "transportable"], [
        "Égoutter, rincer et sécher les pois chiches, les enrober d'huile et d'épices.",
        "Les griller 40 à 45 min à 180 °C en remuant de temps en temps."]),
    23: ("col-fromage-blanc-concombre-saumon-fume-etm", "Fromage blanc au concombre et saumon fumé", "collation",
         ["sans-cuisson", "rapide", "poisson"], [
        "Couper le concombre en dés et le saumon fumé en lanières.",
        "Mélanger avec le fromage blanc 0 %."]),
    24: ("col-oeufs-mimosa-basilic-olives-bbc", "Œufs mimosa au basilic et aux olives", "collation",
         ["vegetarien", "transportable"], [
        "Cuire les œufs 8 min, les refroidir, les écaler et retirer les jaunes.",
        "Mixer basilic, olives, huile et vinaigre, écraser avec les jaunes et garnir les blancs."]),
    25: ("col-bol-thon-fromage-blanc-cornichons-etm", "Bol de thon, fromage blanc et cornichons", "collation",
         ["sans-cuisson", "rapide", "poisson"], [
        "Égoutter le thon, hacher cornichons et piment.",
        "Mélanger avec le fromage blanc (et un trait de sauce piquante si on veut)."]),
    26: ("col-salade-thon-curry-etm", "Salade de thon au curry", "collation",
         ["sans-cuisson", "rapide", "poisson"], [
        "Hacher l'oignon et égoutter le thon.",
        "Mélanger avec la mayonnaise et le curry."]),
    27: ("col-tartines-seigle-fromage-blanc-truite-jow", "Tartines de seigle, fromage blanc et truite fumée", "collation",
         ["sans-cuisson", "rapide", "poisson"], [
        "Tartiner le pain de seigle de fromage blanc.",
        "Ajouter la truite fumée et les tomates séchées en morceaux, servir avec un peu de salade assaisonnée."]),
    29: ("col-veloute-petits-pois-coco-curry-jow", "Velouté de petits pois au lait de coco et curry vert", "collation",
         ["soupe", "vegetalien", "vegetarien", "rapide"], [
        "Faire revenir oignon et ail 2 min dans l'huile.",
        "Ajouter petits pois, lait de coco, pâte de curry et 12 cl d'eau, mijoter 8 min à couvert, puis mixer."]),
    30: ("col-tartine-ricotta-poire-miel-etm", "Tartine ricotta, poire et miel", "collation",
         ["sucre", "vegetarien", "rapide"], [
        "Griller le pain et le tartiner de ricotta.",
        "Ajouter la poire en lamelles et un filet de miel."]),
    31: ("col-barquettes-concombre-dinde-fromage-frais-etm", "Barquettes de concombre, fromage frais et dinde", "collation",
         ["sans-cuisson", "rapide", "transportable"], [
        "Couper le concombre en deux dans la longueur et l'évider.",
        "Tartiner l'intérieur de fromage frais, garnir de dinde roulée et refermer."]),
    32: ("col-sandwich-pois-chiches-ecrases-etm", "Sandwich de pois chiches écrasés et crudités", "collation",
         ["sans-cuisson", "vegetalien", "vegetarien", "transportable"], [
        "Écraser les pois chiches à la fourchette, émincer poivron et concombre.",
        "Griller le pain et garnir de pois chiches et de légumes."]),
    33: ("col-assiette-fromage-blanc-pistaches-chocolat-fruits-etm", "Assiette fromage blanc, pistaches, chocolat et fruits rouges", "collation",
         ["sans-cuisson", "sucre", "vegetarien", "rapide"], [
        "Répartir le fromage blanc, les pistaches, le chocolat noir, les fraises et les myrtilles dans une boîte ou une assiette.",
        "Se déguste tel quel."]),
    34: ("col-assiette-carottes-pomme-cheddar-amandes-etm", "Assiette carottes, pomme, cheddar et amandes", "collation",
         ["sans-cuisson", "vegetarien", "transportable"], [
        "Couper la pomme en quartiers et les carottes en bâtonnets.",
        "Servir avec le cheddar et les amandes."]),
    36: ("col-creme-feta-miel-pistaches-jow", "Crème de feta au miel et pistaches", "collation",
         ["sans-cuisson", "vegetarien"], [
        "Mixer la feta, le yaourt grec, l'ail et la moitié du miel jusqu'à obtenir une crème lisse.",
        "Servir parsemé de pistaches concassées, du reste de miel et d'un filet d'huile d'olive."]),
    37: ("col-smoothie-banane-cannelle-avoine-etm", "Smoothie banane, cannelle et avoine", "collation",
         ["sans-cuisson", "sucre", "vegetarien", "rapide"], [
        "Mixer boisson d'amande, fromage blanc 0 %, flocons, cannelle et banane jusqu'à obtenir une texture lisse.",
        "Servir aussitôt."]),
    38: ("col-wrap-facon-pizza-etm", "Wrap façon pizza aux épinards", "collation",
         ["vegetarien", "rapide"], [
        "Étaler la sauce tomate sur la tortilla, ajouter les épinards et la mozzarella.",
        "Passer 1 min au micro-ondes (ou à la poêle) jusqu'à ce que le fromage fonde, puis rouler."]),
    39: ("col-demi-pita-poulet-crudites-bbc", "Demi-pita au poulet et crudités", "collation",
         ["sans-cuisson", "rapide", "transportable"], [
        "Ouvrir la demi-pita.",
        "La garnir de poulet cuit, de concombre en morceaux et de tomates cerises coupées en deux."]),
}


def convertir(ing):
    spec = C.get(ing["nom"])
    if spec is None:
        raise SystemExit(f"sans correspondance : {ing['nom']!r}")
    if spec[0] is None:
        return None, 0
    cle, par_unite, facteur, defaut = spec
    q = ing.get("quantite")
    if q is None:
        return (cle, defaut) if defaut else (None, 0)
    return cle, q * (1 if ing.get("unite") == "g" else par_unite) * facteur


def main():
    brut = json.loads((ICI / "pdj_collations_raw.json").read_text(encoding="utf-8"))["recettes"]
    lot = []
    for i, (ident, nom, type_repas, tags, etapes) in F.items():
        src = brut[i]
        n = src["servings"]
        grammes, placard = {}, {}
        for ing in src["ingredients"]:
            cle, g = convertir(ing)
            if cle:
                grammes[cle] = grammes.get(cle, 0) + g / n
                if ing.get("placard_jow"):
                    placard[cle] = placard.get(cle, 0) + g / n
        ingredients = [{"cle": c, "quantite_g": max(1, round(g))} for c, g in grammes.items() if g >= 0.5]
        m = src["macros_par_portion"]
        temps = 5 if "prepare-la-veille" in tags else (src.get("total_min") or 0)
        recette = {
            "id": ident, "nom": nom, "type": type_repas, "portions": 1, "temps_min": temps,
            "ingredients": ingredients, "etapes": etapes, "tags": tags,
            "origine": {
                "site": src["site"], "url": src["url"], "nom_original": src["nom_original"],
                "portions_originales": n,
                "macros_annoncees": {k: m.get(k) for k in ("calories", "proteines", "glucides", "lipides", "fibres")},
            },
        }
        c = macros_recette(recette)
        e = (c["calories"] - m["calories"]) / m["calories"]
        if placard:
            sans = {**recette, "ingredients": [
                {"cle": l["cle"], "quantite_g": l["quantite_g"] - placard.get(l["cle"], 0)} for l in ingredients]}
            e_sans = (macros_recette(sans)["calories"] - m["calories"]) / m["calories"]
            if abs(e_sans) < abs(e):
                e = e_sans
                recette["origine"]["remarque"] = ("Macros du site hors huile/beurre de placard ; "
                                                  "ils sont comptés dans les macros de l'app.")
        if any(ing["nom"].lower().startswith("cottage") for ing in src["ingredients"]):
            recette["origine"]["remarque"] = (recette["origine"].get("remarque", "") +
                                              " Cottage cheese (absent de CIQUAL) remplacé par du fromage blanc 3 %.").strip()
        drapeau = "  <<" if abs(e) > 0.15 else ""
        print(f"{i:2} {type_repas[:4]} {nom[:50]:50} site {m['calories']:5.0f}/{m['proteines']:3.0f}P  "
              f"ciqual {c['calories']:4}/{c['proteines']:3}P  {e:+.0%}{drapeau}")
        recette["_ecart"] = e
        lot.append(recette)
    garde = [r for r in lot if abs(r.pop("_ecart")) <= 0.15]
    (ICI / "lot_pdj.json").write_text(json.dumps({"recettes": garde}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(garde)} gardées sur {len(lot)}")


if __name__ == "__main__":
    main()
