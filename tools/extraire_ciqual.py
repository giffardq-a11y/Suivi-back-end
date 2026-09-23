"""Construit app/data/ingredients.json depuis la table CIQUAL (ANSES).

CIQUAL est la table de composition nutritionnelle officielle française
(open data, sans clé d'API). On n'en garde que les ingrédients dont les
recettes ont besoin, avec pour chacun le code CIQUAL retenu : les macros des
recettes sont ensuite **calculées** à partir de cette table, jamais saisies à
la main.

    python tools/extraire_ciqual.py --verifier   # montre le nom CIQUAL retenu pour chaque ingredient
    python tools/extraire_ciqual.py              # ecrit app/data/ingredients.json

Le zip CIQUAL (3,5 Mo) est téléchargé une fois et mis en cache dans
tools/.cache/ (ignoré par git) : la génération est ensuite hors ligne.

Deux pièges du fichier officiel, traités par _nettoyer_xml : des « < » et des
« & » littéraux dans les libellés (« Panaché préemballé (<1° alc.) »,
« Tendre et léger elle & Vire ») rendent le XML non conforme.

Poids **crus** partout (« riz cru », « poulet cru ») : c'est ce qu'on pèse en
cuisinant et ce qu'on achète, donc ce que la liste de courses doit compter.
"""
import argparse
import json
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
CACHE = ICI / ".cache" / "ciqual.zip"
SORTIE = RACINE / "app" / "data" / "ingredients.json"
URL = "https://ciqual.anses.fr/cms/sites/default/files/inline-files/XML_2020_07_07.zip"

# Codes des constituants CIQUAL utilisés (cf. const_2020_07_07.xml).
KCAL, PROTEINES, GLUCIDES, LIPIDES, FIBRES = "328", "25000", "31000", "40000", "34100"

