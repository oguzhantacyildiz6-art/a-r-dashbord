# -*- coding: utf-8 -*-
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
TZ = timezone(timedelta(hours=3))
UA = "Mozilla/5.0 TEM-BULTEN/1.0"

KEYWORDS = (
    "pkk", "pyd", "pjak", "ypg", "kck", "hpg", "ocalan",
    "imrali", "qandil", "kandil", "rojava",
)

ORG_SOURCES = {"ANF", "Hawar News", "Serxwebun", "Rudaw"}
OTHER_SOURCES = {"BBC", "DW", "Sabah", "NTV", "Haberturk", "Sozcu", "Euronews", "CNN", "Reuters"}
CITY_SOURCES = {"Agrihaber", "Kent04", "Agribasin"}

HOST_NAME = {
    "bbc.com": "BBC", "bbc.co.uk": "BBC",
    "dw.com": "DW",
    "sabah.com.tr": "Sabah",
    "ntv.com.tr": "NTV",
    "haberturk.com": "Haberturk",
    "sozcu.com.tr": "Sozcu",
    "euronews.com": "Euronews",
    "cnn.com": "CNN", "cnnturk.com": "CNN",
    "reuters.com": "Reuters",
    "rudaw.net": "Rudaw",
    "anf-news.com": "ANF", "anfenglish.com": "ANF",
    "hawarnews.com": "Hawar News",
    "serxwebun.org": "Serxwebun",
    "kent04.com": "Kent04",
    "agribasin.com": "Agribasin",
    "agrihaber.com": "Agrihaber",
    "agrihabertv.com": "Agrihaber",
    "agrihabergazetesi.net": "Agrihaber",
}

X_ACCOUNTS = [
    ("@DEMGenelMerkezi", "DEMGenelMerkezi"),
    ("@agribelediye", "agribelediye"),
    ("@HazalAras04", "HazalAras04"),
    ("@agr_hdp", "agr_hdp"),
]
NITTER = ["https://xcancel.com", "https://nitter.poast.org", "https://nitter.privacyredirect.com"]


def now_tr():
    return datetime.now(TZ)


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_scan": None, "social": [], "news_org": [], "news_other": [], "news_city": []}


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
    text = re.sub(r"<[^>]+", " ", text or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fold(text):
    t = (text or "").lower()
    return t.replace("\u00f6", "o").replace("\u0131", "i").replace("\u00fc", "u").replace("\u00e7", "c").replace("\u015f", "s").replace("\u011f", "g")


def relevant(text):
    t = fold(text)
    return any(k in t for k in KEYWORDS)


def parse_dt(raw, url=""):
    raw = (raw or "").strip()
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            return dt.astimezone(TZ)
        except Exception:
            pass
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(raw[:19].replace("Z", ""), fmt.replace("%z", ""))
                return dt.replace(tzinfo=TZ)
            except Exception:
                continue
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", raw)
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ)
    m = re.search(r"/(20\d{2})/(\d{1,2})/(\d{1,2})/", url or "")
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ)
    return None


def fmt_date(dt):
    if not dt:
        return ""
    return dt.strftime("%d.%m.%Y")


def in_window(dt, days, allow_missing):
    if dt is None:
        return allow_missing
    return (now_tr() - dt) <= timedelta(days=days)


def unwrap(url):
    if url and "news.google.com" in url:
        qs = parse_qs(urlparse(url).query)
        if "url" in qs:
            return qs["url"][0]
    return url or ""


def name_from_url(url, fallback=""):
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    for key, name in HOST_NAME.items():
        if key in host:
            return name
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
        title = link = desc = pub = ""
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
                pub = strip_tags(c.text or "")[:80]
        if title and link:
            items.append({"title": title, "url": unwrap(link), "summary": desc or title, "pub": pub})
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
        items.append({"title": inner, "url": url, "summary": inner, "pub": ""})
    times = re.findall(r"datetime=[\"']([^\"']+)[\"']", html or "")
    seen, out = set(), []
    for i, it in enumerate(items):
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        if i < len(times):
            it["pub"] = times[i]
        out.append(it)
        if len(out) >= 50:
            break
    return out


