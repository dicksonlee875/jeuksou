#!/usr/bin/env python3
"""Build the Jeuksou 著數碼 wallet page from data/deals.json.

    python build.py                 # writes public/index.html
    python build.py --out wallet.html

The page is one self-contained HTML file (English / 繁體 / 简体). Open it
in a browser, or host the public/ folder anywhere (GitHub Pages, Netlify...).
简体 text is converted from 繁體 with OpenCC, so you only maintain two languages.
"""
import argparse
import json
import re
import shutil
from pathlib import Path

from opencc import OpenCC

ROOT = Path(__file__).resolve().parent
_hk2s = OpenCC("hk2s").convert
# Mainland wording OpenCC doesn't change on its own. Add more pairs here if you spot them.
PHRASES = {"程式": "程序", "帐户": "账户", "结帐": "结账", "菲林相机": "胶片相机", "电邮": "电子邮件", "拣选": "挑选", "连系": "联系"}


def t2s(text):
    text = _hk2s(text)
    for a, b in PHRASES.items():
        text = text.replace(a, b)
    return text


# Words that say what a code is for. A site in several categories (Trip.com, Klook) only shows a code
# under the categories its text names; a code that names none keeps the category it was saved with.
CAT_WORDS = {
    "Hotels": r"hotel|酒店|住宿|旅館|民宿|resort|ryokan|accommodation|\bstays?\b",
    "Flights": r"flight|機票|航班|機位|airfare|\bfly\b",
    "Car rental": r"car (?:rental|hire)|rental car|租車|自駕",
    "Travel extras": r"esim|\bsim\b|wi-?fi|上網|rail|train|火車|鐵路|高鐵|transfer|接送|機場快綫|lounge|貴賓室|insurance|保險|巴士|\bbus\b|ferry|船票",
    "Activities": r"ticket|門票|\btours?\b|activit|attraction|景點|theme park|樂園|體驗|演出",
    "Shopping": r"shopping|購物|網購",
    "Food & rides": r"food|外賣|delivery|送餐|\brides?\b|taxi|的士|叫車",
}


def add_cats(data):
    for d in data["deals"]:
        site_cats = data["sites"].get(d["site"], {}).get("cats") or [d["cat"]]
        if len(site_cats) < 2:
            continue
        text = " ".join(str(d.get(f) or "") for f in ("title", "title_zh", "desc", "desc_zh", "big", "big_zh")).lower()
        if re.search(r"everything|sitewide|site-wide|全站|全單|all products|any booking", text):
            hits = site_cats                      # good on the whole site: show it everywhere
        else:
            hits = [c for c in site_cats if re.search(CAT_WORDS.get(c, r"$^"), text)]
        if hits:
            d["_cats"] = hits


def add_simplified(data):
    for d in data["deals"]:
        for f in ("title", "desc", "cond", "big"):
            if d.get(f + "_zh"):
                d[f + "_sc"] = t2s(d[f + "_zh"])
    for s in data["sites"].values():
        if s.get("note_zh"):
            s["note_sc"] = t2s(s["note_zh"])
    for c in data.get("perks", {}).get("cards", []):
        for o in [c, *c["perks"], *c.get("scope_by", {}).values()]:
            for f in ("scope", "title", "what"):
                if o.get(f + "_zh"):
                    o[f + "_sc"] = t2s(o[f + "_zh"])
    for g in data.get("programs", {}).get("programs", []):
        for r in [*g.get("rows", []), *g.get("map", [])]:
            if r.get("label_zh"):
                r["label_sc"] = t2s(r["label_zh"])
            if r.get("vals_zh"):
                r["vals_sc"] = [t2s(v) for v in r["vals_zh"]]
        for o in [g, *g["tiers"], *g["links"]]:
            for f in ("note", "need", "perks", "title", "what"):
                if o.get(f + "_zh"):
                    o[f + "_sc"] = t2s(o[f + "_zh"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=ROOT / "data" / "deals.json")
    ap.add_argument("--out", default=ROOT / "public" / "index.html")
    ap.add_argument("--keep-avoid", action="store_true", help='also show "avoid" entries (corporate numbers, fake codes)')
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    # "avoid" entries are notes to yourself (fake codes, company-only rate numbers).
    # They stay in deals.json so the scraper won't re-add them, but the public page leaves them out.
    if not args.keep_avoid:
        data["deals"] = [d for d in data["deals"] if d["status"] != "avoid"]
    # Card perks for the Perks tab, kept by hand in data/perks.json.
    perks = ROOT / "data" / "perks.json"
    if perks.exists():
        data["perks"] = json.loads(perks.read_text(encoding="utf-8"))
        data["perks"].pop("_help", None)
    progs = ROOT / "data" / "programs.json"
    if progs.exists():
        data["programs"] = json.loads(progs.read_text(encoding="utf-8"))
        data["programs"].pop("_help", None)
    add_simplified(data)
    add_cats(data)
    html = (ROOT / "template.html").read_text(encoding="utf-8")

    # Interface words: copy the 繁體 block and convert it to 简体.
    hant = re.search(r"/\*HANT\*/(.*?)/\*END_HANT\*/", html, re.S).group(1)
    html = html.replace("/*__HANS__*/{}", t2s(hant), 1)

    # "</" inside a JSON string would close the <script> tag early.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload, 1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    # Home-screen icon and app name for "Add to Home Screen".
    shutil.copytree(ROOT / "icons", out.parent / "icons", dirs_exist_ok=True)
    manifest = {
        "name": "Jeuksou 著數碼", "short_name": "Jeuksou", "start_url": "./", "scope": "./",
        "display": "standalone", "background_color": "#0a0a0c", "theme_color": "#0a0a0c",
        "icons": [{"src": f"icons/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any maskable"} for n in (192, 512)],
    }
    (out.parent / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    live = sum(d["status"] not in ("expired", "avoid") for d in data["deals"])
    print(f"Built {out} ({len(data['deals'])} deals, {live} not expired, {len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