# Un ingrédient : (clé, libellé affiché, motif de recherche dans CIQUAL, rayon,
# unité d'achat, conditionnement courant). Le motif est une expression
# régulière appliquée au nom CIQUAL ; _choisir tranche entre les candidats.
# « code: » en tête du motif épingle un code CIQUAL précis quand la recherche
# par nom retombe sur le mauvais aliment.
INGREDIENTS = [
    # --- Viandes, volailles, œufs ---------------------------------------
    ("poulet_filet", "Blanc de poulet", r"code:36017", "boucherie", "g", 500),
    ("poulet_cuisse", "Cuisse de poulet", r"^Poulet, cuisse.*cru", "boucherie", "g", 600),
    ("dinde_escalope", "Escalope de dinde", r"^Dinde, (escalope|blanc).*cru", "boucherie", "g", 500),
    ("boeuf_hache_5", "Steak haché de bœuf 5 %", r"code:6250", "boucherie", "g", 500),
    ("boeuf_bavette", "Bavette de bœuf", r"code:6212", "boucherie", "g", 400),
    ("porc_filet", "Filet mignon de porc", r"^Porc, filet mignon.*cru", "boucherie", "g", 500),
    ("jambon_blanc", "Jambon blanc", r"^Jambon (cuit|blanc).*découenné", "charcuterie", "g", 200),
    ("lardons", "Lardons", r"^Lardons?.*(nature|fumé)", "charcuterie", "g", 200),
    ("oeuf", "Œuf", r"code:22000", "frais", "piece", 6),
    ("blanc_oeuf", "Blanc d'œuf", r"code:22001", "frais", "g", 500),
    # --- Poissons et fruits de mer --------------------------------------
    ("saumon", "Pavé de saumon", r"code:26036", "poissonnerie", "g", 400),
    ("cabillaud", "Cabillaud", r"^Cabillaud.*cru", "poissonnerie", "g", 400),
    ("colin", "Colin", r"^(Colin|Lieu noir).*cru", "poissonnerie", "g", 400),
    ("truite", "Truite", r"^Truite.*crue", "poissonnerie", "g", 400),
    ("thon_naturel", "Thon au naturel", r"^Thon.*au naturel.*égoutté", "epicerie", "g", 140),
    ("sardine_boite", "Sardines à l'huile", r"^Sardine.*à l'huile.*égoutté", "epicerie", "g", 100),
    ("crevette", "Crevettes", r"^Crevette.*cuite", "poissonnerie", "g", 200),
    # --- Produits laitiers ----------------------------------------------
    ("skyr", "Skyr / fromage blanc 0 %", r"code:19644", "frais", "g", 500),
    ("fromage_blanc_3", "Fromage blanc 3 %", r"code:19646", "frais", "g", 500),
    ("yaourt_nature", "Yaourt nature", r"code:19544", "frais", "piece", 8),
    ("yaourt_grec", "Yaourt à la grecque", r"^Yaourt.*grec", "frais", "g", 400),
    ("lait_demi", "Lait demi-écrémé", r"^Lait.*demi-écrémé.*UHT", "frais", "ml", 1000),
    ("mozzarella", "Mozzarella", r"^Mozzarella", "frais", "g", 125),
    ("feta", "Feta", r"^Feta", "frais", "g", 200),
    ("parmesan", "Parmesan", r"^Parmesan", "frais", "g", 100),
    ("gruyere", "Emmental râpé", r"^Emmental", "frais", "g", 200),
    ("chevre_buche", "Bûche de chèvre", r"^Chèvre.*bûche|^Fromage de chèvre.*bûche", "frais", "g", 180),
    ("creme_legere", "Crème légère 8 %", r"code:19433", "frais", "ml", 200),
    ("beurre", "Beurre", r"^Beurre à 82.*doux|^Beurre doux", "frais", "g", 250),
    # --- Féculents, céréales, pains --------------------------------------
    ("riz_blanc", "Riz (cru)", r"^Riz blanc.*cru", "epicerie", "g", 1000),
    ("riz_complet", "Riz complet (cru)", r"^Riz.*complet.*cru", "epicerie", "g", 1000),
    ("pates", "Pâtes (crues)", r"code:9810", "epicerie", "g", 500),
    ("pates_completes", "Pâtes complètes (crues)", r"code:9870", "epicerie", "g", 500),
    ("semoule", "Semoule de blé (crue)", r"^Semoule de blé.*crue", "epicerie", "g", 500),
    ("quinoa", "Quinoa (cru)", r"^Quinoa.*cru", "epicerie", "g", 500),
    ("boulgour", "Boulgour (cru)", r"^Boulgour.*cru", "epicerie", "g", 500),
    ("pomme_terre", "Pommes de terre", r"code:4008", "primeur", "g", 1500),
    ("patate_douce", "Patate douce", r"^Patate douce.*crue", "primeur", "g", 1000),
    ("flocons_avoine", "Flocons d'avoine", r"code:9311", "epicerie", "g", 500),
    ("pain_complet", "Pain complet", r"code:7110", "boulangerie", "g", 500),
    ("pain_campagne", "Pain de campagne", r"^Pain de campagne", "boulangerie", "g", 500),
    ("tortilla", "Tortilla de blé", r"^(Tortilla|Galette de blé)", "epicerie", "piece", 8),
    ("muesli", "Muesli", r"^Muesli.*sans sucre|^Muesli floconneux", "epicerie", "g", 750),
    # --- Légumineuses -----------------------------------------------------
    ("lentilles", "Lentilles vertes (sèches)", r"code:20585", "epicerie", "g", 500),
    ("pois_chiches", "Pois chiches (en conserve)", r"code:20532", "epicerie", "g", 400),
    ("haricots_rouges", "Haricots rouges (en conserve)", r"code:20524", "epicerie", "g", 400),
    ("haricots_blancs", "Haricots blancs (en conserve)", r"code:20511", "epicerie", "g", 400),
    ("tofu", "Tofu nature", r"^Tofu", "frais", "g", 250),
    # --- Légumes ----------------------------------------------------------
    ("brocoli", "Brocoli", r"code:20057", "primeur", "g", 500),
    ("haricot_vert", "Haricots verts", r"^Haricot vert.*cru", "primeur", "g", 500),
    ("courgette", "Courgette", r"^Courgette.*crue", "primeur", "g", 500),
    ("aubergine", "Aubergine", r"code:20053", "primeur", "g", 400),
    ("carotte", "Carotte", r"^Carotte.*crue", "primeur", "g", 1000),
    ("tomate", "Tomate", r"^Tomate.*crue", "primeur", "g", 500),
    ("tomate_cerise", "Tomates cerises", r"^Tomate cerise", "primeur", "g", 250),
    ("tomate_concassee", "Tomates concassées", r"^Tomate.*(pelée|concassée).*appertisée", "epicerie", "g", 400),
    ("poivron", "Poivron", r"^Poivron.*cru", "primeur", "g", 400),
    ("oignon", "Oignon", r"^Oignon.*cru", "primeur", "g", 500),
    ("echalote", "Échalote", r"^Échalote.*crue", "primeur", "g", 200),
    ("ail", "Ail", r"^Ail.*cru", "primeur", "g", 100),
    ("champignon", "Champignons de Paris", r"^Champignon de Paris.*cru", "primeur", "g", 250),
    ("epinard", "Épinards", r"^Épinard.*cru", "primeur", "g", 500),
    ("salade", "Salade verte", r"code:20031", "primeur", "piece", 1),
    ("concombre", "Concombre", r"^Concombre.*cru", "primeur", "g", 400),
    ("chou_fleur", "Chou-fleur", r"^Chou-fleur.*cru", "primeur", "g", 600),
    ("poireau", "Poireau", r"^Poireau.*cru", "primeur", "g", 500),
    ("petit_pois", "Petits pois surgelés", r"code:20084", "surgeles", "g", 500),
    ("ratatouille", "Légumes pour ratatouille (surgelés)", r"code:20266", "surgeles", "g", 750),
    ("betterave", "Betterave cuite", r"^Betterave.*cuite", "primeur", "g", 500),
    ("avocat", "Avocat", r"^Avocat.*cru", "primeur", "piece", 2),
    # --- Fruits ------------------------------------------------------------
    ("banane", "Banane", r"^Banane.*crue", "primeur", "piece", 6),
    ("pomme", "Pomme", r"code:13039", "primeur", "piece", 6),
    ("poire", "Poire", r"^Poire.*crue", "primeur", "piece", 4),
    ("orange", "Orange", r"^Orange.*pulpe.*crue|^Orange, crue", "primeur", "piece", 4),
    ("kiwi", "Kiwi", r"^Kiwi.*cru", "primeur", "piece", 6),
    ("fraise", "Fraises", r"^Fraise.*crue", "primeur", "g", 250),
    ("fruits_rouges", "Fruits rouges", r"code:13997", "surgeles", "g", 450),
    ("citron", "Citron", r"^Citron.*pulpe.*cru|^Citron, cru", "primeur", "piece", 4),
    ("raisin_sec", "Raisins secs", r"^Raisin.*sec", "epicerie", "g", 250),
    ("datte", "Dattes", r"code:13011", "epicerie", "g", 250),
    # --- Matières grasses, oléagineux ---------------------------------------
    ("huile_olive", "Huile d'olive", r"^Huile d'olive", "epicerie", "ml", 750),
    ("huile_colza", "Huile de colza", r"^Huile de colza", "epicerie", "ml", 500),
    ("amande", "Amandes", r"code:15000", "epicerie", "g", 200),
    ("noix", "Noix", r"code:15005", "epicerie", "g", 200),
    ("noisette", "Noisettes", r"code:15004", "epicerie", "g", 200),
    ("beurre_cacahuete", "Beurre de cacahuète", r"code:15202", "epicerie", "g", 350),
    ("graines_tournesol", "Graines de tournesol", r"code:15011", "epicerie", "g", 200),
    # --- Épicerie, condiments, divers -----------------------------------------
    ("miel", "Miel", r"^Miel", "epicerie", "g", 250),
    ("chocolat_noir", "Chocolat noir 70 %", r"code:31074", "epicerie", "g", 100),
    ("cacao", "Cacao non sucré", r"^Cacao.*non sucré|^Chocolat en poudre.*non sucré", "epicerie", "g", 250),
    ("sauce_soja", "Sauce soja", r"^Sauce soja", "epicerie", "ml", 250),
    ("moutarde", "Moutarde", r"^Moutarde", "epicerie", "g", 200),
    ("vinaigre_balsamique", "Vinaigre balsamique", r"^Vinaigre balsamique", "epicerie", "ml", 250),
    ("bouillon", "Bouillon de légumes (cube)", r"code:11174", "epicerie", "g", 100),
    ("farine", "Farine de blé", r"^Farine de blé.*T55|^Farine de blé tendre", "epicerie", "g", 1000),
    ("lait_coco", "Lait de coco", r"^Lait de coco", "epicerie", "ml", 400),
    ("curry", "Curry (poudre)", r"^Curry", "epicerie", "g", 40),
    ("paprika", "Paprika", r"^Paprika", "epicerie", "g", 40),
    ("herbes_provence", "Herbes de Provence", r"code:11060", "epicerie", "g", 30),
    ("olive_noire", "Olives noires", r"^Olive noire", "epicerie", "g", 200),
    ("pesto", "Pesto", r"^(Pesto|Sauce pesto)", "epicerie", "g", 190),
]

