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

# Words that add nothing to a web search and make Bing/DuckDuckGo too strict.
WEB_STOPWORDS = {
    "a", "about", "after", "again", "all", "also", "an", "and", "any", "are",
    "as", "at", "automatically", "be", "because", "before", "but", "by", "can",
    "could", "did", "do", "does", "during", "exactly", "for", "from", "get",
    "gets", "got", "happen", "happens", "has", "have", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "make", "makes", "me", "my", "of", "on",
    "or", "over", "play", "played", "plays", "put", "puts", "really", "should",
    "so", "still", "than", "that", "the", "their", "then", "there", "these",
    "they", "this", "to", "trigger", "triggers", "under", "use", "used", "uses",
    "using", "was", "we", "what", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your",
}


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


def _bgg_queries(question: str, game: str) -> list[str]:
    """Build a ladder of searches from specific to broad.

    Search engines treat long natural-language questions as a bag of required
    terms, so "if I draw a Flood card during location setup..." finds nothing
    while the shorter quoted phrase "flood card" plus "setup" finds the exact
    threads. Try the old precise forms first, then quoted keyword phrases.
    """
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9']+", question)
        if token.lower() not in WEB_STOPWORDS and len(token) > 1
    ]
    terms: list[str] = []
    for term in tokens:
        if term not in terms:
            terms.append(term)
    terms = terms[:10]

    queries: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.split())
        if value and value not in queries:
            queries.append(value)

    if game:
        add(f"site:boardgamegeek.com/thread {game} {question}")
        add(f"site:boardgamegeek.com/thread {question}")
    else:
        add(f"site:boardgamegeek.com/thread {question}")

    # Quoted noun-phrase pairs are what finally surface threads whose titles
    # only share two or three words with the question. Keep this short: every
    # extra search risks tripping the engine's rate limit.
    bigrams = [f"{terms[index]} {terms[index + 1]}" for index in range(len(terms) - 1)]
    for bigram in bigrams[:2]:
        used = set(bigram.split())
        contexts = [term for term in terms if term not in used]
        for context in contexts[:3]:
            add(f"{game} \"{bigram}\" {context}".strip())

    short = " ".join(terms[:5])
    if short:
        add(f"site:boardgamegeek.com {game} {short}".strip())
        add(f"{game} {short}".strip())

    if game:
        add(f"site:boardgamegeek.com {game} {question}")
        add(f"{game} {question}")
    add(question)
    return queries[:14]


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
    searches = _bgg_queries(query, game)

    note: str | None = None
    deadline = now + 20.0
    # Try every query on one engine before falling back to the other. This
    # keeps the number of requests low, which matters because both engines
    # rate-limit aggressive scrapers, and the deadline keeps a slow engine
    # from holding the community panel open indefinitely.
    for searcher in (_bing_rss, _duckduckgo):
        for search_query in searches:
            if time.monotonic() >= deadline:
                note = "BGG search timed out; the rulebook answer is unaffected."
                break
            try:
                results = searcher(search_query, limit)
            except Exception:  # noqa: BLE001 - optional source must never fail the answer
                continue
            if results:
                with _lock:
                    _cache[cache_key] = (now, copy.deepcopy(results), None)
                return results, None
        if note:
            break
        note = "No BGG forum threads found for this question."

    if note is None:
        note = "BGG web search was unavailable."
    with _lock:
        _cache[cache_key] = (now, [], note)
    return [], note
