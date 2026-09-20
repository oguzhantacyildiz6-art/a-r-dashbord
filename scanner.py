# -*- coding: utf-8 -*-
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
TZ = timezone(timedelta(hours=3))
UA = "Mozilla/5.0 TEM-BULTEN/1.0"

KEYWORDS = (
    "pkk", "pyd", "pjak", "ypg", "kck", "hpg", "ocalan",
    "imrali", "qandil", "kandil", "rojava", "teror orgutu",
)

ORG_SOURCES = {"ANF", "Hawar News", "Serxwebun", "Rudaw"}
ALLOWED_OTHER = {"BBC", "DW", "Sabah", "NTV", "Haberturk", "Sozcu"}

HOST_NAME = {
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "dw.com": "DW",
    "sabah.com.tr": "Sabah",
    "ntv.com.tr": "NTV",
    "haberturk.com": "Haberturk",
    "sozcu.com.tr": "Sozcu",
    "rudaw.net": "Rudaw",
    "anf-news.com": "ANF",
    "anfenglish.com": "ANF",
    "hawarnews.com": "Hawar News",
    "serxwebun.org": "Serxwebun",
}

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


def fold(text):
    t = (text or "").lower()
    return (
        t.replace("\u00f6", "o").replace("\u00d6", "o")
        .replace("\u0131", "i").replace("\u0130", "i")
        .replace("\u00fc", "u").replace("\u00e7", "c")
        .replace("\u015f", "s").replace("\u011f", "g")
    )


def relevant(text):
    t = fold(text)
    return any(k in t for k in KEYWORDS)


def unwrap(url):
    if not url:
        return url
    if "news.google.com" in url:
        qs = parse_qs(urlparse(url).query)
        if "url" in qs:
            return qs["url"][0]
    return url


def name_from_url(url, fallback=""):
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    for key, name in HOST_NAME.items():
        if key in host:
            return name
    return fallback


def source_from_title(title, fallback):
    parts = re.split(r"\s[-\u2013|]\s", title or "")
    if len(parts) >= 2:
        tail = parts[-1].strip()
        mapping = {
            "sabah": "Sabah", "ntv": "NTV", "haberturk": "Haberturk",
            "habertürk": "Haberturk", "sozcu": "Sozcu", "sözcü": "Sozcu",
            "bbc": "BBC", "dw": "DW", "deutsche welle": "DW",
        }
        key = fold(tail)
        for k, v in mapping.items():
            if k in key:
                return v
    return fallback


def parse_rss(xml_bytes):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return items
    for it in root.iter():
        tag = it.tag.split("}")[-1].lower()
        if tag not in ("item", "entry"):
            continue
        title = link = desc = pub = src = ""
        for c in list(it):
            ctag = c.tag.split("}")[-1].lower()
            if ctag == "title":
                title = strip_tags(c.text or "")
            elif ctag == "link":
                link = (c.text or c.attrib.get("href") or "").strip()
            elif ctag in ("description", "summary", "content"):
                desc = strip_tags(c.text or "")[:280]
                hrefs = re.findall(r"href=[\"']([^\"']+)[\"']", c.text or "")
                if hrefs and (not link or "news.google.com" in link):
                    link = hrefs[0]
            elif ctag in ("pubdate", "published", "updated", "date"):
                pub = strip_tags(c.text or "")[:40]
            elif ctag == "source":
                src = strip_tags(c.text or "")
        if title and link:
            items.append({"title": title, "url": unwrap(link), "summary": desc or title, "date": pub, "src": src})
    return items


def scrape_links(html, base):
    items = []
    for m in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href, inner = m.group(1), strip_tags(m.group(2))
        if len(inner) < 22 or len(inner) > 200:
            continue
        if href.startswith("#") or "javascript:" in href:
            continue
        url = urljoin(base, href)
        if not url.startswith("http"):
            continue
        items.append({"title": inner, "url": url, "summary": inner, "date": "", "src": ""})
    seen, out = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
        if len(out) >= 50:
            break
    return out


def add_item(out, name, row):
    url = unwrap(row.get("url") or "")
    title = row.get("title") or ""
    source = name_from_url(url, "") or source_from_title(title, name) or name
    if source == name and row.get("src"):
        source = source_from_title(row["src"], source)
    blob = title + " " + (row.get("summary") or "") + " " + source
    if not relevant(blob):
        return
    if "news.google.com" in url:
        return
    group = "org" if source in ORG_SOURCES else "other"
    if group == "other" and source not in ALLOWED_OTHER:
        return
    out.append({
        "section": "news",
        "group": group,
        "source": source,
        "title": re.sub(r"\s[-\u2013|]\s(Sabah|NTV|Haberturk|Sozcu|BBC|DW).*$", "", title, flags=re.I)[:160],
        "summary": (row.get("summary") or title)[:280],
        "url": url,
        "date": row.get("date") or now_tr().strftime("%d.%m %H:%M"),
        "badge": source,
    })


def scan_news():
    sources = [
        ("ANF", "https://anf-news.com/latest-news", False),
        ("ANF", "https://anf-news.com/rss", True),
        ("Hawar News", "https://hawarnews.com/en/news", False),
        ("Hawar News", "https://hawarnews.com/en/rss/latest-posts", True),
        ("Serxwebun", "https://serxwebun.org/", False),
        ("Rudaw", "https://www.rudaw.net/turkish", False),
        ("BBC", "https://feeds.bbci.co.uk/turkce/rss.xml", True),
        ("DW", "https://rss.dw.com/rdf/rss-tur-all", True),
        ("Sabah", "https://www.sabah.com.tr/rss/gundem.xml", True),
        ("Sabah", "https://www.sabah.com.tr/arama?query=PKK", False),
        ("NTV", "https://www.ntv.com.tr/gundem.rss", True),
        ("NTV", "https://www.ntv.com.tr/arama?q=PKK", False),
        ("Haberturk", "https://www.haberturk.com/rss", True),
        ("Haberturk", "https://www.haberturk.com/haberleri/pkk", False),
        ("Sozcu", "https://www.sozcu.com.tr/feeds-rss-category-gundem", True),
        ("Sozcu", "https://www.sozcu.com.tr/haberleri/pkk/", False),
        ("BBC", "https://news.google.com/rss/search?q=PKK+OR+PYD+site:bbc.com+OR+site:dw.com+OR+site:sabah.com.tr+OR+site:ntv.com.tr+OR+site:haberturk.com+OR+site:sozcu.com.tr&hl=tr&gl=TR&ceid=TR:tr", True),
    ]
    out = []
    for name, url, is_rss in sources:
        try:
            raw = fetch(url)
            rows = parse_rss(raw) if is_rss else scrape_links(raw.decode("utf-8", "ignore"), url)
            for row in rows:
                add_item(out, name, row)
        except Exception:
            continue
    return dedupe(out)


def scan_x():
    out = []
    for label, handle in X_ACCOUNTS:
        got = False
        for host in NITTER:
            try:
                rows = parse_rss(fetch(f"{host}/{handle}/rss"))
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
                "summary": "X resmi API ucretsiz degil.",
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
    data["news_org"] = [x for x in news if x.get("group") == "org"][:60]
    data["news_other"] = [x for x in news if x.get("group") != "org"][:50]
    data["news"] = news[:80]
    if social:
        data["social"] = social[:40]
    save_data(data)
    return data
