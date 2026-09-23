"""Contre-vérifie le genre des noms sur en.wiktionary (le genre de fr.wiktionary est parfois faux
pour le danois : « tante » y est neutre, « universitet » commun).

Règle : genre en.wiktionary disponible -> il fait foi (article corrigé si besoin) ;
sinon l'article est retiré (carte sans article, comme l'ancien jeu), faute de confirmation.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ICI, "wiktionnaire_cache")
UA = {"User-Agent": "suivi-app-cartes/0.1 (usage personnel)"}


def fetch_en(page):
    fn = os.path.join(CACHE, "en_" + urllib.parse.quote(page, safe="") + ".json")
    if os.path.exists(fn):
        d = json.load(open(fn, encoding="utf-8"))
        if d.get("error") != "fetch failed":
            return d
    url = ("https://en.wiktionary.org/w/api.php?action=parse&page=" + urllib.parse.quote(page)
           + "&prop=wikitext&format=json&redirects=1&maxlag=5")
    for essai in range(6):
        try:
            data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
            break
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After")
            time.sleep(int(ra) if ra and ra.isdigit() else 20 * (essai + 1))
        except Exception:
            time.sleep(10)
    else:
        return {"error": "fetch failed"}
    json.dump(data, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(1.5)
    return data


def genre_en(lemme):
    d = fetch_en(lemme)
    t = d.get("parse", {}).get("wikitext", {}).get("*", "")
    i = t.find("==Danish==")
    if i < 0:
        return None
    j = t.find("\n==", i + 10)
    while j >= 0 and t[j:j + 4] == "\n===":
        j = t.find("\n==", j + 3)
    sec = t[i:j if j > 0 else None]
    genres = set()
    for m in re.finditer(r"\{\{da-noun\|([^}]*)\}\}", sec):
        args = m.group(1).split("|")
        kv = dict(a.split("=", 1) for a in args if "=" in a)
        pos = [a for a in args if "=" not in a]
        if kv.get("g") in ("c", "n"):
            genres.add(kv["g"])
        elif pos and pos[0] in ("en", "n", "et", "t"):
            genres.add("c" if pos[0] in ("en", "n") else "n")
    for m in re.finditer(r"\{\{head\|da\|noun[^}]*\|g=([cn])", sec):
        genres.add(m.group(1))
    return genres.pop() if len(genres) == 1 else None


def main():
    chemin = os.path.join(ICI, "cartes_danois_raw.json")
    cartes = json.load(open(chemin, encoding="utf-8"))["cartes"]
    bilan = {"confirme": 0, "corrige": [], "sans_article": []}
    for c in cartes:
        mots = c["danois"].split()
        if c.get("nature") != "nom" or mots[0] not in ("en", "et") or len(mots) != 2:
            continue
        lemme, art = mots[1], mots[0]
        g = genre_en(lemme)
        if g is None:
            c["danois"] = lemme
            c["genre"] = None
            if c.get("hint", "") and c["hint"].startswith("pl."):
                c["hint"] = None
            bilan["sans_article"].append(lemme)
            continue
        bon = "en" if g == "c" else "et"
        c["genre_verifie"] = f"https://en.wiktionary.org/wiki/{urllib.parse.quote(lemme)}#Danish"
        if bon != art:
            c["danois"] = f"{bon} {lemme}"
            c["genre"] = g
            bilan["corrige"].append(f"{art} {lemme} -> {bon} {lemme}")
        else:
            bilan["confirme"] += 1
        print(".", end="", flush=True, file=sys.stderr)
    json.dump({"cartes": cartes}, open(chemin, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
