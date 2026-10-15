"""Lightweight public market-news feed used by the standalone AI-news service.

This module intentionally has no broker, pandas, yfinance, or trading-engine imports
so the AI-news container can use a much smaller dependency set than market-api.
"""
from __future__ import annotations

import email.utils
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

from .tinyfish_news import search_tinyfish, tinyfish_enabled

NEWS_RSS_FEEDS: list[tuple[str, str, str]] = [
    ("Moneycontrol Latest", "https://www.moneycontrol.com/rss/latestnews.xml", "Market"),
    ("Moneycontrol Business", "https://www.moneycontrol.com/rss/business.xml", "Corporate"),
    ("Moneycontrol Economy", "https://www.moneycontrol.com/rss/economy.xml", "Economy"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets", "Market"),
    ("Livemint Companies", "https://www.livemint.com/rss/companies", "Corporate"),
    ("News18 Markets", "https://www.news18.com/rss/markets.xml", "Market"),
    ("News18 Business", "https://www.news18.com/rss/business.xml", "Market"),
    ("Indian Express Business", "https://indianexpress.com/section/business/feed/", "Market"),
    ("Google · Markets", "https://news.google.com/rss/search?q=indian+stock+market&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · Sensex Nifty", "https://news.google.com/rss/search?q=sensex+nifty&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · FII DII", "https://news.google.com/rss/search?q=india+FII+DII+market&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · RBI Policy", "https://news.google.com/rss/search?q=RBI+monetary+policy+india&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · SEBI", "https://news.google.com/rss/search?q=SEBI+india&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · Earnings", "https://news.google.com/rss/search?q=indian+company+earnings+results&hl=en-IN&gl=IN&ceid=IN:en", "Earnings"),
    ("Google · Dividend Buyback", "https://news.google.com/rss/search?q=india+dividend+buyback&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · IPO", "https://news.google.com/rss/search?q=indian+IPO+listing&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Corporate Deals", "https://news.google.com/rss/search?q=indian+company+merger+acquisition+deal&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · IT Sector", "https://news.google.com/rss/search?q=indian+IT+sector+stocks&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Pharma", "https://news.google.com/rss/search?q=indian+pharma+stocks&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Auto Sales", "https://news.google.com/rss/search?q=india+auto+sales&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Bank NPA", "https://news.google.com/rss/search?q=indian+banks+NPA&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · GST Budget", "https://news.google.com/rss/search?q=india+GST+budget+economy&hl=en-IN&gl=IN&ceid=IN:en", "Economy"),
    ("Google · Infrastructure", "https://news.google.com/rss/search?q=india+infrastructure+ECONOMIC&hl=en-IN&gl=IN&ceid=IN:en", "Economy"),
    ("Google · Crude Oil", "https://news.google.com/rss/search?q=india+crude+oil+price&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Gold", "https://news.google.com/rss/search?q=india+gold+price&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Rupee Dollar", "https://news.google.com/rss/search?q=indian+rupee+dollar+forex&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
]

_BULLISH = ("beats", "surges", "rallies", "upgrade", "record profit", "order win", "buyback", "profit rises", "inflows")
_BEARISH = ("tumbles", "crashes", "plunges", "downgrade", "fraud", "probe", "profit falls", "outflows", "defaults")
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Earnings": ("earnings", "result", "profit", "revenue", "quarter", "eps", "dividend", "guidance"),
    "Regulatory": ("sebi", "rbi", "regulator", "penalty", "probe", "ban", "nclt", "fine"),
    "Commodity": ("crude", "gold", "silver", "oil", "brent", "rupee", "dollar", "currency"),
    "Economy": ("gdp", "inflation", "budget", "economy", "fii", "dii", "macro", "repo rate", "gst"),
    "Corporate": ("merger", "acquisition", "buyback", "promoter", "board", "ceo", "deal", "contract"),
}


def _clean_text(value: str | None) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", value or "").split()).strip()


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _child(el: ET.Element, local: str) -> ET.Element | None:
    return next((child for child in el if _local(child.tag) == local), None)


def _text(el: ET.Element, local: str) -> str:
    node = _child(el, local)
    return _clean_text(node.text if node is not None else "")


def _link(el: ET.Element) -> str:
    links = [c for c in el if _local(c.tag) == "link"]
    for node in links:
        href = node.get("href")
        if href and node.get("rel") in (None, "alternate"):
            return href
    if not links:
        return ""
    return links[0].get("href") or _clean_text(links[0].text)


def _published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            continue
    return None


def _sentiment(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    pos = sum(1 for token in _BULLISH if token in text)
    neg = sum(1 for token in _BEARISH if token in text)
    return "Bullish" if pos > neg else "Bearish" if neg > pos else "Neutral"


def _category(title: str, summary: str, default: str) -> str:
    text = f"{title} {summary}".lower()
    for category, tokens in _CATEGORY_KEYWORDS.items():
        if any(token in text for token in tokens):
            return category
    return default or "Market"


def _normalize(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").lower()).strip()


def _fetch_feed(name: str, url: str, default_category: str, limit: int) -> list[dict[str, str]]:
    response = requests.get(
        url,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AlphixNews/1.0)"},
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    nodes = root.findall(".//item")
    if not nodes:
        nodes = [node for node in root.iter() if _local(node.tag) == "entry"]
    out: list[dict[str, str]] = []
    for node in nodes[:limit]:
        title = _text(node, "title")
        if len(title) < 10:
            continue
        summary = _text(node, "description") or _text(node, "summary") or _text(node, "content")
        source_node = _child(node, "source")
        source = _clean_text(source_node.text if source_node is not None else "") or name
        published = _published(_text(node, "pubDate") or _text(node, "updated") or _text(node, "published"))
        out.append({
            "source": source,
            "title": title[:300],
            "link": _link(node) or url,
            "summary": summary[:400],
            "publishedAt": published or datetime.now(timezone.utc).isoformat(),
            "sentiment": _sentiment(title, summary),
            "category": _category(title, summary, default_category),
        })
    return out


def fetch_live_news(limit: int = 40, per_feed: int = 4) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_feed, name, url, category, per_feed) for name, url, category in NEWS_RSS_FEEDS]
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception:
                continue

    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in sorted(items, key=lambda row: row.get("publishedAt", ""), reverse=True):
        key = _normalize(item.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    if len(deduped) < 8 and tinyfish_enabled():
        for row in search_tinyfish(
            "India NSE stock market news today",
            location="IN",
            language="en",
            domain_type="news",
            recency_minutes=24 * 60,
        ):
            key = _normalize(row.get("title", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            title = row.get("title") or ""
            summary = row.get("summary") or ""
            deduped.append({
                "source": row.get("source") or "TinyFish",
                "title": title[:300],
                "link": row.get("url") or "",
                "summary": summary[:400],
                "publishedAt": row.get("published_at") or "",
                "sentiment": _sentiment(title, summary),
                "category": _category(title, summary, "Market"),
            })

    deduped.sort(key=lambda row: row.get("publishedAt", ""), reverse=True)
    return deduped[:limit]
