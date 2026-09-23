"""Verifie chaque candidat contre fr.wiktionary (repli en.wiktionary). Cache dans wiktionnaire_cache/."""
import json, os, re, time, urllib.parse, urllib.request, urllib.error, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "wiktionnaire_cache")
UA = {"User-Agent": "suivi-app-cartes/0.1 (usage personnel)"}
os.makedirs(CACHE, exist_ok=True)


def fetch(site, page):
    fn = os.path.join(CACHE, f"{site}_" + urllib.parse.quote(page, safe="") + ".json")
    if os.path.exists(fn):
        d = json.load(open(fn, encoding="utf-8"))
        if d.get("error") != "fetch failed":
            return d
    url = f"https://{site}.wiktionary.org/w/api.php?action=parse&page={urllib.parse.quote(page)}&prop=wikitext&format=json&redirects=1&maxlag=5"
    for essai in range(6):
        try:
            data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
            break
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After")
            wait = int(ra) if ra and ra.isdigit() else 20 * (essai + 1)
            print("  retry", page, e, "wait", wait, file=sys.stderr, flush=True)
            time.sleep(wait)
        except Exception as e:
            print("  retry", page, e, file=sys.stderr, flush=True)
            time.sleep(10)
    else:
        time.sleep(1.5)
        return {"error": "fetch failed"}  # non mis en cache
    json.dump(data, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(1.5)
    return data


def clean(s):
    s = re.sub(r"\{\{(?:lexique|term|figuré|familier|sens figuré|vieilli|désuet|par extension|argot|populaire|soutenu|au pluriel|pluriel)\|([^|}]*)[^}]*\}\}", r"(\1)", s)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip(" #:")


def sections_fr(wt):
    m = re.search(r"==\s*\{\{langue\|da\}\}\s*==", wt)
    if not m:
        return None
    rest = wt[m.end():]
    n = re.search(r"\n==\s*\{\{langue\|", rest)
    body = rest[: n.start()] if n else rest
    out = []
    parts = re.split(r"\n===\s*\{\{S\|([^|}]+)\|da[^}]*\}\}\s*===", body)
    for i in range(1, len(parts), 2):
        pos, txt = parts[i].strip(), parts[i + 1]
        txt = re.split(r"\n====", txt)[0]
        lines = txt.split("\n")
        head = next((l for l in lines if l.startswith("'''")), "")
        tpl = " ".join(l for l in lines if l.startswith("{{da-"))
        defs = [clean(l) for l in lines if re.match(r"#(?![*:])", l)]
        out.append({"pos": pos, "head": head, "tpl": tpl, "defs": [d for d in defs if d]})
    return out


def sections_en(wt):
    m = re.search(r"(?m)^==Danish==\s*$", wt)
    if not m:
        return None
    rest = wt[m.end():]
    n = re.search(r"(?m)^==[^=]", rest)
    body = rest[: n.start()] if n else rest
    out = []
    parts = re.split(r"(?m)^===+\s*([A-Za-z ]+?)\s*===+\s*$", body)
    for i in range(1, len(parts), 2):
        pos, txt = parts[i].strip(), parts[i + 1]
        lines = txt.split("\n")
        head = next((l for l in lines if l.startswith("{{da-") or l.startswith("{{head|da")), "")
        defs = [clean(l) for l in lines if re.match(r"#(?![*:])", l)]
        if defs:
            out.append({"pos": pos.lower(), "head": head, "tpl": head, "defs": [d for d in defs if d]})
    return out


POSMAP_FR = {"nom": "nom", "verbe": "verbe", "adjectif": "adjectif", "adverbe": "adverbe", "pronom": "pronom"}
POSMAP_EN = {"nom": "noun", "verbe": "verb", "adjectif": "adjective", "adverbe": "adverb", "pronom": "pronoun"}


def match(kws, defs):
    txt = " | ".join(defs).lower().replace("’", "'")
    for kw in kws:
        k = kw.lower().strip()
        if not k:
            continue
        if re.search(r"(?<![\w])" + re.escape(k) + r"(s|x|e|es)?(?![\w])", txt):
            return kw
    return None


def verify(da, pos, kws, en_kw):
    wt = fetch("fr", da)
    if "parse" in wt:
        secs = sections_fr(wt["parse"]["wikitext"]["*"])
        if secs:
            ordered = sorted(secs, key=lambda s: 0 if s["pos"].startswith(POSMAP_FR.get(pos, pos)) else 1)
            for s in ordered:
                k = match(kws, s["defs"])
                if k:
                    return {"ok": True, "site": "fr", "sec": s, "kw": k}
            return {"ok": False, "why": "fr: section da sans le sens", "defs": [d for s in secs for d in s["defs"]][:6]}
        why_fr = "fr: pas de section da"
    else:
        why_fr = "fr: echec reseau" if wt.get("error") == "fetch failed" else "fr: page absente"
    if en_kw:
        wt = fetch("en", da)
        if "parse" in wt:
            secs = sections_en(wt["parse"]["wikitext"]["*"])
            if secs:
                ordered = sorted(secs, key=lambda s: 0 if s["pos"].startswith(POSMAP_EN.get(pos, pos)) else 1)
                for s in ordered:
                    k = match([en_kw], s["defs"])
                    if k:
                        return {"ok": True, "site": "en", "sec": s, "kw": k, "why_fr": why_fr}
                return {"ok": False, "why": why_fr + " ; en: sens absent", "defs": [d for s in secs for d in s["defs"]][:6]}
        return {"ok": False, "why": why_fr + " ; en: pas de section Danish"}
    return {"ok": False, "why": why_fr}


if __name__ == "__main__":
    res = []
    for line in open(os.path.join(HERE, "candidats.txt"), encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        cat, fr, da, pos, kws, en_kw, hint = (line.rstrip("\n").split("|") + [""] * 7)[:7]
        r = verify(da, pos, kws.split(";"), en_kw)
        r.update({"cat": cat, "fr": fr, "da": da, "pos": pos, "hint_force": hint})
        res.append(r)
        print(("OK " if r["ok"] else "NO ") + da + " = " + fr + ("" if r["ok"] else "  <" + r["why"] + "> " + " / ".join(r.get("defs", []))[:200]), flush=True)
    json.dump(res, open(os.path.join(HERE, "verif.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