def add_item(out, name, row, group):
    url = unwrap(row.get("url") or "")
    title = row.get("title") or ""
    source = name_from_url(url, name) or name
    if "news.google.com" in url:
        return
    dt = parse_dt(row.get("pub") or "", url)
    blob = title + " " + (row.get("summary") or "")
    if group in ("org", "other") and not relevant(blob):
        return
    if group == "org" and source not in ORG_SOURCES:
        return
    if group == "other" and source not in OTHER_SOURCES:
        return
    if group == "city" and source not in CITY_SOURCES:
        return
    days = {"org": 30, "other": 15, "city": 7}[group]
    if not in_window(dt, days, allow_missing=(group == "city")):
        return
    out.append({
        "section": group,
        "group": group,
        "source": source,
        "title": title[:160],
        "summary": (row.get("summary") or title)[:280],
        "url": url,
        "date": fmt_date(dt) or "",
        "badge": source,
    })


def scan_news():
    jobs = [
        ("org", "ANF", "https://anf-news.com/latest-news", False),
        ("org", "ANF", "https://anf-news.com/rss", True),
        ("org", "Hawar News", "https://hawarnews.com/en/news", False),
        ("org", "Hawar News", "https://hawarnews.com/en/rss/latest-posts", True),
        ("org", "Serxwebun", "https://serxwebun.org/", False),
        ("org", "Rudaw", "https://www.rudaw.net/turkish", False),
        ("other", "BBC", "https://feeds.bbci.co.uk/turkce/rss.xml", True),
        ("other", "DW", "https://rss.dw.com/rdf/rss-tur-all", True),
        ("other", "Sabah", "https://www.sabah.com.tr/rss/gundem.xml", True),
        ("other", "NTV", "https://www.ntv.com.tr/gundem.rss", True),
        ("other", "Haberturk", "https://www.haberturk.com/rss", True),
        ("other", "Sozcu", "https://www.sozcu.com.tr/feeds-rss-category-gundem", True),
        ("other", "Euronews", "https://tr.euronews.com/rss", True),
        ("other", "CNN", "https://www.cnnturk.com/feed/rss/all/news", True),
        ("other", "Reuters", "https://www.reuters.com/world/rss", True),
        ("other", "BBC", "https://news.google.com/rss/search?q=PKK+OR+PYD+(site:bbc.com+OR+site:dw.com+OR+site:euronews.com+OR+site:cnn.com+OR+site:cnnturk.com+OR+site:reuters.com+OR+site:sabah.com.tr+OR+site:ntv.com.tr+OR+site:haberturk.com+OR+site:sozcu.com.tr)&hl=tr&gl=TR&ceid=TR:tr", True),
        ("city", "Kent04", "https://www.kent04.com/", False),
        ("city", "Agribasin", "https://www.agribasin.com/", False),
        ("city", "Agrihaber", "https://www.agrihabertv.com/", False),
        ("city", "Agrihaber", "https://www.agrihaber.com/", False),
    ]
    out = []
    for group, name, url, is_rss in jobs:
        try:
            raw = fetch(url)
            rows = parse_rss(raw) if is_rss else scrape_links(raw.decode("utf-8", "ignore"), url)
            for row in rows:
                add_item(out, name, row, group)
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
                    dt = parse_dt(row.get("pub") or "", row.get("url") or "")
                    out.append({
                        "section": "social", "source": label,
                        "title": row["title"][:160],
                        "summary": (row.get("summary") or row["title"])[:280],
                        "url": f"https://x.com/{handle}",
                        "date": fmt_date(dt),
                        "badge": "X",
                    })
                got = True
                break
            except Exception:
                continue
        if not got:
            out.append({
                "section": "social", "source": label,
                "title": f"{label} hesabi izleniyor",
                "summary": "X resmi API ucretsiz degil.",
                "url": f"https://x.com/{handle}",
                "date": "",
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
    data["news_other"] = [x for x in news if x.get("group") == "other"][:50]
    data["news_city"] = [x for x in news if x.get("group") == "city"][:40]
    data["news"] = news[:80]
    if social:
        data["social"] = social[:40]
    save_data(data)
    return data
