#!/usr/bin/env python3
"""著數碼 scraper: reads the promo pages in sources.json, finds codes and dates,
and merges them into data/deals.json. No AI, no accounts, just HTTP + regex.

    python scraper.py            # scrape every page, update data/deals.json
    python scraper.py --dry-run  # show what it would add, change nothing
    python scraper.py --file page.html --site klook   # test the parser on a saved page

Rules it follows:
  * Codes you entered by hand (found: "manual") are never rewritten. Only their
    "lastSeen" date moves when the code shows up again on a page.
  * New codes come in as "unconfirmed" with found: "auto", because nobody has
    tried them at checkout yet.
  * Any deal whose end date has passed becomes "expired".
  * An auto-found code that no page has shown for STALE_DAYS becomes "expired".
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "deals.json"
SOURCES = ROOT / "sources.json"
STALE_DAYS = 21
TODAY = dt.date.today()
BOT = "JeuksouBot"
# An honest name, so site owners can see who is reading and block it in robots.txt if they want.
UA = f"Mozilla/5.0 (compatible; {BOT}/1.0; promo code wallet, reads public pages every few days)"

# ---------- code detection ----------
# A code is 5-20 capital letters/digits (dashes allowed inside).
CODE_RE = re.compile(r"(?<![A-Za-z0-9$¥£€-])([A-Z0-9](?:[A-Z0-9-]{3,18})[A-Z0-9])(?![A-Za-z0-9-])")
# Words near a code that say "this is a promo code".
CODE_WORDS = re.compile(r"code|coupon|promo|voucher|claim|輸入|優惠碼|折扣碼|代碼|優惠代碼|促銷碼|序號|券|領取|複製", re.I)
# Capitalised words that look like codes but are not.
STOP = set("""
HKD USD EUR GBP RMB CNY JPY TWD MOP AUD SGD HTTPS HTTP HTML WWW COM APP IOS ANDROID FAQ
VISA MASTERCARD UNIONPAY AMEX HSBC CITI DBS BEA BOC SCB AEON PAYME ALIPAYHK ALIPAY OCTOPUS WECHAT
KLOOK AGODA EXPEDIA TRIP BOOKING HERTZ AVIS SIXT EUROPCAR IHERB HKTVMALL TAOBAO ZALORA DYSON CROCS
WATSONS AIRALO TRAINLINE KEETA FOODPANDA PANDAMART PANDAPRO OPODO EDREAMS KIWI SKYSCANNER RENTALCARS
GENIUS PRIME PREMIER CHEERS ESIM VIP SALE FLASH FREE NEW OFF GET SHOP DEAL DEALS BEST UPDATE UPDATED
COPY CODE CODES PROMO COUPON VOUCHER TERMS EXPIRES EXPIRED VERIFIED MONDAY TUESDAY WEDNESDAY THURSDAY
FRIDAY SATURDAY SUNDAY JANUARY FEBRUARY MARCH APRIL JUNE JULY AUGUST SEPTEMBER OCTOBER NOVEMBER DECEMBER
COVID19 ISO9001 MP4 JPEG PNG WEBP UTF8 HK01 4K 5G 3D BLACK FRIDAY CYBER DOUBLE SINGLES 88VIP CASHBACK
""".split())


UNIT_RE = re.compile(r"(HKD|USD|NTD|TWD|RMB|CNY|JPY|KRW|SGD|MYR|THB|EUR|GBP|AUD|MOP)\d[\d,]*|\d+(MB|GB|TB|KM|KG|ML|MM|CM|HZ|MAH|W|K|P|G)")
# All-letter words (HALLOWEEN, CASHBACK) only count when the page labels them, e.g. "code: X" or "優惠碼【X】".
LABEL_BEFORE = re.compile(r"(code|coupon|promo|voucher|碼|代碼)\W{0,4}$", re.I)
# Text about insurance or other side offers that blogs place next to their articles.
OFF_TOPIC = re.compile(r"投保|保費|保險|保障|insur|policy holder|卓健|信用卡申請|開戶", re.I)


def looks_like_code(tok):
    if tok in STOP or tok.replace("-", "") in STOP:
        return False
    if UNIT_RE.fullmatch(tok):
        return False
    core = tok.replace("-", "")
    if core.isdigit():                       # phone numbers, prices, years
        return False
    if re.fullmatch(r"(19|20)\d\d\w*", core) and len(core) <= 6:
        return False
    letters = sum(c.isalpha() for c in core)
    digits = sum(c.isdigit() for c in core)
    if letters and digits:
        return True
    return letters >= 6                      # all-letter codes like WELCOMEHK


# ---------- dates ----------
MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
DATE_PATTERNS = [
    (re.compile(r"(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})"), lambda m: (m[1], m[2], m[3])),
    (re.compile(r"(20\d\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"), lambda m: (m[1], m[2], m[3])),
    (re.compile(r"(\d{1,2})/(\d{1,2})/(20\d\d)"), lambda m: (m[3], m[2], m[1])),         # HK style DD/MM/YYYY
    (re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(20\d\d)"), lambda m: (m[3], m[2], m[1])),
    (re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)"), lambda m: (m[3], m[1], m[2])),
    (re.compile(r"(?<![\d年])(\d{1,2})\s*月\s*(\d{1,2})\s*日"), lambda m: (None, m[1], m[2])),  # 10月31日, no year
]
END_WORDS = re.compile(r"until|till|expir|ends?|valid|before|deadline|to\b|至|截止|到期|有效|為止|前", re.I)


def to_date(y, mo, d):
    try:
        if not str(mo).isdigit():
            mo = MONTHS.get(str(mo)[:3].lower())
            if not mo:
                return None
        mo, d = int(mo), int(d)
        if y is None:                         # no year: pick the nearest future-ish one
            y = TODAY.year
            cand = dt.date(y, mo, d)
            if (TODAY - cand).days > 60:
                cand = dt.date(y + 1, mo, d)
            return cand
        return dt.date(int(y), mo, d)
    except (ValueError, TypeError):
        return None


def find_dates(text):
    """Return [(date, is_end_date)] found in text."""
    out, taken = [], []
    for rx, parts in DATE_PATTERNS:
        for m in rx.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            d = to_date(*parts(m))
            if not d or not (TODAY - dt.timedelta(days=400) <= d <= TODAY + dt.timedelta(days=900)):
                continue
            taken.append((m.start(), m.end()))
            if re.match(r"\s*(\d{1,2}:\d\d)?\s*(開搶|開賣|開始|起|starts?)", text[m.end():m.end() + 12], re.I):
                continue                          # when a sale opens, not when it ends
            before = text[max(0, m.start() - 25):m.start()]
            after = text[m.end():m.end() + 4]
            out.append((d, bool(END_WORDS.search(before) or re.match(r"\s*(前|為止|止)", after))))
    return out


def pick_expiry(text):
    dates = find_dates(text)
    if not dates:
        return None
    ends = [d for d, e in dates if e]
    return max(ends or [d for d, _ in dates])


# ---------- discount ----------
MONEY = r"(?:HK\$|HKD|US\$|USD|NT\$|NTD|RMB|S\$|A\$|\$|¥|£|€)\s?\d[\d,]*(?:\.\d+)?"
BIG_RE = [
    re.compile(r"(\d{1,2}(?:\.\d)?\s?%)"),
    re.compile(r"(\d{1,2}(?:\.\d)?\s?折)"),
    re.compile(r"(?:減|off\s)\s*(" + MONEY + ")", re.I),
    re.compile(r"(" + MONEY + r")\s*off", re.I),
    # Any amount that isn't a minimum spend ("滿 HK$500", "over $500", "min. $500").
    re.compile(r"(?<!滿)(?<!滿 )(?<!over )(?<!min\. )(?<!minimum )(" + MONEY + ")", re.I),
]


def pick_big(text):
    for rx in BIG_RE:
        m = rx.search(text)
        if m:
            v = re.sub(r"\s+", "", m.group(1))
            return v.replace("HKD", "HK$").replace("USD", "US$").replace("NTD", "NT$")
    return "New"


# ---------- page parsing ----------
def page_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe"]):
        t.decompose()
    junk = re.compile(r"sidebar|widget|related|popup|modal|banner|advert|\bads?\b|newsletter|subscribe|cookie|comment|share|recommend", re.I)
    for t in soup.find_all(True):
        if getattr(t, "decomposed", False) or t.attrs is None:   # inside something already removed
            continue
        attrs = " ".join([t.get("id") or ""] + (t.get("class") or []))
        if junk.search(attrs) and t.name not in ("html", "body", "main", "article"):
            t.decompose()
    # Codes hidden in copy-to-clipboard buttons or data attributes.
    attr_codes = set()
    for el in soup.find_all(True):
        for a in ("data-code", "data-clipboard-text", "data-coupon", "data-promo"):
            v = el.get(a)
            if v and CODE_RE.fullmatch(v.strip().upper()):
                attr_codes.add(v.strip().upper())
    strong = {t.get_text(strip=True).upper() for t in soup.find_all(["code", "strong", "b", "kbd", "mark"])}
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.split("\n")]
    return [l for l in lines if l], attr_codes, strong


def extract(html, page):
    """Return {code: {...}} for one page."""
    lines, attr_codes, strong = page_lines(html)
    multi = page.get("sites")
    found = {}
    current_site = page.get("site")
    seen_count = {}
    for l in lines:
        seen_count[l] = seen_count.get(l, 0) + 1

    def filler(l):
        """Lines that can't describe an offer: repeated boilerplate, bare dates/times, short fragments."""
        bare = CODE_RE.sub("", l).strip()
        return (seen_count.get(l, 0) >= 3 or len(bare) < 8
                or re.fullmatch(r"[\d年月日:/\-\s.]*(開搶|開賣|開始)?", bare) is not None)

    for i, line in enumerate(lines):
        if multi:                                 # track which shop this part of the page is about
            low = line.lower()
            for key, words in multi.items():
                if any(w.lower() in low for w in words):
                    current_site = key
                    break
        window = " ".join(lines[max(0, i - 1):i + 2])     # this line and its neighbours
        for m in CODE_RE.finditer(line):
            tok = m.group(1)
            if not looks_like_code(tok):
                continue
            sure = tok in attr_codes or tok in strong
            if not sure and not CODE_WORDS.search(window):
                continue
            if tok.replace("-", "").isalpha() and tok not in attr_codes and not LABEL_BEFORE.search(line[:m.start()]):
                continue
            if not current_site or tok in found:
                continue
            rest = line.replace(tok, "").strip()
            prev = lines[i - 1] if i else ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            # A short line ("CODE 領取", "CODE use code") is a table row: its description is on the line above.
            # Walk up past other code rows to find it.
            if len(rest) < 15 or seen_count.get(line, 0) >= 3:
                j = i - 1
                while j >= 0 and i - j < 15 and filler(lines[j]):
                    j -= 1
                context = lines[j] if j >= 0 else ""
            else:
                context = line
            if OFF_TOPIC.search(context + " " + line):
                continue
            big = pick_big(context.replace(tok, ""))
            if big == "New" and context is line:
                big = pick_big(nxt)
            found[tok] = {
                "site": current_site,
                "big": big,
                "expires": pick_expiry(context) or pick_expiry(line) or (pick_expiry(nxt) if context is line else None),
                "snippet": (context if context is not line else line)[:200],
            }
    for tok in attr_codes - set(found):           # attribute codes with no text around them
        if looks_like_code(tok) and current_site:
            found[tok] = {"site": page.get("site") or current_site, "big": "New", "expires": None, "snippet": ""}
    return found


