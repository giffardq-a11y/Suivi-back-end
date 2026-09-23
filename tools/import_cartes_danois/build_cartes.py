"""Assemble cartes_danois_raw.json a partir de verif.json (mots) + phrases.txt (loecsen)."""
import json, os, re, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
rk = json.load(open(os.path.join(HERE, "freq", "rangs.json"), encoding="utf-8"))
verif = json.load(open(os.path.join(HERE, "verif.json"), encoding="utf-8"))
pairs = json.load(open(os.path.join(HERE, "freq", "loecsen_pairs.json"), encoding="utf-8"))
LOECSEN = "https://www.loecsen.com/fr/vocabulaire-danois"

SANS_ARTICLE = {"januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september",
                "oktober", "november", "december", "nord", "syd", "øst", "vest"}
INDENOMBRABLE = {"mad", "sukker", "salt", "mel", "smør", "ris", "pasta", "havregryn", "yoghurt", "juice",
                 "fløde", "olie", "honning", "spinat", "majs", "protein", "blod", "musik", "medicin",
                 "sundhed", "søvn", "græs", "politi", "svinekød", "oksekød", "skinke", "feber", "tid"}
FRONT = {"forælder": ("le parent", None), "højre": ("droite", "à droite = til højre"),
         "venstre": ("gauche", "à gauche = til venstre")}
DEF_SUFFIX = {"c": "en", "n": "et"}


def plural(tpl, lemma):
    m = re.search(r"\{\{da-nom-([cn])-([a-z0-9]+)((?:\|[^}]*)?)\}\}", tpl)
    if not m:
        return None, None
    g, suf, args = m.group(1), m.group(2), m.group(3)
    kv, pos = {}, []
    for a in [x for x in args.split("|") if x]:
        if "=" in a:
            k, v = a.split("=", 1); kv[k.strip()] = v.strip()
        else:
            pos.append(a.strip())
    for i, v in enumerate(pos, 1):
        kv.setdefault(str(i), v)
    if kv.get("sing"):
        return g, None
    if kv.get("3"):
        return g, kv["3"]
    base = kv.get("rac-pl") or kv.get("rac") or kv.get("racine") or kv.get("1") or lemma
    if suf == "0":
        base = kv.get("rac-pl") or kv.get("1") or lemma
        return g, base
    if suf in ("e", "er", "r", "s", "ere", "re"):  # "n" : règle incertaine, pas d indice
        return g, base + suf
    return g, None


def gender(sec, lemma):
    h = sec["head"] + " " + sec["tpl"]
    if sec.get("site") == "en" or h.startswith("{{da-noun") or "{{head|da" in h:
        m = re.search(r"g=([cn])\b", h) or re.search(r"\{\{da-noun\|(?:[^}|]*\|)?(?:g=)?([cn])[|}]", h)
        if m:
            return m.group(1)
        m = re.search(r"\{\{da-noun\|([^|}]*)", h)
        if m and m.group(1) in ("en", "et"):
            return "c" if m.group(1) == "en" else "n"
    if re.search(r"\{\{c(\|[^}]*)?\}\}", h):
        return "c"
    if re.search(r"\{\{n(\|[^}]*)?\}\}", h):
        return "n"
    g, _ = plural(sec["tpl"], lemma)
    return g


cartes, rejets, doublons = [], [], []
existant = open(os.path.join(HERE, "deck_existant.txt"), encoding="utf-8").read().splitlines()
ex_da = {l.split("=", 1)[1].strip().lower() for l in existant if "=" in l}
ex_fr = {l.split("|", 1)[1].split("=", 1)[0].strip().lower() for l in existant if "=" in l}

for r in verif:
    if not r["ok"]:
        rejets.append({"da": r["da"], "fr": r["fr"], "cat": r["cat"], "why": r["why"], "defs": r.get("defs", [])})
        continue
    sec, lemma, site = r["sec"], r["da"], r["site"]
    sec["site"] = site
    pos = sec["pos"].lower()
    nature = ("nom" if pos.startswith(("nom", "noun")) else "verbe" if pos.startswith(("verbe", "verb"))
              else "adjectif" if pos.startswith(("adjectif", "adjective")) else "adverbe" if pos.startswith(("adverbe", "adverb"))
              else "pronom" if pos.startswith(("pronom", "pronoun")) else pos)
    fr, hint = r["fr"], (r["hint_force"] or None)
    genre = None
    if nature == "nom":
        genre = gender(sec, lemma)
        _, pl = plural(sec["tpl"], lemma)
        art = {"c": "en", "n": "et"}.get(genre)
        if lemma in SANS_ARTICLE or not art:
            back = lemma
        elif lemma in INDENOMBRABLE:
            back = lemma
            hint = hint or f"indénombrable, genre {art}"
        else:
            back = f"{art} {lemma}"
            if pl and pl != lemma and not hint:
                hint = f"pl. {pl}"
            elif pl == lemma and not hint:
                hint = f"pl. {pl} (invariable)"
        if not art and lemma not in SANS_ARTICLE:
            hint = hint or "genre non indiqué par la source"
    elif nature == "verbe":
        back = "at " + lemma
    else:
        back = lemma
    if lemma in FRONT:
        fr, h2 = FRONT[lemma]
        hint = h2 or hint
    if back.lower() in ex_da or lemma.lower() in ex_da or fr.lower() in ex_fr:
        doublons.append(lemma); continue
    src = (f"https://fr.wiktionary.org/wiki/{urllib.parse.quote(lemma)}#da" if site == "fr"
           else f"https://en.wiktionary.org/wiki/{urllib.parse.quote(lemma)}#Danish")
    cartes.append({"francais": fr, "danois": back, "hint": hint, "categorie": r["cat"], "nature": nature,
                   "genre": genre, "source": src, "definitions_source": sec["defs"],
                   "frequence_rang": rk.get(lemma)})

# phrases (loecsen)
pset = {(f.strip(), d.strip()) for _, f, d in pairs}
for line in open(os.path.join(HERE, "phrases.txt"), encoding="utf-8"):
    if line.startswith("#") or not line.strip():
        continue
    cat, fr, da, lf, ld, hint = (line.rstrip("\n").split("|") + [""] * 6)[:6]
    if (lf, ld) not in pset:
        rejets.append({"da": da, "fr": fr, "cat": cat, "why": "loecsen: paire introuvable", "defs": []}); continue
    if da.lower() in ex_da or fr.lower() in ex_fr:
        doublons.append(da); continue
    cartes.append({"francais": fr, "danois": da, "hint": hint or None, "categorie": cat, "nature": "expression",
                   "genre": None, "source": LOECSEN, "definitions_source": [f"{lf} = {ld}"], "frequence_rang": None})

# doublons internes (meme danois)
vus, final = set(), []
for c in cartes:
    k = c["danois"].lower()
    if k in vus:
        doublons.append(k); continue
    vus.add(k); final.append(c)

json.dump({"cartes": final}, open(os.path.join(HERE, "cartes_danois_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(rejets, open(os.path.join(HERE, "rejets.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
from collections import Counter
print("cartes", len(final), Counter(c["categorie"] for c in final))
print("rejets", len(rejets), "doublons", doublons)
print("sources", Counter(c["source"].split("/")[2] for c in final))
