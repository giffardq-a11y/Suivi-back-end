"""Convertit eatthismuch_raw.json en lot au format suivi-app (1 portion, clés CIQUAL)."""
import json
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
BACKEND = ICI.parent.parent
sys.path.insert(0, str(BACKEND))
from app.recettes import macros_recette  # noqa: E402

# nom eatthismuch -> clé CIQUAL ; None = négligeable (sel, poivre, épices < 1 g, eau...)
CORRESPONDANCE = {
    "Tamari soy sauce": "sauce_soja", "Lemon juice": "citron", "Honey": "miel",
    "Sesame oil": "huile_olive", "Rice wine vinegar": "vinaigre_cidre",
    "Crushed red pepper flakes": None, "Chicken breast": "poulet_filet", "Olive oil": "huile_olive",
    "Garlic": "ail", "Garlic powder": None, "Carrots": "carotte", "Red bell pepper": "poivron",
    "Green bell pepper": "poivron", "Yellow bell pepper": "poivron_jaune",
    "White mushrooms": "champignon", "Broccoli": "brocoli", "Cornstarch": "maizena",
    "White rice": "riz_blanc", "Brown rice": "riz_complet", "Asparagus": "asperge",
    "Cherry tomatoes": "tomate_cerise", "Salt": None, "Black pepper": None, "Cumin seed": "cumin",
    "Atlantic salmon": "saumon", "Pink salmon": "saumon", "Lemon": "citron", "Basil pesto": "pesto",
    "Lentils": "lentilles", "Water": None, "Onion": "oignon", "Parsley": "persil",
    "Shrimp": "crevette", "Scallions": "oignon", "Ginger root": "gingembre",
    "Greek yogurt": "skyr", "Oregano": None, "Chickpeas": "pois_chiches", "Tomatoes": "tomate",
    "Cucumber": "concombre", "Spinach": "epinard", "Flour tortillas": "tortilla", "Feta cheese": "feta",
    "Light tuna": "thon_naturel", "Yellowfin tuna": "thon_naturel", "Radishes": "radis",
    "Chili pepper": None, "Cilantro": "coriandre_fraiche", "Romaine lettuce": "salade",
    "Cooking spray": None, "Turkey": "blanc_dinde", "Egg": "oeuf", "Cheddar cheese": "cheddar",
    "Tofu": "tofu", "Canola oil": "huile_colza", "Coriander seed": "coriandre_graine",
    "Turmeric": "curcuma", "Black beans": "haricots_rouges", "Thyme": None,
    "Sourdough bread": "pain_campagne", "Cottage cheese": "skyr", "Cinnamon": "cannelle",
    "Almonds": "amande", "Rolled oats": "flocons_avoine", "Banana": "banane", "2% milk": "lait_demi",
    "Strawberries": "fraise", "Brown sugar": None, "Vegetable broth": "bouillon",
    "Chicken stock": "bouillon", "Basil": "basilic", "Parmesan cheese": "parmesan",
    "Baguette": "baguette", "Flaxseed": "lin", "Blueberries": "myrtille", "Pecans": "noix",
    "Coconut oil": "huile_colza", "Sun-dried tomatoes": "tomate_sechee",
    "Balsamic vinegar": "vinaigre_balsamique", "English walnuts": "noix", "Pears": "poire",
    "Hazelnuts": "noisette", "Arugula": "roquette",
    "Newman's Own balsamic vinaigrette": "vinaigre_balsamique", "Butter": "beurre",
    "Bacon": "lardons", "Atlantic cod": "cabillaud", "Black olives": "olive_noire",
    "Mozzarella cheese": "mozzarella", "Pine nuts": "pignon", "Mayonnaise": "mayonnaise",
    "Mixed vegetables": "legumes_surgeles", "Worcestershire sauce": None, "Chili powder": None,
    "Green peas": "petit_pois", "Spearmint": "menthe", "Paprika": "paprika",
    "Zucchini": "courgette", "Onion powder": None, "Ground turkey": "dinde_escalope",
    "Hamburger bun": "pain_burger", "Breadcrumbs": "chapelure", "Pork tenderloin": "porc_filet",
    "Quinoa": "quinoa", "Nutritional yeast": None, "Raspberries": "framboise",
    "Green beans": "haricot_vert", "Dill weed": "aneth", "Lime juice": "citron_vert",
}
# bouillon liquide -> bouillon déshydraté (cube de 10 g pour 500 ml)
FACTEUR = {"Vegetable broth": 0.02, "Chicken stock": 0.02}

