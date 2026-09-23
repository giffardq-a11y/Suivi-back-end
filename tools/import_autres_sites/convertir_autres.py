"""Convertit autres_sites_raw.json (BBC Good Food, Jow) en lot suivi-app (1 portion, clés CIQUAL).

Poids standard pour les pièces, densités pour les cuillères (ml), facteurs cuit -> cru.
Chaque recette garde les macros annoncées par le site dans « origine » pour contrôle.
"""
import json
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
BACKEND = ICI.parent.parent
sys.path.insert(0, str(BACKEND))
from app.recettes import macros_recette  # noqa: E402

HUILE = 0.92  # g/ml
# nom sur la page -> (clé CIQUAL, g par unité [1 pour g, densité pour ml, poids d'une pièce],
#                     facteur [cuit -> cru, bouillon liquide -> cube...], grammes si quantité absente)
C = {
    # BBC Good Food
    "pack closed cup mushrooms": ("champignon", 1, 1, None),
    "closed cup mushrooms quartered": ("champignon", 1, 1, None),
    "rapeseed oil plus 2 drops": ("huile_colza", HUILE, 1, None),
    "rapeseed oil": ("huile_colza", HUILE, 1, None),
    "rapeseed oil (for brushing)": ("huile_colza", 1, 1, 5),
    "cherry tomatoes halved, or 8 tomatoes, cut into wedges": ("tomate_cerise", 1, 1, None),
    "parsley": (None,), "porridge oats": ("flocons_avoine", 1, 1, None),
    "eggs": ("oeuf", 50, 1, None), "medium eggs": ("oeuf", 50, 1, None),
    "large egg": ("oeuf", 60, 1, None), "egg": ("oeuf", 50, 1, None),
    "English mustard powder made up with water": ("moutarde", 1, 1, None),
    "English mustard powder": (None,), "dry mustard powder": (None,),
    "cans cherry tomatoes": ("tomate_concassee", 1, 1, None),
    "can mixed bean salad drained": ("haricots_rouges", 1, 1, None),
    "baby spinach": ("epinard", 1, 1, None),
    "baby spinach wilted in a pan or the microwave": ("epinard", 1, 1, None),
    "thinly sliced smoked ham torn": ("jambon_blanc", 1, 1, None),
    "wholemeal rye bread to serve (optional)": (None,),
    "cherry tomatoes quartered": ("tomate_cerise", 1, 1, None),
    "red or white onion finely chopped": ("oignon", 150, 1, None),
    "lime juiced": ("citron_vert", 50, 1, None),
    "olive oil": ("huile_olive", HUILE, 1, None), "olive oil (for frying)": ("huile_olive", 1, 1, 3),
    "olive oil plus extra for drizzling": ("huile_olive", HUILE, 1, None),
    "garlic cloves crushed": ("ail", 5, 1, None), "garlic clove halved": ("ail", 5, 1, None),
    "garlic clove finely chopped": ("ail", 5, 1, None), "garlic clove crushed": ("ail", 5, 1, None),
    "large garlic clove finely grated": ("ail", 7, 1, None), "garlic clove finely grated": ("ail", 5, 1, None),
    "small garlic clove finely chopped": ("ail", 3, 1, None), "garlic clove": ("ail", 5, 1, None),
    "ground cumin": (None,), "chipotle paste or 1 tsp chilli flakes": (None,),
    "cans black beans drained": ("haricots_rouges", 1, 1, None), "small bunch coriander chopped": (None,),
    "bread": ("pain_campagne", 40, 1, None), "avocado finely sliced": ("avocat", 150, 1, None),
    "avocado oil": ("huile_olive", HUILE, 1, None),
    "large onions halved and sliced": ("oignon", 200, 1, None),
    "fresh thyme leaves plus extra for sprinkling": (None,), "fresh thyme leaves": (None,),
    "fresh tomatoes chopped": ("tomate", 1, 1, None), "smoked paprika": (None,),
    "omega seed mix (see tip)": ("graines_tournesol", 0.6, 1, None),
    "large eggs": ("oeuf", 60, 1, None),
    "small onion sliced": ("oignon", 80, 1, None),
    "small red pepper thinly sliced into strips": ("poivron", 100, 1, None),
    "can chopped tomatoes": ("tomate_concassee", 1, 1, None),
    "red wine vinegar": ("vinaigre_cidre", 1, 1, None),
    "can butter beans or chickpeas, drained": ("haricots_blancs", 1, 1, None),
    "sugar": (None,), "seeded bread": ("pain_complet", 40, 1, None),
    "a few parsley sprigs, finely chopped": (None,),
    "boneless, skinless chicken thigh": ("poulet_cuisse", 1, 1, None),
    "medium red onions cut into thick wedges": ("oignon", 150, 1, None),
    "small red potato cut into thick slices": ("pomme_terre", 1, 1, None),
    "red peppers deseeded and cut into thick slices": ("poivron", 150, 1, None),
    "ground cumin, smoked paprika, fennel seeds (1 tsp each)": (None,),
    "lemon (zest and juice)": ("citron", 60, 1, None), "lemon (zest)": (None,),
    "whole blanched almond roughly chopped": ("amande", 1, 1, None),
    "tub 0% Greek yogurt to serve": ("skyr", 1, 1, None),
    "small handful parsley or coriander, chopped, to serve": (None,),
    "bulgur wheat": ("boulgour", 1, 1, None),
    "small cucumber deseeded and finely chopped": ("concombre", 200, 1, None),
    "pitted green olives": ("olive_verte", 1, 1, None),
    "small handful of parsley finely chopped": (None,),
    "rose harissa": ("harissa", 1, 1, None), "honey": ("miel", 1.4, 1, None),
    "lemon juiced": ("citron", 60, 1, None), "lemon zested and juiced": ("citron", 60, 1, None),
    "lemon": ("citron", 60, 1, None),
    "red onion finely sliced": ("oignon", 120, 1, None),
    "skinless, boneless white fish fillets, such as cod or haddock": ("cabillaud", 1, 1, None),
    "skinless chicken breasts": ("poulet_filet", 150, 1, None), "Cajun seasoning": (None,),
    "quinoa": ("quinoa", 1, 1, None), "hot chicken stock": ("bouillon", 1, 0.02, None),
    "dried apricots sliced": ("abricot_sec", 1, 1, None),
    "ready-to-use Puy lentils": ("lentilles", 1, 0.4, None),
    "red onions cut into thin wedges": ("oignon", 150, 1, None),
    "spring onions (1 bunch)": ("oignon", 100, 1, None),
    "skinless cod loin or pollock fillets": ("cabillaud", 1, 1, None),
    "large red pepper sliced": ("poivron", 200, 1, None),
    "leeks well washed and thinly sliced": ("poireau", 150, 1, None),
    "flaked almonds": ("amande", 0.27, 1, None), "tomato purée": ("concentre_tomate", 1.1, 1, None),
    "vegetable bouillon powder": (None,), "apple cider vinegar": ("vinaigre_cidre", 1, 1, None),
    "fresh tuna fillets, defrosted": ("thon_naturel", 1, 1, None),
    "ripe avocado": ("avocat", 150, 1, None), "cider vinegar": ("vinaigre_cidre", 1, 1, None),
    "capers": (None,), "romaine lettuce leaves": ("salade", 15, 1, None),
    "cherry tomatoes preferably on the vine, halved": ("tomate_cerise", 15, 1, None),
    "chunky peanut butter (without palm oil or sugar)": ("beurre_cacahuete", 1.05, 1, None),
    "Madras curry powder": (None,), "soy sauce": (None,), "lime juice": ("citron_vert", 1, 1, None),
    "chicken breast fillets": ("poulet_filet", 1, 1, None),
    "cucumber (about 10 cm)": ("concombre", 1, 1, 100),
    "sweet chilli sauce (to serve, optional)": (None,),
    "small handful flatleaf parsley finely chopped, plus extra sprigs to serve": (None,),
    "handful chives finely snipped": (None,), "handful fresh basil torn": (None,),
    "parmesan freshly grated": ("parmesan", 1, 1, None), "tub ricotta": ("ricotta", 1, 1, None),
    "rye bread (6 very thin slices)": ("pain_seigle", 1, 1, None),
    "small tomatoes sliced": ("tomate", 80, 1, None), "cucumber slices": ("concombre", 5, 1, None),
    "thinly sliced turkey breast (look for carved turkey rather than pre-formed slices)": ("blanc_dinde", 1, 1, None),
    "Little Gem lettuce leaves, shredded": ("salade", 10, 1, None),
    "light mayonnaise": ("mayonnaise", 0.45, 1, None),  # allégée ≈ moitié de l'énergie
    "0% bio-yogurt": ("yaourt_nature", 1, 1, None), "raisin": ("raisin_sec", 0.6, 1, None),
    "spring onions finely chopped": ("oignon", 15, 1, None),
    "almond milk or milk of your choice": ("boisson_amande", 1, 1, None),
    "cinnamon": ("cannelle", 0.5, 1, None), "vanilla essence": (None,),
    "bio yogurt": ("yaourt_nature", 1, 1, None), "cinnamon for dusting": (None,),
    "blueberries": ("myrtille", 1, 1, None),
    "shallot finely chopped": ("echalote", 30, 1, None),
    "green lentil (drained weight from a 400g can)": ("lentilles", 1, 0.4, None),
    "extra lean pork mince (less than 5% fat)": ("porc_filet", 1, 1, None),
    "finely chopped sage": (None,), "finely snipped chive": (None,), "good pinch of grated nutmeg": (None,),
    "plain flour": ("farine", 0.55, 1, None), "panko crumbs (Japanese breadcrumbs)": ("chapelure", 1, 1, None),
    "green beans": ("haricot_vert", 1, 1, None), "tomato amber or red, quartered": ("tomate", 120, 1, None),
    "tuna in spring water (can)": ("thon_naturel", 1, 1, None),
    "French dressing": ("huile_olive", 0.45 * HUILE, 1, None),  # vinaigrette ≈ 45 % d'huile
    # Jow
    "Ail": ("ail", 5, 1, None), "Œuf": ("oeuf", 50, 1, None),
    "Pain de campagne (tranché)": ("pain_campagne", 40, 1, None),
    "Piment d'Espelette": (None,), "Coriandre (frais)": (None,), "Persil (frais)": (None,),
    "Yaourt Grec": ("yaourt_grec", 1.03, 1, None), "Huile d'olive": ("huile_olive", HUILE, 1, None),
    "Tortilla (blé complet)": ("tortilla", 45, 1, None),
    "Blanc de dinde (tranches)": ("blanc_dinde", 40, 1, None),
    "Champignons bruns": ("champignon", 1, 1, None), "Mozzarella (râpée)": ("mozzarella", 1, 1, None),
    "Sauce pesto": ("pesto", 1, 1, None),
    "Poulet (escalope)": ("poulet_filet", 150, 1, None), "Riz": ("riz_blanc", 1, 1, None),
    "Carotte (frais)": ("carotte", 1, 1, None), "Avocat": ("avocat", 150, 1, None),
    "Échalote": ("echalote", 30, 1, None), "Sauce soja sucrée": ("sauce_soja", 1.2, 1, None),
    "Skyr": ("skyr", 1.03, 1, None),
    "Saumon (frais)": ("saumon", 125, 1, None), "Semoule": ("semoule", 1, 1, None),
    "Harissa (pâte)": ("harissa", 1, 1, None), "Tomates séchées": ("tomate_sechee", 1, 1, None),
    "Pâtes (Linguine)": ("pates", 1, 1, None), "Crevette (cuite)": ("crevette", 1, 1, None),
    "Tomate pelée": ("tomate_concassee", 1, 1, None), "Mélange pour pâtes": (None,),
    "Thon (conserve)": ("thon_naturel", 1, 1, None),
    "Dinde (escalope)": ("dinde_escalope", 150, 1, None),
    "Haricot vert (frais)": ("haricot_vert", 1, 1, None), "Paprika": (None,),
    "Pics à brochette": (None,),
    "Tofu (nature)": ("tofu", 1, 1, None), "Brocoli (frais)": ("brocoli", 1, 1, None),
    "Beurre de cacahuète": ("beurre_cacahuete", 1.05, 1, None), "Farine de blé": ("farine", 0.55, 1, None),
    "Lentilles (cuites)": ("lentilles", 1, 0.4, None), "Moutarde": ("moutarde", 1, 1, None),
    "Vinaigre balsamique": ("vinaigre_balsamique", 1, 1, None), "Lardons": ("lardons", 1, 1, None),
    "Salade (coeur de laitue)": ("salade", 1, 1, 80),
    "Moutarde à l'ancienne": ("moutarde", 1, 1, None), "Parmesan (morceaux)": ("parmesan", 1, 1, None),
    "Salade (sucrine)": ("salade", 100, 1, None), "Lard (tranches)": ("lardons", 15, 1, None),
    "Quinoa (cuit)": ("quinoa", 1, 0.35, None),
    "Concombre": ("concombre", 300, 1, None), "Tomate": ("tomate", 1, 1, None),
    "Oignon rouge": ("oignon", 120, 1, None), "Paprika fumé": (None,),
    "Mélange céréales (cuites)": ("boulgour", 1, 0.4, None),
    "Chou-fleur (frais)": ("chou_fleur", 1, 1, None), "Pois chiches (cuits)": ("pois_chiches", 1, 1, None),
    "Citron jaune": ("citron", 60, 1, None),
    "Pommes de terre": ("pomme_terre", 1, 1, None), "Haricot vert (surgelé)": ("haricot_vert", 1, 1, None),
    "Crème fraîche": ("creme_legere", 1, 1, None), "Ciboulette": (None,),
    "Cabillaud (frais)": ("cabillaud", 125, 1, None), "Orange": ("orange", 180, 1, None),
    "Haricots blancs nature (cuits)": ("haricots_blancs", 1, 1, None),
    "Haddock fumé": ("haddock", 1, 1, None), "Crème liquide": ("creme_legere", 1, 1, None),
    "Curcuma (poudre)": (None,), "Oignon jaune": ("oignon", 150, 1, None),
    "Maquereau fumé": ("maquereau_fume", 100, 1, None), "Petits pois (surgelés)": ("petit_pois", 1, 1, None),
    "Vinaigre de cidre": ("vinaigre_cidre", 1, 1, None), "Menthe (feuilles)": (None,),
    "Chapelure": ("chapelure", 0.45, 1, None), "Salade (roquette)": ("roquette", 1, 1, 30),
    "Garam masala": (None,),
    "Haricot vert (frais) ": ("haricot_vert", 1, 1, None),
    "Vinaigre de vin blanc": ("vinaigre_cidre", 1, 1, None),
    "Poire": ("poire", 150, 1, None), "Brie (fondant)": ("brie", 1, 1, None),
    "Miel (liquide)": ("miel", 1.4, 1, None), "Pignons de pin": ("pignon", 0.6, 1, None),
    "Salade (Mélange)": ("salade", 1, 1, 30),
}