# Poids net moyen d'une pièce, pour les ingrédients qui s'achètent à l'unité :
# les recettes pèsent en grammes, la liste de courses parle en pièces (« 4
# œufs » plutôt que « 200 g d'œuf »). Ordres de grandeur du commerce.
POIDS_PIECE_G = {
    "oeuf": 50,          # œuf moyen sans coquille
    "yaourt_nature": 125,
    "tortilla": 45,
    "salade": 150,
    "avocat": 150,       # chair, sans peau ni noyau
    "banane": 120,       # pulpe
    "pomme": 150,
    "poire": 150,
    "orange": 180,
    "kiwi": 75,
    "citron": 60,
}

PREFERES = ("cru", "crue", "nature", "frais", "fraîche", "sans sel", "non sucré")
PENALISES = ("plat préparé", "préemballé", "industriel", "reconstitué", "déshydraté",
             "assaisonné", "aromatisé", "sucré", "allégé en matières grasses",
             "enrichi", "pour bébé", "infantile", "fast food", "restaurant")


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn").lower()


def _nettoyer_xml(brut: str) -> str:
    """CIQUAL laisse des « < » et des « & » littéraux dans les libellés."""
    brut = re.sub(r"&(?![a-zA-Z]+;|#\d+;)", "&amp;", brut)
    return re.sub(r"<(?=[\s\d])", "&lt;", brut)