# index eatthismuch -> (id, nom, type, tags, étapes)
FICHES = {
    0: ("dej-wok-poulet-legumes-riz-etm", "Wok de poulet mariné, légumes et riz", "dejeuner",
        ["wok", "poele", "plat-complet"], [
        "Cuire le riz selon le paquet. Mélanger sauce soja, jus de citron, miel et huile, y enrober le poulet en dés et laisser mariner.",
        "Saisir le poulet égoutté 5 min au wok très chaud avec la moitié de l'huile, le réserver en gardant la marinade.",
        "Faire revenir l'ail 1 min dans le reste d'huile, ajouter carottes, poivron et champignons 3 min, puis le brocoli et le poulet.",
        "Délayer la fécule dans la marinade, verser dans le wok et laisser épaissir 5 min à feu doux. Servir sur le riz."]),
    1: ("din-saumon-asperges-tomates-pesto-etm", "Saumon rôti, asperges et tomates cerises au pesto", "diner",
        ["four", "poisson", "rapide"], [
        "Préchauffer le four à 230 °C. Sur une plaque, enrober asperges et tomates cerises d'huile d'olive, sel et poivre.",
        "Poser le saumon assaisonné parmi les légumes avec les rondelles de citron et enfourner 10 à 15 min.",
        "À la sortie du four, déposer le pesto sur le saumon et les légumes, arroser de jus de citron et servir."]),
    2: ("col-soupe-lentilles-cumin-etm", "Soupe de lentilles au cumin et citron", "collation",
        ["soupe", "batch", "vegetalien", "vegetarien"], [
        "Faire revenir oignon, carottes et ail hachés 3 min dans l'huile d'olive, ajouter le cumin et cuire 30 s.",
        "Ajouter les lentilles rincées et 5 fois leur poids d'eau, porter à ébullition puis cuire 20 à 25 min à petit feu.",
        "Mixer en partie ou totalement, puis ajouter hors du feu le jus de citron et le persil, rectifier l'assaisonnement."]),
    3: ("din-crevettes-miel-ail-brocoli-riz-etm", "Crevettes miel-ail, brocoli et riz complet", "diner",
        ["poele", "poisson", "plat-complet"], [
        "Mélanger miel, sauce soja, ail et gingembre râpés ; y enrober les crevettes avec la moitié de la sauce, 15 min au frais.",
        "Cuire le riz complet selon le paquet et le brocoli 4 à 5 min à la vapeur.",
        "Saisir les crevettes 1 min dans l'huile chaude, retourner, verser le reste de sauce et cuire jusqu'à ce qu'elles soient opaques.",
        "Servir sur le riz avec le brocoli, parsemer d'oignon émincé."]),
    4: ("din-papillote-saumon-pesto-haricots-verts-etm", "Papillote de saumon au pesto et haricots verts", "diner",
        ["four", "poisson"], [
        "Préchauffer le four à 230 °C. Sur une feuille de papier cuisson, poser les haricots verts, un peu de pesto et des rondelles de citron.",
        "Ajouter le saumon assaisonné, le napper du reste de pesto et fermer la papillote en roulant les bords.",
        "Cuire 15 à 20 min, ouvrir délicatement et parsemer de persil."]),
    7: ("col-salade-thon-asiatique-etm", "Salade de thon à l'asiatique", "collation",
        ["sans-cuisson", "rapide", "froid", "poisson"], [
        "Mélanger le thon égoutté, les radis en quartiers, la carotte râpée, l'ail et le gingembre hachés.",
        "Assaisonner d'huile, de vinaigre, sel et poivre, puis ajouter coriandre et oignon émincés.",
        "Servir sur la laitue émincée."]),
    8: ("pdj-omelette-dinde-cheddar-etm", "Omelette au blanc de dinde et cheddar", "petit-dejeuner",
        ["sale", "poele", "rapide"], [
        "Faire dorer le blanc de dinde émincé dans une poêle antiadhésive, le réserver.",
        "Battre les œufs, les verser dans la poêle et cuire 3 à 4 min en ramenant les bords vers le centre.",
        "Garnir de cheddar et de dinde, replier l'omelette et laisser fondre le fromage 2 min."]),
    10: ("pdj-piperade-oeufs-pain-etm", "Piperade aux œufs brouillés et pain grillé", "petit-dejeuner",
         ["poele", "vegetarien"], [
        "Faire fondre oignon, poivrons et ail 8 à 10 min à couvert dans l'huile d'olive.",
        "Ajouter les tomates concassées, assaisonner et laisser compoter 5 min à découvert.",
        "Incorporer les œufs battus et remuer 3 à 4 min jusqu'à ce qu'ils soient brouillés. Parsemer de persil, servir avec le pain grillé."]),
    11: ("pdj-oeufs-cocotte-champignons-epinards-etm", "Gratin d'œufs aux champignons, épinards et cheddar", "petit-dejeuner",
         ["four", "sale", "batch", "vegetarien"], [
        "Préchauffer le four à 180 °C. Hacher champignons, oignon et épinards.",
        "Mélanger avec les œufs battus et le cheddar râpé, verser dans un plat.",
        "Cuire 25 min, jusqu'à ce que les œufs soient pris. Se garde 3 jours au frais."]),
    12: ("pdj-fromage-blanc-cannelle-amandes-etm", "Fromage blanc 0 % à la cannelle et aux amandes", "petit-dejeuner",
         ["sans-cuisson", "rapide", "sucre", "vegetarien"], [
        "Concasser grossièrement les amandes.",
        "Mélanger le fromage blanc avec la cannelle et parsemer d'amandes."]),
    13: ("pdj-porridge-banane-lait-etm", "Flocons d'avoine au lait et à la banane", "petit-dejeuner",
         ["rapide", "sucre", "vegetarien"], [
        "Verser les flocons et le lait dans un bol, manger tel quel ou chauffer 2 min au micro-ondes.",
        "Ajouter la banane en rondelles."]),
    14: ("pdj-porridge-fraises-etm", "Porridge aux fraises mixées", "petit-dejeuner",
         ["rapide", "sucre", "vegetarien"], [
        "Mixer les fraises et les mélanger au lait et aux flocons d'avoine.",
        "Chauffer 45 s au micro-ondes, remuer, puis 30 s de plus."]),
    15: ("pdj-oeufs-pizzaiola-baguette-etm", "Œufs pochés à la pizzaiola et baguette", "petit-dejeuner",
         ["poele", "sale", "vegetarien"], [
        "Dorer l'ail 1 min dans l'huile, ajouter persil, tomates concassées et bouillon, porter à ébullition puis ajouter le basilic.",
        "Laisser mijoter 5 min, casser les œufs dans la sauce, parsemer de parmesan et cuire 10 à 15 min à couvert.",
        "Servir avec la baguette."]),
    16: ("pdj-overnight-oats-myrtilles-lin-etm", "Overnight oats aux myrtilles et graines de lin", "petit-dejeuner",
         ["prepare-la-veille", "sans-cuisson", "sucre", "vegetarien", "transportable"], [
        "La veille, superposer dans un bocal flocons d'avoine, 160 g d'eau, fromage blanc 0 %, graines de lin et myrtilles, sans mélanger.",
        "Le matin, mélanger et parsemer de noix concassées."]),
    17: ("dej-salade-nicoise-thon-lentilles-etm", "Salade niçoise au thon, lentilles et œuf", "dejeuner",
         ["poisson", "tiede"], [
        "Cuire les lentilles 20 min à l'eau, égoutter. Cuire l'œuf 8 min, ajouter les haricots verts la dernière minute.",
        "Saisir le thon 1 à 2 min par face dans l'huile de coco (ou utiliser du thon au naturel).",
        "Mélanger épinards, lentilles, haricots, tomates séchées, noix, huile d'olive et balsamique ; garnir de thon et d'œuf coupé en deux."]),
    18: ("dej-jambalaya-poulet-riz-complet-etm", "Jambalaya de poulet au riz complet", "dejeuner",
         ["one-pot", "plat-complet", "epice"], [
        "Dorer le poulet en dés 5 à 8 min dans l'huile, réserver. Faire fondre l'oignon 3 min, ajouter poivron et ail 5 min.",
        "Remettre le poulet, ajouter le riz, les tomates concassées et 12 cl de bouillon, couvrir et mijoter 20 à 25 min."]),
    20: ("dej-salade-lentilles-poire-noisettes-feta-etm", "Salade de lentilles, poire, noisettes et feta", "dejeuner",
         ["tiede", "vegetarien", "transportable"], [
        "Cuire les lentilles rincées 20 min à l'eau frémissante, égoutter et laisser tiédir.",
        "Mélanger avec la poire en dés, les noisettes, la feta et la roquette.",
        "Arroser de vinaigre balsamique, mélanger délicatement et servir."]),
    22: ("dej-cabillaud-tomate-olives-mozzarella-etm", "Cabillaud à la tomate, olives et mozzarella", "dejeuner",
         ["poele", "poisson"], [
        "Faire fondre le beurre, dorer les lardons et l'oignon 2 min, ajouter l'ail 30 s.",
        "Ajouter le cabillaud 2 min en le retournant, puis les tomates concassées ; mijoter 2 à 3 min.",
        "Ajouter olives et mozzarella hors du feu, laisser fondre, servir parsemé de pignons et de basilic."]),
    25: ("dej-wrap-poulet-cesar-etm", "Wrap de poulet façon César", "dejeuner",
         ["four", "transportable"], [
        "Cuire le poulet 15 à 20 min au four à 200 °C, puis le couper en dés.",
        "Mélanger poulet, laitue émincée, parmesan, tomate en dés et mayonnaise, garnir la tortilla et rouler."]),
    26: ("dej-wok-thon-legumes-etm", "Wok de légumes au thon et soja", "dejeuner",
         ["wok", "rapide", "poisson"], [
        "Mettre les légumes surgelés, le thon égoutté, la sauce soja et le citron dans un wok à feu moyen.",
        "Couvrir et cuire 10 min en remuant toutes les 2 min."]),
    27: ("din-poulet-farci-epinards-feta-etm", "Poulet farci aux épinards et à la feta", "diner",
         ["four", "batch"], [
        "Préchauffer le four à 165 °C. Aplatir les blancs de poulet et les assaisonner.",
        "Mélanger épinards décongelés et essorés, mayonnaise, ail haché et feta.",
        "Inciser le poulet, le farcir, fermer avec des piques, saupoudrer de paprika et cuire 45 min."]),
    29: ("din-cabillaud-asperges-ail-etm", "Cabillaud poêlé et asperges à l'ail", "diner",
         ["poele", "poisson", "rapide"], [
        "Cuire le cabillaud assaisonné 4 à 5 min par face dans la moitié de l'huile, le réserver.",
        "Dans la même poêle, faire revenir l'ail 1 min dans le reste d'huile, puis les asperges 4 à 5 min."]),
    30: ("din-cabillaud-petits-pois-menthe-etm", "Cabillaud poêlé et petits pois à la menthe", "diner",
         ["poele", "poisson", "rapide"], [
        "Cuire le cabillaud salé 3 à 4 min par face dans l'huile chaude.",
        "Pendant ce temps, cuire les petits pois 2 à 3 min à l'eau bouillante, égoutter.",
        "Mélanger les petits pois avec la menthe hachée, le beurre et le jus de citron, servir avec le poisson."]),
    31: ("din-salade-poulet-pois-chiches-menthe-etm", "Salade de poulet, pois chiches, feta et menthe", "diner",
         ["froid", "transportable"], [
        "Cuire le poulet dans l'huile 5 à 10 min par face, laisser reposer puis couper en dés.",
        "Égoutter les pois chiches, couper concombre et oignon.",
        "Mélanger avec épinards, feta, menthe, ail, fromage blanc 0 % et le jus du citron."]),
    34: ("din-filet-mignon-croute-chapelure-etm", "Filet mignon de porc en croûte de chapelure", "diner",
         ["four", "batch"], [
        "Préchauffer le four à 220 °C. Mélanger chapelure et huile d'olive, en couvrir le filet mignon.",
        "Cuire au moins 35 min (75 °C à cœur), laisser reposer 10 min avant de trancher."]),
    35: ("col-fromage-blanc-fraises-etm", "Fromage blanc 0 % aux fraises", "collation",
         ["sans-cuisson", "rapide", "sucre", "vegetarien"], [
        "Couper les fraises en lamelles.",
        "Les mélanger au fromage blanc."]),
    40: ("col-muffins-oeufs-legumes-etm", "Muffins d'œufs aux légumes et cheddar", "collation",
         ["four", "batch", "sale", "vegetarien", "transportable"], [
        "Préchauffer le four à 200 °C. Couper poivron, oignon, épinards et tomates en dés.",
        "Mélanger avec les œufs battus et le cheddar, répartir dans des moules à muffins huilés.",
        "Cuire 15 à 18 min, jusqu'à ce que le dessus soit ferme."]),
    41: ("col-tomate-farcie-thon-etm", "Tomate farcie au thon et fromage blanc", "collation",
         ["sans-cuisson", "rapide", "poisson"], [
        "Couper la tomate en deux et l'évider légèrement.",
        "Mélanger thon égoutté, oignon haché, fromage blanc 0 % et aneth, garnir les demi-tomates."]),
}