_robots = {}


def allowed(url):
    """Follow each site's robots.txt. If it can't be read, assume reading is allowed."""
    host = urlparse(url)
    base = f"{host.scheme}://{host.netloc}"
    if base not in _robots:
        rp = RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch(BOT, url)


def fetch(url, tries=3):
    if not allowed(url):
        raise RuntimeError("blocked by robots.txt, skipped")
    last = None
    for n in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-HK,en;q=0.9,zh-HK;q=0.8"}, timeout=25)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 410):
                break
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(2 * (n + 1))
    raise RuntimeError(last)


# ---------- merge ----------
def merge(data, found_by_page):
    today = TODAY.isoformat()
    deals = data["deals"]
    known = {}
    for d in deals:
        for c in d.get("codes") or []:
            known[(d["site"], c)] = d
    added, seen = [], set()
    # The same code on pages about different shops is the blog's own promotion, not the shop's.
    shops_per_code = {}
    for page, found in found_by_page:
        for code, f in found.items():
            shops_per_code.setdefault(code, set()).add(f["site"])
    shared = {c for c, shops in shops_per_code.items() if len(shops) > 1}
    # Coupon hubs list other brands' codes on a shop's page. Skip a code whose text names another
    # brand and not this shop.
    names = {k: v["name"].lower().split(" /")[0].split(".")[0] for k, v in data["sites"].items()}
    others = set(names.values()) | {"kayak", "priceline", "cheapflights", "momondo", "hotwire", "orbitz", "travelocity", "farfetch", "tahiti"}

    def other_brand(site, text):
        low = text.lower()
        return names.get(site, "") not in low and any(o in low for o in others - {names.get(site, "")})

    groups = {}
    for page, found in found_by_page:
        host = urlparse(page["url"]).netloc.replace("www.", "")
        for code, f in found.items():
            site = f["site"]
            if site not in data["sites"] or code in shared or other_brand(site, f["snippet"]):
                continue
            key = (site, code)
            if key in known:
                d = known[key]
                d["lastSeen"] = today
                seen.add(id(d))
                if d.get("found") == "auto" and f["expires"] and not d.get("expires"):
                    d["expires"] = f["expires"].isoformat()
                continue
            exp = f["expires"].isoformat() if f["expires"] else None
            snippet = f["snippet"] or code
            gkey = (site, page["url"], snippet)
            if f["snippet"] and gkey in groups:          # same offer, another code (e.g. one per card)
                g = groups[gkey]
                g["codes"].append(code)
                known[key] = g
                continue
            d = {
                "site": site, "cat": page.get("cat", "Shopping"), "big": f["big"],
                "title": f"New code found on {host}", "title_zh": f"在 {host} 找到的新優惠碼",
                "codes": [code], "kind": "code",
                "desc": snippet, "desc_zh": snippet,
                "cond": f"Found automatically on {today}. Not tried at checkout yet, and the conditions may be in the source text.",
                "cond_zh": f"於 {today} 自動找到，尚未在結帳測試，使用條件請看來源原文。",
                "expires": exp, "status": "unconfirmed", "src": page["url"],
                "found": "auto", "firstSeen": today, "lastSeen": today,
            }
            if f["big"] == "New":
                d["big_zh"] = "新"
            deals.append(d)
            known[key] = d
            groups[gkey] = d
            added.append(d)
    # Expire by date, and retire auto codes nobody has listed for a while.
    expired = 0
    for d in deals:
        if d["status"] in ("expired", "avoid"):
            continue
        if d.get("expires") and d["expires"] < today:
            d["status"] = "expired"; expired += 1
        elif d.get("found") == "auto" and d.get("lastSeen") and \
                (TODAY - dt.date.fromisoformat(d["lastSeen"])).days > STALE_DAYS:
            d["status"] = "expired"
            d["cond"] = f"No source has listed this code since {d['lastSeen']}."
            d["cond_zh"] = f"自 {d['lastSeen']} 起再沒有來源列出這個優惠碼。"
            expired += 1
    return added, expired


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show changes, don't save")
    ap.add_argument("--file", help="parse a saved HTML file instead of fetching")
    ap.add_argument("--site", help="site key for --file")
    args = ap.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    pages = json.loads(SOURCES.read_text(encoding="utf-8"))["pages"]

    results, ok_sites, failed = [], set(), []
    if args.file:
        page = {"url": "file://" + args.file, "site": args.site, "cat": "Shopping"}
        found = extract(Path(args.file).read_text(encoding="utf-8", errors="replace"), page)
        results.append((page, found))
    else:
        for page in pages:
            try:
                html = fetch(page["url"])
            except RuntimeError as e:
                failed.append((page["url"], str(e)))
                print(f"  ✗ {page['url']}  ({e})")
                continue
            found = extract(html, page)
            results.append((page, found))
            ok_sites.update([page["site"]] if page.get("site") else page["sites"].keys())
            print(f"  ✓ {page['url']}  {len(found)} codes")
            time.sleep(1.5)                       # be polite

    added, expired = merge(data, results)
    for k in ok_sites:
        data["sites"][k]["checked"] = TODAY.isoformat()
    data["updated"] = TODAY.isoformat()

    print(f"\nNew codes: {len(added)}   Newly expired: {expired}   Pages failed: {len(failed)}/{len(pages) if not args.file else 1}")
    for d in added:
        print(f"  + {data['sites'][d['site']]['name']:<16} {d['codes'][0]:<18} {d['big']:<8} ends {d['expires'] or '?'}")
    if args.dry_run or args.file:
        print("\n(dry run, nothing saved)")
        return 0
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Saved {DATA.relative_to(ROOT)}")
    # Fail the run only if every page failed, so a scheduled job flags a real outage.
    return 1 if pages and len(failed) == len(pages) and not args.file else 0


if __name__ == "__main__":
    sys.exit(main())
