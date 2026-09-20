# -*- coding: utf-8 -*-
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin
from urllib.request import Request, urlopen

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
TZ = timezone(timedelta(hours=3))
UA = "Mozilla/5.0 TEM-BULTEN/1.0"

KEYWORDS = (
    "pkk", "pyd", "pjak", "kck", "ypg", "sdf", "ocalan", "imrali",
    "dem parti", "rojava", "qandil",
)

ORG_SOURCES = {"ANF", "Hawar News", "Serxwebun"}

X_ACCOUNTS = [
    ("@DEMGenelMerkezi", "DEMGenelMerkezi"),
    ("@agribelediye", "agribelediye"),
    ("@HazalAras04", "HazalAras04"),
    ("@agr_hdp", "agr_hdp"),
]

NITTER = [
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
]


def now_tr():
    return datetime.now(TZ)


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_scan": None, "social": [], "news_org": [], "news_other": []}


def save_data(data):
    data["last_scan"] = now_tr().strftime("%d.%m.%Y %H:%M")
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def fetch(url, timeout=18):
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def relevant(text):
    t = (text or "").lower().replace("\u00f6", "o").replace("\u0131", "i")
    return any(k in t for k in KEYWORDS)


def parse_rss(xml_bytes):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return items
    for it in root.iter():
        if it.tag.split("}")[-1].lower() != "item":
            continue
        title = link = desc = pub = ""
        for c in list(it):
            tag = c.tag.split("}")[-1].lower()
            if tag == "title":
                title = strip_tags(c.text or "")
            elif tag == "link":
                link = (c.text or "").strip()
            elif tag in ("description", "summary"):
                desc = strip_tags(c.text or "")[:280]
            elif tag in ("pubdate", "published", "date"):
                pub = strip_tags(c.text or "")[:40]
        if title and link:
            items.append({"title": title, "url": link, "summary": desc or title, "date": pub})
    return items


def scrape_links(html, base):
    items = []
    for m in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href, inner = m.group(1), strip_tags(m.group(2))
        if len(inner) < 28 or len(inner) > 180:
            continue
        if href.startswith("#") or "javascript:" in href:
            continue
        url = urljoin(base, href)
        items.append({"title": inner, "url": url, "summary": inner, "date": ""})
    seen, out = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
        if len(out) >= 20:
            break
    return out


def scan_news():
    sources = [
        ("ANF", "https://anf-news.com/rss", True),
        ("ANF", "https://anf-news.com/latest-news", False),
        ("Hawar News", "https://hawarnews.com/en/rss/latest-posts", True),
        ("Hawar News", "https://hawarnews.com/en/news", False),
        ("Serxwebun", "https://serxwebun.org/", False),
        ("Google Haber", "https://news.google.com/rss/search?q=PKK+OR+PYD+OR+PJAK+OR+Ocalan&hl=tr&gl=TR&ceid=TR:tr", True),
        ("DW Turkce", "https://rss.dw.com/rdf/rss-tur-all", True),
        ("BBC Turkce", "https://feeds.bbci.co.uk/turkce/rss.xml", True),
        ("TRT Haber", "https://www.trthaber.com/arama.html?q=PKK", False),
    ]
    out = []
    for name, url, is_rss in sources:
        try:
            raw = fetch(url)
            rows = parse_rss(raw) if is_rss else scrape_links(raw.decode("utf-8", "ignore"), url)
            for row in rows:
                blob = row["title"] + " " + row.get("summary", "")
                if name in ("DW Turkce", "BBC Turkce", "Google Haber", "TRT Haber") and not relevant(blob):
                    continue
                group = "org" if name in ORG_SOURCES else "other"
                out.append({
                    "section": "news",
                    "group": group,
                    "source": name,
                    "title": row["title"][:160],
                    "summary": (row.get("summary") or row["title"])[:280],
                    "url": row["url"],
                    "date": row.get("date") or now_tr().strftime("%d.%m %H:%M"),
                    "badge": "Orgut" if group == "org" else "Medya",
                })
        except Exception:
            continue
    return dedupe(out)


def scan_x():
    out = []
    for label, handle in X_ACCOUNTS:
        got = False
        for host in NITTER:
            rss = f"{host}/{handle}/rss"
            try:
                rows = parse_rss(fetch(rss))
                for row in rows[:6]:
                    out.append({
                        "section": "social",
                        "source": label,
                        "title": row["title"][:160],
                        "summary": (row.get("summary") or row["title"])[:280],
                        "url": f"https://x.com/{handle}",
                        "date": row.get("date") or now_tr().strftime("%d.%m %H:%M"),
                        "badge": "X",
                    })
                got = True
                break
            except Exception:
                continue
        if not got:
            out.append({
                "section": "social",
                "source": label,
                "title": f"{label} hesabi izleniyor",
                "summary": "X resmi API ucretsiz degil. Ayna kaynak yanit vermedi; haber siteleri taranmaya devam ediyor.",
                "url": f"https://x.com/{handle}",
                "date": now_tr().strftime("%d.%m %H:%M"),
                "badge": "Beklemede",
            })
    return dedupe(out)


def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = (it.get("source"), it.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def run_scan():
    data = load_data()
    news = scan_news()
    social = scan_x()
    if news:
        data["news_org"] = [x for x in news if x.get("group") == "org"][:50]
        data["news_other"] = [x for x in news if x.get("group") != "org"][:50]
        data["news"] = news[:80]
    if social:
        data["social"] = social[:40]
    save_data(data)
    return data
