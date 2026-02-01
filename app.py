import os
import re
import sqlite3
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

import requests
from dateutil import parser as dtparser
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from bs4 import BeautifulSoup
from langdetect import detect
import argostranslate.translate as argos

import config

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "news.db")

TZ = ZoneInfo("Europe/Paris")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-change-me")

NEWSAPI_DAILY_LIMIT = int(os.getenv("NEWSAPI_DAILY_LIMIT", "100"))

NEWSAPI_REGISTER_URL = "https://newsapi.org/register"
FINNHUB_REGISTER_URL = "https://finnhub.io/register"


# -----------------------
# DB helpers
# -----------------------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            title TEXT,
            description TEXT,
            url TEXT UNIQUE,
            published_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_articles (
            snapshot_date TEXT,
            article_id INTEGER,
            sector TEXT,
            market TEXT,
            themes TEXT,
            score INTEGER,
            created_at TEXT,
            PRIMARY KEY (snapshot_date, article_id),
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS translations (
            url TEXT,
            mode TEXT,
            target_lang TEXT,
            translated TEXT,
            created_at TEXT,
            PRIMARY KEY (url, mode, target_lang)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,          -- "newsapi" or "finnhub"
            key TEXT,
            label TEXT,
            is_active INTEGER,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,          -- "newsapi"
            key_id INTEGER,
            key_tail TEXT,
            local_day TEXT,         -- YYYY-MM-DD Paris
            status_code INTEGER,
            created_at TEXT
        )
    """)

    con.commit()
    con.close()


# -----------------------
# Helpers
# -----------------------
def paris_today_str() -> str:
    return datetime.now(TZ).date().isoformat()


def _key_tail(k: str) -> str:
    k = (k or "").strip()
    return k[-4:] if len(k) >= 4 else k


def get_active_key_row(provider: str) -> Optional[sqlite3.Row]:
    con = db()
    row = con.execute("""
        SELECT * FROM api_keys
        WHERE provider = ? AND is_active = 1
        ORDER BY created_at DESC
        LIMIT 1
    """, (provider,)).fetchone()
    con.close()
    return row


def get_active_key(provider: str, fallback_env: str) -> str:
    row = get_active_key_row(provider)
    if row and row["key"]:
        return (row["key"] or "").strip()
    return (fallback_env or "").strip()


def set_active_key(provider: str, new_key: str, save_old: bool, label: str = "active", fallback_env: str = "") -> None:
    new_key = (new_key or "").strip()
    if not new_key:
        raise ValueError("Empty key")

    con = db()

    old_row = con.execute("""
        SELECT * FROM api_keys WHERE provider=? AND is_active=1
        ORDER BY created_at DESC LIMIT 1
    """, (provider,)).fetchone()

    old_key = ""
    if old_row and old_row["key"]:
        old_key = (old_row["key"] or "").strip()
    else:
        old_key = (fallback_env or "").strip()

    if save_old and old_key and old_key != new_key:
        con.execute("""
            INSERT INTO api_keys (provider, key, label, is_active, created_at)
            VALUES (?, ?, ?, 0, ?)
        """, (provider, old_key, f"old-{paris_today_str()}", datetime.now(timezone.utc).isoformat()))

    con.execute("UPDATE api_keys SET is_active=0 WHERE provider=?", (provider,))
    con.execute("""
        INSERT INTO api_keys (provider, key, label, is_active, created_at)
        VALUES (?, ?, ?, 1, ?)
    """, (provider, new_key, (label or "active").strip() or "active", datetime.now(timezone.utc).isoformat()))

    con.commit()
    con.close()


def list_keys(provider: str) -> List[sqlite3.Row]:
    con = db()
    rows = con.execute("""
        SELECT id, provider, label, key, is_active, created_at
        FROM api_keys
        WHERE provider = ?
        ORDER BY is_active DESC, created_at DESC
    """, (provider,)).fetchall()
    con.close()
    return rows


def activate_key_by_id(provider: str, key_id: int) -> None:
    con = db()
    row = con.execute("""
        SELECT id FROM api_keys
        WHERE provider=? AND id=?
    """, (provider, int(key_id))).fetchone()
    if not row:
        con.close()
        raise ValueError("Key not found")

    con.execute("UPDATE api_keys SET is_active=0 WHERE provider=?", (provider,))
    con.execute("UPDATE api_keys SET is_active=1 WHERE provider=? AND id=?", (provider, int(key_id)))
    con.commit()
    con.close()


def log_api_usage(provider: str, key_id: Optional[int], key_tail: str, status_code: int) -> None:
    con = db()
    con.execute("""
        INSERT INTO api_usage (provider, key_id, key_tail, local_day, status_code, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (provider, key_id, key_tail, paris_today_str(), int(status_code), datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()


def get_newsapi_usage_today() -> Dict[str, Any]:
    active_row = get_active_key_row("newsapi")
    active_key = get_active_key("newsapi", config.NEWSAPI_KEY)
    tail = _key_tail(active_key)

    con = db()
    if active_row:
        used = con.execute("""
            SELECT COUNT(*) AS n
            FROM api_usage
            WHERE provider='newsapi' AND local_day=? AND key_id=?
        """, (paris_today_str(), int(active_row["id"]))).fetchone()["n"]
        label = active_row["label"] or "active"
    else:
        used = con.execute("""
            SELECT COUNT(*) AS n
            FROM api_usage
            WHERE provider='newsapi' AND local_day=? AND key_tail=?
        """, (paris_today_str(), tail)).fetchone()["n"]
        label = "env"

    con.close()
    limit_ = int(NEWSAPI_DAILY_LIMIT)
    remaining = max(0, limit_ - int(used))
    return {"used": int(used), "limit": limit_, "remaining": int(remaining), "tail": tail, "label": label}


def verify_newsapi_key(key: str) -> Tuple[bool, str]:
    key = (key or "").strip()
    if not key:
        return False, "Empty key"
    url = "https://newsapi.org/v2/top-headlines"
    params = {"country": "us", "pageSize": 1, "apiKey": key}
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return True, "OK"
        try:
            j = r.json()
            msg = j.get("message") or str(j)
        except Exception:
            msg = r.text[:200]
        return False, f"HTTP {r.status_code}: {msg}"
    except Exception as e:
        return False, str(e)


def verify_finnhub_key(key: str) -> Tuple[bool, str]:
    key = (key or "").strip()
    if not key:
        return False, "Empty key"
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": "AAPL", "token": key}
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return True, "OK"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


# -----------------------
# DB insert helpers
# -----------------------
def upsert_article_return_id(a: Dict[str, Any]) -> Optional[int]:
    con = db()
    con.execute("""
        INSERT OR IGNORE INTO articles (source, title, description, url, published_at)
        VALUES (?, ?, ?, ?, ?)
    """, (a["source"], a["title"], a.get("description", ""), a["url"], a.get("published_at", "")))
    con.commit()
    row = con.execute("SELECT id FROM articles WHERE url = ?", (a["url"],)).fetchone()
    con.close()
    return int(row["id"]) if row else None


def upsert_daily(snapshot_date: str, article_id: int, meta: Dict[str, Any]) -> None:
    con = db()
    con.execute("""
        INSERT OR REPLACE INTO daily_articles
        (snapshot_date, article_id, sector, market, themes, score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        snapshot_date,
        article_id,
        meta.get("sector", "Non classé"),
        meta.get("market", "ALL"),
        meta.get("themes", ""),
        int(meta.get("score", 0)),
        datetime.now(timezone.utc).isoformat()
    ))
    con.commit()
    con.close()


# -----------------------
# Classification
# -----------------------
def norm(s: Optional[str]) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def detect_themes(text_lower: str) -> List[str]:
    hits: List[str] = []
    for theme, kws in config.THEMES.items():
        if any(kw.lower() in text_lower for kw in kws):
            hits.append(theme)
    return hits


def pick_sector(text_lower: str) -> Tuple[str, int]:
    best_sector = "Non classé"
    best_score = 0
    for sector, rules in config.GICS.items():
        sc = 0
        for kw in rules["keywords"]:
            if kw.lower() in text_lower:
                sc += 2
        if sc > best_score:
            best_score = sc
            best_sector = sector
    return best_sector, best_score


def detect_market_from_text(text_lower: str) -> str:
    for tk in config.WATCHLIST:
        if tk.lower() in text_lower:
            return config.infer_market_from_symbol(tk)

    eu_markers = [
        ".pa", ".de", ".mi", ".as", ".mc", ".sw", ".st", ".ls", ".br", ".ol", ".co", ".he", ".vi", ".ir",
        "eurozone", "zone euro", "ecb", "bce", "euro", "eur",
        "cac 40", "dax", "ftse", "stoxx", "euro stoxx",
        "paris", "frankfurt", "milan", "madrid", "amsterdam", "london",
        "european union", "eu commission", "brussels", "bruxelles"
    ]
    if any(m in text_lower for m in eu_markers):
        return "EU"

    us_markers = ["fed", "fomc", "u.s.", "treasury", "nasdaq", "s&p", "dow jones", "wall street", "nyse"]
    if any(m in text_lower for m in us_markers):
        return "US"

    return "ALL"


def score_article(text_lower: str, sector_kw_score: int, themes: List[str]) -> int:
    score = 0
    for tk in config.WATCHLIST:
        if tk.lower() in text_lower:
            score += 6
    score += sector_kw_score
    if themes:
        score += 2
    impact_words = [
        "profit warning", "guidance", "downgrade", "upgrade",
        "rate hike", "rate cut", "merger", "acquisition",
        "antitrust", "sanctions", "results", "earnings"
    ]
    for w in impact_words:
        if w in text_lower:
            score += 2
    return score


def classify(title: str, desc: str) -> Dict[str, Any]:
    text = f"{title or ''} {desc or ''}"
    tl = text.lower()
    sector, sector_kw_score = pick_sector(tl)
    themes = detect_themes(tl)
    market = detect_market_from_text(tl)
    score = score_article(tl, sector_kw_score, themes)
    return {"sector": sector, "themes": ",".join(themes), "market": market, "score": score}


# -----------------------
# Time helpers
# -----------------------
def paris_day_bounds_utc(day_str: str) -> Tuple[datetime, datetime]:
    d = dtparser.parse(day_str).date()
    start_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TZ)
    end_local = datetime.now(TZ)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def parse_dt_maybe(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = dtparser.parse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def get_last_published_utc_for_day(day_str: str) -> Optional[datetime]:
    con = db()
    row = con.execute("""
        SELECT MAX(a.published_at) AS max_pub
        FROM daily_articles d
        JOIN articles a ON a.id = d.article_id
        WHERE d.snapshot_date = ?
    """, (day_str,)).fetchone()
    con.close()
    if not row or not row["max_pub"]:
        return None
    return parse_dt_maybe(row["max_pub"])


# -----------------------
# Fetchers
# -----------------------
def fetch_newsapi_range(from_utc: datetime, to_utc: datetime) -> List[Dict[str, Any]]:
    api_key = get_active_key("newsapi", config.NEWSAPI_KEY)
    if not api_key:
        return []

    active_row = get_active_key_row("newsapi")
    active_id = int(active_row["id"]) if active_row else None
    tail = _key_tail(api_key)

    url = "https://newsapi.org/v2/everything"
    q = "(bourse OR actions OR marchés OR market OR stocks OR earnings OR résultats OR inflation OR ECB OR Fed OR taux OR rates OR guidance OR merger OR acquisition)"

    def one_lang(lang: str) -> List[Dict[str, Any]]:
        params = {
            "q": q,
            "from": from_utc.isoformat().replace("+00:00", "Z"),
            "to": to_utc.isoformat().replace("+00:00", "Z"),
            "sortBy": "publishedAt",
            "pageSize": 100,
            "language": lang,
            "apiKey": api_key,
        }
        r = requests.get(url, params=params, timeout=25)
        log_api_usage("newsapi", active_id, tail, r.status_code)

        if r.status_code == 429:
            raise RuntimeError("NEWSAPI_429")

        r.raise_for_status()
        data = r.json()

        out: List[Dict[str, Any]] = []
        for a in data.get("articles", []):
            title = norm(a.get("title"))
            desc = norm(a.get("description"))
            if not a.get("url") or not title:
                continue
            out.append({
                "source": f"NewsAPI:{(a.get('source') or {}).get('name', '')}",
                "title": title,
                "description": desc,
                "url": a.get("url"),
                "published_at": a.get("publishedAt", ""),
            })
        return out

    return one_lang("fr") + one_lang("en")


def fetch_finnhub_market(from_utc: datetime, to_utc: datetime) -> List[Dict[str, Any]]:
    finnhub_key = get_active_key("finnhub", config.FINNHUB_KEY)
    if not finnhub_key:
        return []

    url = "https://finnhub.io/api/v1/news"
    params = {"category": "general", "token": finnhub_key}
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()

    items: List[Dict[str, Any]] = []
    for a in data[:250]:
        title = norm(a.get("headline"))
        desc = norm(a.get("summary"))
        if not a.get("url") or not title:
            continue
        try:
            pub_dt = datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc)
        except Exception:
            continue
        if pub_dt < from_utc or pub_dt > to_utc:
            continue

        items.append({
            "source": "Finnhub:market",
            "title": title,
            "description": desc,
            "url": a.get("url"),
            "published_at": pub_dt.isoformat(),
        })
    return items


# -----------------------
# Snapshot logic
# -----------------------
def refresh_snapshot(for_date: Optional[str] = None) -> int:
    snapshot_date = for_date or paris_today_str()
    start_utc, now_utc = paris_day_bounds_utc(snapshot_date)
    last_pub = get_last_published_utc_for_day(snapshot_date)

    from_utc = start_utc if last_pub is None else (last_pub - timedelta(minutes=5))
    to_utc = now_utc

    have_newsapi = bool(get_active_key("newsapi", config.NEWSAPI_KEY))
    have_finnhub = bool(get_active_key("finnhub", config.FINNHUB_KEY))

    if not have_newsapi and not have_finnhub:
        raise RuntimeError("MISSING_KEYS:newsapi,finnhub")

    items: List[Dict[str, Any]] = []
    if have_newsapi:
        items += fetch_newsapi_range(from_utc, to_utc)
    if have_finnhub:
        items += fetch_finnhub_market(from_utc, to_utc)

    new_count = 0
    for it in items:
        pub_dt = parse_dt_maybe(it.get("published_at", ""))
        if pub_dt is not None:
            if pub_dt < start_utc or pub_dt > to_utc:
                continue

        meta = classify(it["title"], it.get("description", ""))
        if meta["score"] < 2:
            continue

        article_id = upsert_article_return_id(it)
        if article_id:
            upsert_daily(snapshot_date, article_id, meta)
            new_count += 1

    return new_count


# -----------------------
# Translation (Argos)
# -----------------------
def get_translation_cached(url: str, mode: str, target_lang: str = "fr") -> Optional[str]:
    con = db()
    row = con.execute("""
        SELECT translated FROM translations
        WHERE url = ? AND mode = ? AND target_lang = ?
    """, (url, mode, target_lang)).fetchone()
    con.close()
    return row["translated"] if row else None


def set_translation_cached(url: str, mode: str, translated: str, target_lang: str = "fr") -> None:
    con = db()
    con.execute("""
        INSERT OR REPLACE INTO translations (url, mode, target_lang, translated, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (url, mode, target_lang, translated, datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def extract_article_text(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    if r.status_code in (401, 403):
        raise RuntimeError("Access denied (401/403). Paywall / anti-bot.")
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    meta_desc = soup.find("meta", attrs={"name": "description"})
    og_desc = soup.find("meta", attrs={"property": "og:description"})
    fallback_desc = ""
    if meta_desc and meta_desc.get("content"):
        fallback_desc = clean_text(meta_desc.get("content"))
    elif og_desc and og_desc.get("content"):
        fallback_desc = clean_text(og_desc.get("content"))

    candidates: List[str] = []
    for sel in ["article", "main", "body"]:
        node = soup.select_one(sel)
        if node:
            candidates.append(clean_text(node.get_text(" ")))

    for node in soup.find_all(["div", "section"], limit=250):
        txt = clean_text(node.get_text(" "))
        if len(txt) > 1200:
            candidates.append(txt)

    if not candidates:
        return fallback_desc

    text = max(candidates, key=len)
    if len(text) < 400 and fallback_desc:
        text = fallback_desc

    return text[:7000]


def translate_to_fr_argos(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    lang = "en"
    try:
        lang = detect(text)
    except Exception:
        lang = "en"

    if lang == "fr":
        return text

    if lang != "en":
        try:
            return argos.translate(text, lang, "fr")
        except Exception:
            raise RuntimeError(f"Detected: {lang}. Install pack {lang}->fr.")

    return argos.translate(text, "en", "fr")


# -----------------------
# Routes
# -----------------------
@app.route("/")
def index():
    day = request.args.get("day", paris_today_str())
    sector = request.args.get("sector", "Tout")
    q = (request.args.get("q") or "").strip().lower()
    min_score = int(request.args.get("min_score", "2"))
    sort = request.args.get("sort", "score")

    have_newsapi = bool(get_active_key("newsapi", config.NEWSAPI_KEY))
    have_finnhub = bool(get_active_key("finnhub", config.FINNHUB_KEY))

    newsapi_keys = list_keys("newsapi")
    finnhub_keys = list_keys("finnhub")

    con = db()
    days = con.execute("""
        SELECT snapshot_date, COUNT(*) as n
        FROM daily_articles
        GROUP BY snapshot_date
        ORDER BY snapshot_date DESC
        LIMIT 90
    """).fetchall()

    where = ["d.snapshot_date = ?", "d.score >= ?"]
    params: List[Any] = [day, min_score]

    if sector != "Tout":
        where.append("d.sector = ?")
        params.append(sector)

    if q:
        where.append("(lower(a.title) LIKE ? OR lower(a.description) LIKE ? OR lower(a.source) LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]

    where_sql = " AND ".join(where)
    order_sql = "a.published_at DESC, d.score DESC" if sort == "date" else "d.score DESC, a.published_at DESC"

    def fetch_rows(market_value: str, limit: int):
        return con.execute(f"""
            SELECT d.snapshot_date, d.sector, d.market, d.themes, d.score,
                   a.source, a.title, a.description, a.url, a.published_at
            FROM daily_articles d
            JOIN articles a ON a.id = d.article_id
            WHERE {where_sql} AND d.market = ?
            ORDER BY {order_sql}
            LIMIT ?
        """, params + [market_value, limit]).fetchall()

    rows_us = fetch_rows("US", 150)
    rows_eu = fetch_rows("EU", 150)
    rows_all = fetch_rows("ALL", 120)

    counts = con.execute(f"""
        SELECT d.market, COUNT(*) as n
        FROM daily_articles d
        JOIN articles a ON a.id = d.article_id
        WHERE {where_sql}
        GROUP BY d.market
    """, params).fetchall()
    counts_map = {r["market"]: r["n"] for r in counts}
    count_us = counts_map.get("US", 0)
    count_eu = counts_map.get("EU", 0)
    count_all = counts_map.get("ALL", 0)

    stats = con.execute("""
        SELECT d.sector, COUNT(*) as n
        FROM daily_articles d
        WHERE d.snapshot_date = ? AND d.score >= ?
        GROUP BY d.sector
        ORDER BY n DESC
    """, (day, min_score)).fetchall()

    con.close()

    # sectors list uses stable keys (GICS keys + special values)
    sectors = ["Tout"] + list(config.GICS.keys()) + ["Non classé"]

    # FR labels (UI)
    sector_labels = {k: v["label"] for k, v in config.GICS.items()}
    sector_labels["Tout"] = "Tous"
    sector_labels["Non classé"] = "Non classé"

    # EN labels (UI)
    sector_labels_en = {
        "Energy": "Energy",
        "Materials": "Materials",
        "Industrials": "Industrials",
        "Consumer Discretionary": "Consumer Discretionary",
        "Consumer Staples": "Consumer Staples",
        "Health Care": "Health Care",
        "Financials": "Financials",
        "Information Technology": "Technology",
        "Communication Services": "Communication",
        "Utilities": "Utilities",
        "Real Estate": "Real Estate",
        "Tout": "All",
        "Non classé": "Unclassified",
    }

    today = paris_today_str()
    yesterday = (datetime.now(TZ) - timedelta(days=1)).date().isoformat()

    newsapi_quota = get_newsapi_usage_today() if have_newsapi else None

    return render_template(
        "index.html",
        # base vars
        days=days,
        day=day,
        sectors=sectors,
        sector_labels=sector_labels,
        sector_labels_en=sector_labels_en,
        sector=sector,
        q=q,
        min_score=min_score,
        sort=sort,
        # stats + rows
        stats=stats,
        rows_us=rows_us,
        rows_eu=rows_eu,
        rows_all=rows_all,
        count_us=count_us,
        count_eu=count_eu,
        count_all=count_all,
        # dates
        today=today,
        yesterday=yesterday,
        # keys/quota
        have_newsapi=have_newsapi,
        have_finnhub=have_finnhub,
        newsapi_quota=newsapi_quota,
        newsapi_register_url=NEWSAPI_REGISTER_URL,
        finnhub_register_url=FINNHUB_REGISTER_URL,
        newsapi_keys=newsapi_keys,
        finnhub_keys=finnhub_keys,
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    day = request.form.get("day") or None
    snapshot_day = day or paris_today_str()

    try:
        new_count = refresh_snapshot(for_date=day)
        flash(f"Snapshot updated ✅ (+{new_count})", "success")
    except Exception as e:
        s = str(e)
        if "NEWSAPI_429" in s:
            q = get_newsapi_usage_today()
            flash(f"NewsAPI quota reached (429). Estimated: {q['used']}/{q['limit']}. Switch key if needed.", "danger")
        elif s.startswith("MISSING_KEYS:"):
            flash("Missing API keys (NewsAPI and Finnhub). Add at least one key.", "danger")
        else:
            flash(f"Refresh error: {e}", "danger")

    return redirect(url_for("index", day=snapshot_day))


@app.route("/refresh_json", methods=["POST"])
def refresh_json():
    day = request.form.get("day") or paris_today_str()

    have_newsapi = bool(get_active_key("newsapi", config.NEWSAPI_KEY))
    have_finnhub = bool(get_active_key("finnhub", config.FINNHUB_KEY))

    if not have_newsapi and not have_finnhub:
        return jsonify({
            "ok": False,
            "missing": True,
            "missing_newsapi": True,
            "missing_finnhub": True,
            "error": "Missing API keys (NewsAPI and Finnhub)."
        }), 400

    try:
        new_count = refresh_snapshot(for_date=day)
        return jsonify({"ok": True, "new": new_count})
    except Exception as e:
        s = str(e)
        if "NEWSAPI_429" in s:
            q = get_newsapi_usage_today()
            return jsonify({
                "ok": False,
                "quota": True,
                "error": "NewsAPI quota reached (429).",
                "used": q["used"],
                "limit": q["limit"],
                "remaining": q["remaining"],
                "tail": q["tail"],
                "label": q["label"]
            }), 429
        if s.startswith("MISSING_KEYS:"):
            return jsonify({
                "ok": False,
                "missing": True,
                "missing_newsapi": not have_newsapi,
                "missing_finnhub": not have_finnhub,
                "error": "Missing key. Add NewsAPI and/or Finnhub."
            }), 400
        return jsonify({"ok": False, "error": s}), 500


@app.route("/set_api_key", methods=["POST"])
def set_api_key_route():
    provider = (request.form.get("provider") or "").strip().lower()
    new_key = (request.form.get("new_key") or "").strip()
    save_old = (request.form.get("save_old") == "on")
    do_test = (request.form.get("do_test") == "on")
    label = (request.form.get("label") or "active").strip() or "active"

    if provider not in ("newsapi", "finnhub"):
        flash("Invalid provider.", "danger")
        return redirect(url_for("index"))

    if not new_key:
        flash("Empty key.", "danger")
        return redirect(url_for("index"))

    if do_test:
        if provider == "newsapi":
            ok, msg = verify_newsapi_key(new_key)
        else:
            ok, msg = verify_finnhub_key(new_key)
        if not ok:
            flash(f"Key rejected ({provider}): {msg}", "danger")
            return redirect(url_for("index"))
        flash(f"Key tested ✅ ({provider})", "success")

    try:
        fallback = config.NEWSAPI_KEY if provider == "newsapi" else config.FINNHUB_KEY
        set_active_key(provider, new_key, save_old=save_old, label=label, fallback_env=fallback)
        flash(f"Key saved ✅ ({provider})", "success")
    except Exception as e:
        flash(f"Key save error: {e}", "danger")

    return redirect(url_for("index"))


@app.route("/activate_key", methods=["POST"])
def activate_key_route():
    provider = (request.form.get("provider") or "").strip().lower()
    key_id = request.form.get("key_id")

    if provider not in ("newsapi", "finnhub"):
        flash("Invalid provider.", "danger")
        return redirect(url_for("index"))

    if not key_id or not str(key_id).isdigit():
        flash("Invalid key id.", "danger")
        return redirect(url_for("index"))

    try:
        activate_key_by_id(provider, int(key_id))
        flash(f"Key activated ✅ ({provider})", "success")
    except Exception as e:
        flash(f"Key switch error: {e}", "danger")

    return redirect(url_for("index"))


@app.route("/translate", methods=["POST"])
def translate():
    payload = request.get_json(force=True)
    mode = (payload.get("mode") or "summary").strip().lower()
    url = (payload.get("url") or "").strip()
    title = (payload.get("title") or "").strip()
    desc = (payload.get("description") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "Missing URL"}), 400
    if mode not in ("summary", "full"):
        return jsonify({"ok": False, "error": "Invalid mode"}), 400

    cached = get_translation_cached(url, mode, "fr")
    if cached:
        return jsonify({"ok": True, "translated": cached, "cached": True})

    try:
        if mode == "summary":
            text = (title + "\n\n" + desc).strip() or (title or desc)
        else:
            text = extract_article_text(url)
            if not text:
                return jsonify({"ok": False, "error": "Cannot extract full content (empty)."}), 400

        translated = translate_to_fr_argos(text)
        if not translated:
            return jsonify({"ok": False, "error": "Empty translation."}), 500

        set_translation_cached(url, mode, translated, "fr")
        return jsonify({"ok": True, "translated": translated, "cached": False})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/clear", methods=["POST"])
def clear():
    con = db()
    con.execute("DELETE FROM daily_articles")
    con.execute("DELETE FROM articles")
    con.execute("DELETE FROM translations")
    con.execute("DELETE FROM api_usage")
    con.execute("DELETE FROM api_keys")
    con.commit()
    con.close()
    flash("Database cleared.", "warning")
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)