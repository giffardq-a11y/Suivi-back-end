"""Contrôle un fichier de recettes : ingrédients connus, quantités plausibles,
macros dans les clous (voir app/recettes.py).

    python tools/valider_recettes.py                 # le catalogue livré
    python tools/valider_recettes.py mon_lot.json    # un lot en cours d'écriture
    python tools/valider_recettes.py mon_lot.json --detail   # + macros recette par recette

Sort en code 1 si une anomalie est trouvée : à lancer avant de proposer un lot.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.recettes import FICHIER_RECETTES, TYPES_REPAS, macros_recette, valider  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fichier", nargs="?", default=str(FICHIER_RECETTES))
    ap.add_argument("--detail", action="store_true", help="affiche les macros de chaque recette")
    args = ap.parse_args()

    chemin = Path(args.fichier)
    if not chemin.exists():
        print(f"Fichier introuvable : {chemin}")
        return 1

    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    liste = donnees.get("recettes", [])
    print(f"{chemin.name} : {len(liste)} recettes")
    for type_repas in TYPES_REPAS:
        print(f"   {type_repas:16} {sum(1 for r in liste if r.get('type') == type_repas)}")

    if args.detail:
        print()
        for recette in liste:
            m = macros_recette(recette)
            print(f"  {recette.get('nom', '?')[:44]:44} {m['calories']:>5} kcal  "
                  f"P{m['proteines']:>4} G{m['glucides']:>4} L{m['lipides']:>4}")

    erreurs = valider(donnees)
    if erreurs:
        print(f"\n{len(erreurs)} anomalie(s) :")
        for erreur in erreurs:
            print(f"  {erreur}")
        return 1
    print("\nAucune anomalie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