def _telecharger() -> Path:
    if CACHE.exists():
        return CACHE
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Téléchargement de CIQUAL depuis {URL} ...")
    urllib.request.urlretrieve(URL, CACHE)
    print(f"  -> {CACHE} ({CACHE.stat().st_size // 1024} Ko)")
    return CACHE


def _lire(z: zipfile.ZipFile, motif: str) -> ET.Element:
    nom = next(i.filename for i in z.infolist() if i.filename.startswith(motif))
    return ET.fromstring(_nettoyer_xml(z.read(nom).decode("windows-1252")))


def macros(code: str, compositions: dict) -> dict | None:
    """Macros pour 100 g d'un aliment CIQUAL, ou None s'il n'est pas exploitable.

    Beaucoup d'entrées brutes (brocoli cru, amande, miel, laitue...) ont leurs
    protéines/glucides/lipides mais **pas** le champ énergie de CIQUAL, laissé
    à « - ». On recalcule alors les kcal avec les coefficients d'Atwater
    (4/4/9, et 2 pour les fibres) plutôt que d'écarter l'ingrédient — et on
    note d'où vient la valeur."""
    valeurs = compositions.get(code, {})
    if not all(c in valeurs for c in (PROTEINES, GLUCIDES, LIPIDES)):
        return None
    p, g, l = valeurs[PROTEINES], valeurs[GLUCIDES], valeurs[LIPIDES]
    fibres = valeurs.get(FIBRES, 0.0)
    kcal, origine = valeurs.get(KCAL), "ciqual"
    if kcal is None:
        kcal, origine = 4 * p + 4 * g + 9 * l + 2 * fibres, "atwater"
    return {"kcal": round(kcal, 1), "proteines": round(p, 1), "glucides": round(g, 1),
            "lipides": round(l, 1), "fibres": round(fibres, 1), "kcal_source": origine}


def _teneur(valeur: str) -> float | None:
    """« 12,3 », « < 0,5 », « traces », « - » : CIQUAL ne donne pas que des nombres."""
    valeur = (valeur or "").strip().replace(" ", "").replace(" ", "")
    if not valeur or valeur == "-":
        return None
    if valeur.lower() in ("traces", "tracés"):
        return 0.0
    valeur = valeur.lstrip("<").replace(",", ".")
    try:
        return float(valeur)
    except ValueError:
        return None


