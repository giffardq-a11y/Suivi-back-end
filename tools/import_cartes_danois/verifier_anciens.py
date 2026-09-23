"""Audit des 182 cartes d'origine (écrites de mémoire) : sens vérifié sur fr.wiktionary (repli
en.wiktionary), genre des noms sur en.wiktionary, phrases cherchées dans les paires loecsen.com."""
import json
import os
import re
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
sys.path.insert(0, r"C:\Users\6144\Desktop\Ai project\suivi-app\backend")
from verify import verify  # noqa: E402
from verifier_genres import genre_en  # noqa: E402
from app.danish_deck import DECK  # noqa: E402

PAIRES = json.load(open(os.path.join(ICI, "freq", "loecsen_pairs.json"), encoding="utf-8"))


def norm(s):
    return re.sub(r"[^\wæøå ]", "", s.lower().replace("...", "")).strip()


def cherche_loecsen(da):
    cible = norm(da)
    for p in (PAIRES if isinstance(PAIRES, list) else PAIRES.get("paires", [])):
        fr, dk = p[-2], p[-1]
        if norm(dk) == cible or (cible and norm(dk).startswith(cible)):
            return fr, dk
    return None


def main():
    lignes = {}
    for l in open(os.path.join(ICI, "anciens.txt"), encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        champs = l.rstrip("\n").split("|")
        lignes[int(champs[0])] = champs[1:]
    rapport = []
    for i, (fr, back, hint, cat) in enumerate(DECK[:182]):
        champs = lignes.get(i, [""])
        r = {"i": i, "fr": fr, "da": back, "cat": cat}
        if champs[0]:
            lemme, pos, kws, en_kw = champs
            v = verify(lemme, pos, kws.split(";"), en_kw)
            r.update({"ok": v["ok"], "site": v.get("site"), "why": v.get("why"),
                      "defs": (v.get("sec") or {}).get("defs") or v.get("defs", [])})
            if pos == "nom" and v["ok"]:
                g = genre_en(lemme)
                r["genre_en"] = {"c": "en", "n": "et"}.get(g)
        else:
            trouve = cherche_loecsen(back)
            r.update({"ok": bool(trouve), "site": "loecsen" if trouve else None,
                      "why": None if trouve else "phrase absente de loecsen", "defs": list(trouve) if trouve else []})
        rapport.append(r)
        print(("OK " if r["ok"] else "NO ") + f"{i} {fr} = {back}" + ("" if r["ok"] else f"  <{r['why']}> " + " / ".join(r["defs"])[:160])
              + (f"  [genre {r['genre_en']}]" if r.get("genre_en") else ""), flush=True)
    json.dump(rapport, open(os.path.join(ICI, "audit_anciens.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