# index -> (id, nom FR, type, tags, étapes)
F = {
    0: ("pdj-galettes-oeuf-avoine-champignons-bbc", "Galettes d'œufs à l'avoine, champignons et tomates", "petit-dejeuner",
        ["poele", "sale", "vegetarien"], [
        "Faire revenir les champignons émincés 6 à 8 min à couvert dans un peu d'huile, puis ajouter les tomates cerises 2 min.",
        "Battre les œufs avec le persil, les flocons d'avoine et la moutarde.",
        "Cuire le mélange en 4 fines galettes, 1 min de chaque côté dans une poêle huilée, garnir de légumes et rouler."]),
    3: ("pdj-oeufs-cocotte-haricots-tomate-jambon-bbc", "Œufs cuits dans une sauce tomate aux haricots et jambon", "petit-dejeuner",
        ["poele", "sale", "one-pot"], [
        "Faire réduire 10 min les tomates et les haricots égouttés dans une poêle allant au four, puis ajouter les épinards jusqu'à ce qu'ils tombent.",
        "Creuser 4 puits, y casser les œufs, glisser le jambon déchiré et passer 4 à 5 min sous le gril jusqu'à ce que les blancs soient pris."]),
    4: ("pdj-tartines-haricots-noirs-avocat-bbc", "Tartines de haricots au cumin et avocat", "petit-dejeuner",
        ["poele", "vegetalien", "vegetarien"], [
        "Mélanger tomates cerises, un quart de l'oignon, le jus de citron vert et 1 c. à s. d'huile.",
        "Faire fondre le reste de l'oignon dans 2 c. à s. d'huile, ajouter l'ail et le cumin 1 min, puis les haricots égouttés et chauffer 3 min en écrasant un peu.",
        "Griller le pain, l'arroser du reste d'huile, garnir de haricots, d'avocat en lamelles et de salsa de tomates."]),
    6: ("pdj-haricots-blancs-fumes-sur-pain-bbc", "Haricots blancs à la tomate fumée sur pain grillé", "petit-dejeuner",
        ["poele", "vegetalien", "vegetarien"], [
        "Faire fondre l'oignon et le poivron 10 à 15 min dans l'huile, ajouter la moitié de l'ail écrasé, les tomates, le paprika et le vinaigre.",
        "Ajouter les haricots égouttés et mijoter 10 min jusqu'à ce que la sauce épaississe.",
        "Griller le pain, le frotter avec le reste d'ail et le garnir de haricots, avec un filet d'huile et du persil."]),
    8: ("din-oeufs-turque-yaourt-jow", "Œufs à la turque, yaourt et huile pimentée", "diner",
        ["sale", "vegetarien", "rapide"], [
        "Cuire les œufs 6 min à l'eau bouillante, les refroidir et les écaler.",
        "Faire dorer l'ail en lamelles 1 à 2 min dans l'huile d'olive, ajouter hors du feu le piment d'Espelette.",
        "Étaler le yaourt grec, poser les œufs, arroser d'huile pimentée et servir avec le pain grillé."]),
    9: ("pdj-wrap-oeuf-dinde-champignons-jow", "Wrap complet œuf, dinde et champignons", "petit-dejeuner",
        ["poele", "sale", "rapide"], [
        "Battre l'œuf avec le pesto, sel et poivre, le verser dans une poêle huilée et poser la tortilla dessus ; cuire 2 à 3 min puis retourner.",
        "Garnir de champignons émincés, de dinde en morceaux et de mozzarella, replier et laisser dorer 30 s."]),
    10: ("dej-bowl-riz-poulet-carottes-avocat-jow", "Bowl riz, poulet, carottes râpées et avocat", "dejeuner",
         ["poele", "plat-complet"], [
        "Cuire le riz. Faire revenir l'échalote émincée 2 min dans l'huile, ajouter le poulet en morceaux et l'ail, cuire 6 à 8 min.",
        "Verser la sauce soja et poursuivre 1 à 2 min.",
        "Servir sur le riz avec les carottes râpées et l'avocat, napper de skyr assaisonné au piment d'Espelette."]),
    11: ("dej-saumon-harissa-semoule-tomates-sechees-jow", "Saumon à la harissa, semoule aux tomates séchées", "dejeuner",
         ["poele", "poisson", "rapide"], [
        "Badigeonner le saumon de harissa et d'huile d'olive, saler et laisser mariner.",
        "Couvrir la semoule d'eau chaude 5 min, l'égrainer et ajouter les tomates séchées et le persil.",
        "Cuire le saumon 3 min de chaque côté à feu vif et le servir sur la semoule."]),
    12: ("dej-linguine-tomates-crevettes-jow", "Linguine aux tomates et crevettes", "dejeuner",
         ["poele", "rapide", "poisson"], [
        "Cuire les pâtes. Faire revenir les crevettes 1 min dans l'huile avec les herbes.",
        "Ajouter les tomates pelées en les écrasant, saler, poivrer, puis mélanger avec les pâtes égouttées."]),
    13: ("dej-linguine-thon-tomates-sechees-jow", "Linguine au thon et tomates séchées", "dejeuner",
         ["poele", "rapide", "poisson"], [
        "Cuire les pâtes en gardant 2 c. à s. d'eau de cuisson.",
        "Faire revenir l'ail râpé et les tomates séchées en lamelles 2 min, ajouter le thon émietté et l'eau de cuisson.",
        "Mélanger avec les pâtes égouttées et le persil."]),
    14: ("dej-brochettes-dinde-paprika-semoule-jow", "Brochettes de dinde au paprika, haricots verts et semoule", "dejeuner",
         ["poele", "plat-complet"], [
        "Cuire les haricots verts 10 min à l'eau bouillante salée.",
        "Couper la dinde en lanières, l'enrober de paprika et d'huile, l'enfiler sur des piques et la cuire 10 à 12 min à la poêle.",
        "Faire gonfler la semoule dans le même volume d'eau bouillante, servir avec le yaourt grec assaisonné."]),
    15: ("dej-tofu-sauce-cacahuete-riz-brocoli-jow", "Tofu sauce cacahuète, riz et brocoli", "dejeuner",
         ["poele", "vegetalien", "vegetarien", "plat-complet"], [
        "Cuire le riz et le brocoli en fleurettes 6 min à l'eau salée.",
        "Enrober le tofu en dés de farine et le faire griller 5 min à la poêle.",
        "Mélanger beurre de cacahuète, sauce soja, ail râpé et un peu d'eau, verser sur le tofu et cuire 1 à 2 min. Servir avec le riz et le brocoli."]),
    16: ("dej-salade-lentilles-saumon-echalote-jow", "Salade de lentilles au saumon et échalote", "dejeuner",
         ["poele", "poisson", "tiede"], [
        "Cuire le saumon 6 min côté peau puis 1 min de chaque côté, et l'émietter.",
        "Mélanger moutarde, vinaigre balsamique et huile d'olive.",
        "Dresser les lentilles cuites rincées avec le saumon et l'échalote émincée, arroser de vinaigrette."]),
    17: ("dej-salade-lyonnaise-jow", "Salade lyonnaise, œuf mollet, lardons et parmesan", "dejeuner",
         ["poele", "rapide"], [
        "Cuire l'œuf 5 min 30 à l'eau bouillante, le refroidir puis l'écaler.",
        "Faire revenir les lardons 2 à 3 min, puis dorer le pain dans la même poêle.",
        "Servir la salade avec les lardons, les croûtons, l'œuf, les copeaux de parmesan et la vinaigrette moutarde-huile."]),
    18: ("dej-salade-quinoa-poulet-brocoli-lard-jow", "Salade de quinoa, poulet, brocoli et lard", "dejeuner",
         ["poele", "tiede"], [
        "Cuire le brocoli 5 min à l'eau salée et le quinoa selon le paquet.",
        "Faire revenir le poulet en tranches 2 à 3 min par face, puis le lard en morceaux.",
        "Dresser la sucrine, le quinoa, le poulet, le brocoli et le lard, assaisonner de vinaigrette à la moutarde."]),
    19: ("dej-poulet-grecque-cereales-jow", "Poulet mariné à la grecque, salade et céréales", "dejeuner",
         ["poele", "plat-complet"], [
        "Mariner le poulet 10 min dans 1 c. à s. d'huile et le paprika.",
        "Mélanger concombre, tomate et oignon rouge en dés avec un filet d'huile.",
        "Cuire le poulet 4 à 5 min par face, servir avec les céréales réchauffées, la salade et le yaourt assaisonné."]),
    20: ("dej-poulet-poivrons-pommes-terre-amandes-four-bbc", "Plaque de poulet, poivrons, pommes de terre et amandes", "dejeuner",
         ["four", "batch", "plat-complet"], [
        "Préchauffer le four à 200 °C. Mélanger poulet, oignons, pommes de terre et poivrons avec l'ail, les épices, l'huile et le citron.",
        "Rôtir 40 min en retournant à mi-cuisson, ajouter les amandes les 8 dernières minutes.",
        "Servir avec une cuillerée de fromage blanc 0 %."]),
    21: ("dej-poisson-harissa-boulgour-olives-bbc", "Poisson blanc à la harissa, taboulé de boulgour", "dejeuner",
         ["poele", "poisson"], [
        "Cuire le boulgour, le rincer et le mélanger avec concombre, tomates cerises, olives et persil.",
        "Mélanger harissa, miel, ail, jus de citron et un peu d'huile.",
        "Faire dorer l'oignon 4 à 5 min, ajouter le poisson et la sauce harissa et cuire 3 à 4 min par face. Servir sur le boulgour."]),
    22: ("din-poulet-carottes-chou-fleur-pois-chiches-jow", "Poulet, légumes rôtis aux pois chiches et sauce yaourt", "diner",
         ["four", "plat-complet"], [
        "Rôtir chou-fleur, carottes et pois chiches égouttés 30 à 40 min à 180 °C avec un filet d'huile.",
        "Cuire le poulet 4 à 5 min par face à la poêle.",
        "Mélanger le yaourt avec le zeste et le jus de citron et servir en sauce."]),
    23: ("din-saumon-pommes-terre-haricots-verts-jow", "Saumon, pommes de terre rôties et haricots verts", "diner",
         ["four", "poisson"], [
        "Rôtir les pommes de terre en fines lamelles 25 min à 190 °C avec un filet d'huile.",
        "Ajouter le saumon assaisonné et cuire encore 8 à 10 min. Cuire les haricots verts 3 min à l'eau.",
        "Servir avec la crème mélangée au zeste et au jus de citron."]),
    24: ("din-papillote-cabillaud-agrumes-riz-jow", "Papillote de cabillaud aux agrumes et riz", "diner",
         ["four", "poisson", "leger"], [
        "Préchauffer le four à 200 °C. Poser le cabillaud sur du papier cuisson avec l'échalote hachée, un filet d'huile et les tranches d'orange et de citron.",
        "Fermer la papillote et cuire 10 min. Servir avec le riz."]),
    25: ("din-veloute-haricots-blancs-haddock-jow", "Velouté de haricots blancs au haddock", "diner",
         ["soupe", "poisson", "rapide"], [
        "Faire revenir l'oignon émincé avec le curcuma 1 min dans l'huile, ajouter les haricots rincés.",
        "Couvrir d'eau (15 cl), porter à ébullition et mijoter 10 min, puis ajouter la crème et mixer.",
        "Servir avec le haddock en lamelles."]),
    27: ("din-salade-quinoa-maquereau-fume-petits-pois-jow", "Salade de quinoa, maquereau fumé, concombre et petits pois", "diner",
         ["froid", "poisson", "rapide"], [
        "Cuire le quinoa, ébouillanter les petits pois.",
        "Mélanger moutarde à l'ancienne, vinaigre de cidre et huile d'olive.",
        "Dresser quinoa, concombre en dés, petits pois, maquereau émietté et menthe, arroser de vinaigrette."]),
    29: ("din-bouchees-dinde-carottes-roties-jow", "Bouchées de dinde et carottes rôties au yaourt", "diner",
         ["four", "poele"], [
        "Rôtir les carottes coupées en deux 20 à 25 min à 220 °C avec un filet d'huile.",
        "Hacher la dinde, la mélanger avec l'œuf, le garam masala, la chapelure et le zeste de citron, former des galettes et les cuire 4 min par face.",
        "Servir sur la sauce yaourt-citron avec les carottes et la roquette."]),
    31: ("din-poulet-cajun-quinoa-lentilles-abricots-bbc", "Poulet cajun, quinoa, lentilles et abricots secs", "diner",
         ["four", "batch", "epice"], [
        "Enrober le poulet d'épices cajun et le rôtir 20 min à 200 °C.",
        "Cuire le quinoa 15 min dans le bouillon, en ajoutant abricots et lentilles les 5 dernières minutes, puis égoutter.",
        "Faire fondre les oignons 10 à 15 min dans l'huile, mélanger au quinoa avec les oignons nouveaux et servir avec le poulet tranché."]),
    32: ("din-cabillaud-ail-romesco-epinards-bbc", "Cabillaud à l'ail, sauce romesco et épinards", "diner",
         ["four", "poisson"], [
        "Enrober le poisson d'huile, de thym, d'ail et de zeste de citron, et le cuire 15 à 20 min au four à 220 °C.",
        "Faire revenir poivron et poireaux 5 min, ajouter les amandes 5 min, puis le concentré de tomate, le vinaigre et un peu d'eau.",
        "Mixer avec le jus de citron en sauce épaisse, servir avec le poisson et les épinards tombés."]),
    33: ("din-thon-avocat-feuilles-laitue-bbc", "Thon snacké et « mayo » d'avocat en feuilles de laitue", "diner",
         ["poele", "poisson", "rapide"], [
        "Saisir le thon huilé 1 min de chaque côté et le laisser reposer.",
        "Écraser l'avocat avec le vinaigre de cidre (et un peu de moutarde) jusqu'à obtenir une texture de mayonnaise.",
        "Garnir les feuilles de laitue de « mayo », de thon tranché et de tomates cerises."]),
    34: ("col-aiguillettes-poulet-satay-bbc", "Aiguillettes de poulet satay au four", "collation",
         ["four", "transportable"], [
        "Mélanger beurre de cacahuète, ail râpé, curry, un trait de sauce soja et jus de citron vert.",
        "Enrober le poulet en lanières et cuire 8 à 10 min au four à 200 °C.",
        "Servir chaud ou froid avec des bâtonnets de concombre."]),
    35: ("col-salade-haricots-verts-oeuf-jow", "Salade de haricots verts et œuf dur", "collation",
         ["leger", "vegetarien"], [
        "Cuire les haricots verts 10 à 12 min à l'eau salée et l'œuf 10 min.",
        "Mélanger vinaigre, huile d'olive et moutarde.",
        "Servir les haricots avec l'œuf en dés et la vinaigrette."]),
    36: ("col-mini-omelettes-roulees-ricotta-bbc", "Mini-omelettes roulées à la ricotta", "collation",
         ["poele", "vegetarien", "transportable"], [
        "Battre les œufs avec 2 c. à s. d'eau, les herbes, l'ail et la moitié du parmesan, puis cuire 3 fines omelettes.",
        "Mélanger la ricotta avec le basilic et le reste du parmesan, en tartiner les omelettes, les rouler et les couper en tronçons."]),
    37: ("col-tartines-seigle-dinde-curry-bbc", "Tartines de seigle à la dinde, sauce yaourt au curry", "collation",
         ["sans-cuisson", "rapide"], [
        "Mélanger mayonnaise allégée, yaourt, curry, raisins secs et oignon nouveau.",
        "Tartiner le pain de seigle, garnir de tomate, concombre, dinde et laitue, napper du reste de sauce."]),
    38: ("col-avoine-cuite-myrtilles-bbc", "Petits gratins d'avoine aux myrtilles", "collation",
         ["four", "sucre", "vegetarien"], [
        "Battre la boisson d'amande, l'œuf, les flocons, 2 c. à s. d'eau, la cannelle et la vanille, répartir dans 2 ramequins.",
        "Cuire 15 min à 200 °C et servir avec le yaourt et les myrtilles."]),
    39: ("col-tartine-poire-brie-miel-jow", "Tartine gratinée poire, brie et miel", "collation",
         ["four", "vegetarien"], [
        "Garnir la tranche de pain de brie puis de lamelles de poire, arroser de miel.",
        "Passer 10 min sous le gril du four, parsemer de pignons et servir avec un peu de salade."]),
    40: ("col-oeufs-ecossais-legers-bbc", "Œufs écossais allégés au porc et lentilles", "collation",
         ["four", "batch", "transportable"], [
        "Cuire 4 œufs 5 min, les refroidir et les écaler. Mélanger le porc haché, les lentilles écrasées, l'échalote revenue, la sauge et la moutarde.",
        "Fariner les œufs, les envelopper d'un quart de la farce, les passer dans le 5e œuf battu puis dans la chapelure.",
        "Les faire dorer dans l'huile puis cuire 12 min au four à 200 °C."]),
    41: ("col-pot-nicoise-thon-bbc", "Pot niçois au thon et œuf", "collation",
         ["transportable", "poisson", "rapide"], [
        "Cuire l'œuf 8 à 10 min et les haricots verts 6 min à la vapeur.",
        "Dans une boîte, superposer haricots, tomate, thon et œuf en quartiers, arroser de vinaigrette."]),
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
    brut = json.loads((ICI / "autres_sites_raw.json").read_text(encoding="utf-8"))["recettes"]
    lot = []
    for i, (ident, nom, type_repas, tags, etapes) in F.items():
        src = brut[i]
        n = src["servings"]
        grammes: dict[str, float] = {}
        placard: dict[str, float] = {}
        for ing in src["ingredients"]:
            cle, g = convertir(ing)
            if cle:
                grammes[cle] = grammes.get(cle, 0) + g / n
                if ing.get("placard_jow"):
                    placard[cle] = placard.get(cle, 0) + g / n
        ingredients = [{"cle": c, "quantite_g": max(1, round(g))} for c, g in grammes.items() if g >= 0.5]
        m = src["macros_par_portion"]
        temps = src.get("total_min") or (src.get("prep_min") or 0) + (src.get("cook_min") or 0)
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
        if placard:  # Jow ne compte pas toujours l'huile « de placard » dans ses macros
            sans = {**recette, "ingredients": [
                {"cle": l["cle"], "quantite_g": l["quantite_g"] - placard.get(l["cle"], 0)} for l in ingredients]}
            e_sans = (macros_recette(sans)["calories"] - m["calories"]) / m["calories"]
            if abs(e_sans) < abs(e):
                e = e_sans
                recette["origine"]["remarque"] = ("Macros du site hors huile de placard ; "
                                                  "l'huile est comptée dans les macros de l'app.")
        drapeau = "  <<" if abs(e) > 0.15 else ""
        print(f"{i:2} {type_repas[:4]} {nom[:50]:50} site {m['calories']:5.0f}/{m['proteines']:3.0f}P  "
              f"ciqual {c['calories']:4}/{c['proteines']:3}P  {e:+.0%}{drapeau}")
        recette["_ecart"] = e
        lot.append(recette)
    garde = [r for r in lot if abs(r.pop("_ecart")) <= 0.15]
    (ICI / "lot_autres.json").write_text(json.dumps({"recettes": garde}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"\n{len(garde)} gardées sur {len(lot)}")


if __name__ == "__main__":
    main()