def main():
    brut = json.loads((ICI / "eatthismuch_raw.json").read_text(encoding="utf-8"))["recettes"]
    lot, rapport = [], []
    for i, fiche in FICHES.items():
        src = brut[i]
        ident, nom, type_repas, tags, etapes = fiche
        n = src["servings"]
        grammes: dict[str, float] = {}
        for ing in src["ingredients"]:
            if ing["nom"] not in CORRESPONDANCE:
                raise SystemExit(f"{i} {src['nom_en']} : ingrédient sans correspondance {ing['nom']}")
            cle = CORRESPONDANCE[ing["nom"]]
            if cle is None:
                continue
            g = ing["grams_total_recipe"] * FACTEUR.get(ing["nom"], 1) / n
            grammes[cle] = grammes.get(cle, 0) + g
        ingredients = [{"cle": c, "quantite_g": max(1, round(g))} for c, g in grammes.items() if g >= 0.5]
        if len(ingredients) > 12:  # plafond du catalogue : on retire le condiment le plus négligeable
            ingredients = [l for l in ingredients if l["cle"] != "vinaigre_cidre"]
        temps = (src.get("prep_min") or 0) + (src.get("cook_min") or 0)
        if "prepare-la-veille" in tags:
            temps = 5
        m = src["macros_par_portion"]
        recette = {
            "id": ident, "nom": nom, "type": type_repas, "portions": 1, "temps_min": temps,
            "ingredients": ingredients, "etapes": etapes, "tags": tags,
            "origine": {
                "site": "eatthismuch.com", "url": src["url"], "nom_original": src["nom_en"],
                "portions_originales": n,
                "macros_annoncees": {k: m[k] for k in ("calories", "proteines", "glucides", "lipides", "fibres")},
            },
        }
        calc = macros_recette(recette)
        ecart = (calc["calories"] - m["calories"]) / m["calories"]
        rapport.append((i, nom, m, calc, ecart))
        lot.append(recette)
    (ICI / "lot_eatthismuch.json").write_text(
        json.dumps({"recettes": lot}, ensure_ascii=False, indent=1), encoding="utf-8")
    for i, nom, m, c, e in rapport:
        drapeau = "  <<" if abs(e) > 0.15 or abs(c["proteines"] - m["proteines"]) > 6 else ""
        print(f"{i:2} {nom[:48]:48} site {m['calories']:4}/{m['proteines']:3}P  ciqual {c['calories']:4}/{c['proteines']:3}P  {e:+.0%}{drapeau}")


if __name__ == "__main__":
    main()
