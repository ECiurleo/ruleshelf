"""Optional Reddit search through plain web search.

Reddit blocks unauthenticated API/scraping requests from many server IPs, and
setting up an OAuth app is friction for a self-hosted library. Instead this
uses Yahoo's public search results (Bing-backed) restricted to Reddit thread
URLs. Only titles, URLs and snippets are used; Reddit pages are never scraped.
"""

from __future__ import annotations

import html
import re
import time
from urllib.parse import urlparse

from app.services.bgg import WEB_STOPWORDS
from app.services.websearch import search_yahoo

CACHE_SECONDS = 600
MAX_QUERIES = 6
_cache: dict[str, tuple[float, list[dict], str | None]] = {}
_THREAD = re.compile(r"/comments/([A-Za-z0-9]+)")
_DATE_PREFIX = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4} · ")


def _terms(question: str) -> list[str]:
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9']+", question)
        if token.lower() not in WEB_STOPWORDS and len(token) > 1
    ]
    terms: list[str] = []
    for term in tokens:
        if term not in terms:
            terms.append(term)
    return terms[:10]


def _reddit_queries(question: str, game: str) -> list[str]:
    terms = _terms(question)
    queries: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.split())
        if value and value not in queries:
            queries.append(value)

    short = " ".join(terms[:3])
    if game:
        add(f'site:reddit.com "{game}" {short}'.strip())
        slug = re.sub(r"[^A-Za-z0-9]+", "_", game).strip("_")
        if slug:
            add(f"site:reddit.com/r/{slug} {short}".strip())
        add(f'"{game}" reddit {short}'.strip())
        bigrams = [
            f"{terms[index]} {terms[index + 1]}" for index in range(len(terms) - 1)
        ]
        for bigram in bigrams[:2]:
            add(f'site:reddit.com "{game}" "{bigram}"'.strip())
        add(f'site:reddit.com "{game}"')
    if short:
        add(f"site:reddit.com {short}")
    add(question)
    return queries[:MAX_QUERIES]


def _make_result(title: str, url: str, snippet: str) -> dict | None:
    parsed = urlparse(url)
    if "reddit.com" not in parsed.netloc or "/comments/" not in parsed.path:
        return None
    match = _THREAD.search(parsed.path)
    parts = [part for part in parsed.path.split("/") if part]
    subreddit = parts[1] if len(parts) > 1 and parts[0] == "r" else "Reddit"
    snippet = " ".join(html.unescape(snippet or "").split())
    snippet = _DATE_PREFIX.sub("", snippet)
    title = " ".join(html.unescape(title or "").split()) or "Reddit thread"
    body = snippet[:1200] if snippet else title
    return {
        "chunk_id": f"reddit-{match.group(1) if match else abs(hash(url))}",
        "text": body,
        "snippet": html.escape(body),
        "score": 0.0,
        "page_start": None,
        "page_end": None,
        "source_type": "reddit",
        "url": f"https://www.reddit.com{parsed.path}",
        "document": {
            "id": "",
            "title": title,
            "role": "forum",
            "role_label": f"Reddit · r/{subreddit}",
            "precedence": 0,
            "overrides": False,
        },
    }


def _game_terms(game: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[A-Za-z0-9]+", (game or "").lower())
        if len(term) > 2
    ]


def _relevance(result: dict, terms: list[str]) -> int:
    text = " ".join(
        [
            result["document"]["title"],
            result["text"],
            result["url"],
        ]
    ).lower()
    return sum(1 for term in terms if term in text)


def search_reddit(
    query: str,
    game_title: str | None = None,
    limit: int = 3,
) -> tuple[list[dict], str | None]:
    query = query.strip()
    if not query:
        return [], None
    game = (game_title or "").strip()
    game_terms = _game_terms(game)
    query_terms = _terms(query)

    cache_key = f"{game_title or ''}|{query}|{limit}"
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < CACHE_SECONDS:
        return [dict(item) for item in cached[1]], cached[2]

    deadline = time.monotonic() + 20.0
    last_note: str | None = None
    collected: dict[str, dict] = {}
    for search_query in _reddit_queries(query, game):
        if time.monotonic() >= deadline:
            last_note = "Reddit search timed out."
            break
        for item in search_yahoo(search_query, max(limit * 3, 10)):
            url = item["url"]
            if "/comments/" not in url or url in collected:
                continue
            result = _make_result(item["title"], url, item["snippet"])
            if not result:
                continue
            haystack = f"{result['document']['title']} {result['text']} {result['url']}".lower()
            if game_terms and not any(term in haystack for term in game_terms):
                continue
            collected[url] = result
        if len(collected) >= limit:
            break
        last_note = "No Reddit threads found for this question."

    if collected:
        ranked = sorted(
            collected.values(),
            key=lambda item: _relevance(item, query_terms),
            reverse=True,
        )
        specific = [term for term in query_terms if len(term) >= 5]
        if specific:
            ranked = [
                item
                for item in ranked
                if any(
                    term
                    in f"{item['document']['title']} {item['text']}".lower()
                    for term in specific
                )
            ]
            if not ranked:
                note = "No relevant Reddit threads found for this question."
                _cache[cache_key] = (now, [], note)
                return [], note
        results = ranked[:limit]
        _cache[cache_key] = (now, results, None)
        return results, None

    note = last_note or "No Reddit threads found for this question."
    _cache[cache_key] = (now, [], note)
    return [], note