def charger_ciqual() -> tuple[dict[str, str], dict[str, dict[str, float]]]:
    """Renvoie {code aliment: nom} et {code aliment: {code constituant: teneur}}."""
    with zipfile.ZipFile(_telecharger()) as z:
        aliments = {
            a.findtext("alim_code").strip(): a.findtext("alim_nom_fr").strip()
            for a in _lire(z, "alim_2020")
        }
        compositions: dict[str, dict[str, float]] = {}
        for c in _lire(z, "compo_2020"):
            code_alim = c.findtext("alim_code").strip()
            code_const = c.findtext("const_code").strip()
            if code_const not in (KCAL, PROTEINES, GLUCIDES, LIPIDES, FIBRES):
                continue
            teneur = _teneur(c.findtext("teneur"))
            if teneur is not None:
                compositions.setdefault(code_alim, {})[code_const] = teneur
    return aliments, compositions


def _choisir(motif: str, aliments: dict[str, str], compositions: dict) -> tuple[str, str] | None:
    """Meilleur aliment CIQUAL pour un motif : d'abord ceux qui ont des macros,
    puis les formes brutes (« cru », « nature ») plutôt que préparées, puis le
    nom le plus court — le plus générique en pratique."""
    if motif.startswith("code:"):
        code = motif[5:].strip()
        return (code, aliments[code]) if code in aliments else None

    regex = re.compile(_sans_accents(motif), re.IGNORECASE)
    candidats = []
    for code, nom in aliments.items():
        if not regex.search(_sans_accents(nom)):
            continue
        if macros(code, compositions) is None:
            continue
        nom_bas = _sans_accents(nom)
        score = sum(2 for mot in PREFERES if _sans_accents(mot) in nom_bas)
        score -= sum(3 for mot in PENALISES if _sans_accents(mot) in nom_bas)
        candidats.append((-score, len(nom), code, nom))
    if not candidats:
        return None
    _, _, code, nom = min(candidats)
    return code, nom


def construire(verifier: bool = False) -> list[dict]:
    aliments, compositions = charger_ciqual()
    print(f"CIQUAL : {len(aliments)} aliments, {len(compositions)} avec des macros\n")

    resultat, manquants = [], []
    for cle, libelle, motif, rayon, unite, conditionnement in INGREDIENTS:
        trouve = _choisir(motif, aliments, compositions)
        if not trouve:
            manquants.append((cle, motif))
            continue
        code, nom_ciqual = trouve
        m = macros(code, compositions)
        resultat.append({
            "cle": cle,
            "nom": libelle,
            "rayon": rayon,
            "unite": unite,
            "conditionnement": conditionnement,
            "poids_piece_g": POIDS_PIECE_G.get(cle),
            "kcal_100g": m["kcal"],
            "proteines_100g": m["proteines"],
            "glucides_100g": m["glucides"],
            "lipides_100g": m["lipides"],
            "fibres_100g": m["fibres"],
            "kcal_source": m["kcal_source"],
            "ciqual_code": code,
            "ciqual_nom": nom_ciqual,
        })
        if verifier:
            print(f"  {libelle:32} [{code:>6}] {nom_ciqual[:52]:52} "
                  f"{m['kcal']:>6} kcal P{m['proteines']:>5} G{m['glucides']:>5} L{m['lipides']:>5}"
                  f"{'  (kcal calculees)' if m['kcal_source'] == 'atwater' else ''}")

    sans_poids = [i["cle"] for i in resultat
                  if i["unite"] == "piece" and not i.get("poids_piece_g")]
    if sans_poids:
        # Sans poids unitaire, impossible de convertir les grammes d'une
        # recette en nombre de pièces à acheter.
        print("\nIngrédients vendus à la pièce sans poids unitaire (POIDS_PIECE_G) :")
        for cle in sans_poids:
            print(f"  {cle}")

    if manquants:
        print("\nAucune correspondance CIQUAL (motif à corriger) :")
        for cle, motif in manquants:
            print(f"  {cle:24} {motif}")
    return resultat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", action="store_true",
                    help="affiche la correspondance retenue sans rien écrire")
    args = ap.parse_args()

    ingredients = construire(verifier=args.verifier)
    print(f"\n{len(ingredients)} ingrédients sur {len(INGREDIENTS)} demandés.")
    if args.verifier:
        return 0

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(
        json.dumps({"source": "CIQUAL 2020 (ANSES), " + URL, "ingredients": ingredients},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"Écrit : {SORTIE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
