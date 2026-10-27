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
PHRASES = {"程式": "程序", "帐户": "账户", "结帐": "结账", "菲林相机": "胶片相机", "电邮": "电子邮件"}


def t2s(text):
    text = _hk2s(text)
    for a, b in PHRASES.items():
        text = text.replace(a, b)
    return text


def add_simplified(data):
    for d in data["deals"]:
        for f in ("title", "desc", "cond", "big"):
            if d.get(f + "_zh"):
                d[f + "_sc"] = t2s(d[f + "_zh"])
    for s in data["sites"].values():
        if s.get("note_zh"):
            s["note_sc"] = t2s(s["note_zh"])


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
    add_simplified(data)
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
