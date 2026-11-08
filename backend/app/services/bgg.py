"""Optional BoardGameGeek forum lookup through a web search.

BGG's XML API now requires a registered application token and has no full-text
forum search. We query Bing's public RSS results restricted to BGG thread URLs,
with DuckDuckGo's HTML results as a fallback. We only keep the thread title, URL
and search snippet; no BGG pages are scraped. Forum snippets are always treated
as unofficial and ranked after rulebooks.
"""

from __future__ import annotations

import copy
import html
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
CACHE_SECONDS = 600
TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=15.0, pool=15.0)

_cache: dict[str, tuple[float, list[dict], str | None]] = {}
_lock = threading.Lock()

_THREAD_ID = re.compile(r"/thread/(\d+)")


def _clean(text: str) -> str:
    return " ".join(html.unescape(text or "").split())


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return _clean(BeautifulSoup(text, "html.parser").get_text(" ", strip=True))


def _thread_id(url: str) -> str | None:
    match = _THREAD_ID.search(url or "")
    return match.group(1) if match else None


def _make_result(title: str, url: str, snippet: str) -> dict | None:
    thread_id = _thread_id(url)
    if not thread_id:
        return None
    snippet = _strip_html(snippet)
    title = _strip_html(title)
    title = re.sub(r"\s*[|–-]\s*BoardGameGeek\s*$", "", title).strip()
    if not title:
        title = "BoardGameGeek thread"
    return {
        "chunk_id": f"bgg-{thread_id}",
        "text": snippet,
        "snippet": html.escape(snippet),
        "score": 0.0,
        "page_start": None,
        "page_end": None,
        "source_type": "bgg",
        "url": url,
        "document": {
            "id": "",
            "title": title,
            "role": "forum",
            "role_label": "BGG forum",
            "precedence": 0,
            "overrides": False,
        },
    }


def _bing_rss(search_query: str, limit: int) -> list[dict]:
    params = urlencode({"q": search_query, "format": "rss", "mkt": "en-US", "cc": "US"})
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(
            f"https://www.bing.com/search?{params}",
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        )
    if response.status_code >= 400:
        return []
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError:
        return []

    results: list[dict] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        url = (item.findtext("link") or "").strip()
        if "boardgamegeek.com/thread/" not in url or url in seen:
            continue
        seen.add(url)
        result = _make_result(
            item.findtext("title") or "",
            url,
            item.findtext("description") or "",
        )
        if result:
            results.append(result)
        if len(results) >= limit:
            break
    return results


def _decode_ddg_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg")
        return unquote(target[0]) if target else None
    return href


def _duckduckgo(search_query: str, limit: int) -> list[dict]:
    params = urlencode({"q": search_query, "kl": "us-en"})
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(
            f"https://html.duckduckgo.com/html/?{params}",
            headers={"User-Agent": USER_AGENT},
        )
    if response.status_code >= 400:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    for block in soup.select(".result"):
        link = block.select_one(".result__a")
        snippet = block.select_one(".result__snippet")
        if link:
            rows.append(
                (
                    _decode_ddg_url(link.get("href") or ""),
                    link.get_text(" ", strip=True),
                    snippet.get_text(" ", strip=True) if snippet else "",
                )
            )
    if not rows:
        for link in soup.select("a.result-link"):
            snippet = link.find_next(class_="result-snippet")
            rows.append(
                (
                    _decode_ddg_url(link.get("href") or ""),
                    link.get_text(" ", strip=True),
                    snippet.get_text(" ", strip=True) if snippet else "",
                )
            )

    results: list[dict] = []
    seen: set[str] = set()
    for url, title, snippet in rows:
        if not url or "boardgamegeek.com/thread/" not in url or url in seen:
            continue
        seen.add(url)
        result = _make_result(title, url, snippet)
        if result:
            results.append(result)
        if len(results) >= limit:
            break
    return results


def search_bgg(query: str, game_title: str | None = None, limit: int = 5) -> tuple[list[dict], str | None]:
    query = query.strip()
    if not query:
        return [], None
    cache_key = f"{game_title or ''}|{query}|{limit}"
    now = time.monotonic()
    with _lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return copy.deepcopy(cached[1]), cached[2]

    game = (game_title or "").strip()
    searches = [
        f"site:boardgamegeek.com/thread {game} {query}".strip(),
        f"site:boardgamegeek.com/thread {query}".strip(),
    ]
    if game:
        searches.append(f"site:boardgamegeek.com {game} {query}".strip())

    note: str | None = None
    for search_query in searches:
        for searcher in (_bing_rss, _duckduckgo):
            try:
                results = searcher(search_query, limit)
            except Exception:  # noqa: BLE001 - optional source must never fail the answer
                continue
            if results:
                with _lock:
                    _cache[cache_key] = (now, copy.deepcopy(results), None)
                return results, None
        note = "No BGG forum threads found for this question."

    if note is None:
        note = "BGG web search was unavailable."
    with _lock:
        _cache[cache_key] = (now, [], note)
    return [], note
