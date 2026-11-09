"""Optional Reddit search through the official OAuth API.

Reddit blocks unauthenticated scraping from server IPs, so this uses an
application-only OAuth token (client ID + secret from a Reddit app). It reads
public posts only; no Reddit username or password is needed.
"""

from __future__ import annotations

import base64
import html
import re
import threading
import time
from urllib.parse import urlencode

import httpx

from app.services.bgg import WEB_STOPWORDS

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_URL = "https://oauth.reddit.com"
USER_AGENT = "ruleshelf/0.9 (self-hosted rulebook search)"
TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=10.0, pool=10.0)
MAX_QUERIES = 6

_token_lock = threading.Lock()
_token: tuple[str, str, float] | None = None
_cache: dict[str, tuple[float, list[dict], str | None]] = {}
_cache_lock = threading.Lock()
CACHE_SECONDS = 600


def _access_token(client_id: str, client_secret: str) -> str:
    global _token
    now = time.monotonic()
    with _token_lock:
        if _token and _token[0] == client_id and _token[2] > now:
            return _token[1]
        credentials = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")
        response = httpx.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {credentials}",
                "User-Agent": USER_AGENT,
            },
            timeout=TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError("Reddit rejected the API client ID or secret.")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Reddit did not return an access token.")
        expires = float(payload.get("expires_in") or 3600)
        _token = (client_id, token, now + max(60.0, expires - 60.0))
        return token


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

    add(question)
    if game and terms:
        add(f"{game} {' '.join(terms[:5])}")
    bigrams = [f"{terms[index]} {terms[index + 1]}" for index in range(len(terms) - 1)]
    for bigram in bigrams[:2]:
        used = set(bigram.split())
        for context in [term for term in terms if term not in used][:3]:
            add(f"{game} \"{bigram}\" {context}".strip())
    if terms:
        add(" ".join(terms[:4]))
    return queries[:MAX_QUERIES]


def _result(post: dict) -> dict | None:
    permalink = post.get("permalink")
    title = " ".join(html.unescape(post.get("title") or "").split())
    if not permalink or not title:
        return None
    body = " ".join(html.unescape(post.get("selftext") or "").split())
    snippet = body[:1200] if body else title
    subreddit = post.get("subreddit") or "Reddit"
    return {
        "chunk_id": f"reddit-{post.get('id') or permalink}",
        "text": snippet,
        "snippet": html.escape(snippet),
        "score": 0.0,
        "page_start": None,
        "page_end": None,
        "source_type": "reddit",
        "url": f"https://www.reddit.com{permalink}",
        "document": {
            "id": "",
            "title": title,
            "role": "forum",
            "role_label": f"Reddit · r/{subreddit}",
            "precedence": 0,
            "overrides": False,
        },
    }


def search_reddit(
    query: str,
    game_title: str | None = None,
    limit: int = 5,
    client_id: str = "",
    client_secret: str = "",
) -> tuple[list[dict], str | None]:
    query = query.strip()
    if not query:
        return [], None
    if not client_id or not client_secret:
        return [], "Reddit search needs a Reddit API app (client ID and secret) in Settings."

    cache_key = f"{client_id}|{game_title or ''}|{query}|{limit}"
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return [dict(item) for item in cached[1]], cached[2]

    try:
        token = _access_token(client_id, client_secret)
    except Exception as exc:  # noqa: BLE001 - optional source must not fail the answer
        return [], f"Reddit search unavailable: {exc}"

    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    deadline = time.monotonic() + 20.0
    last_error: str | None = None
    for search_query in _reddit_queries(query, (game_title or "").strip()):
        if time.monotonic() >= deadline:
            last_error = "Reddit search timed out."
            break
        params = {
            "q": search_query,
            "limit": limit,
            "sort": "relevance",
            "t": "all",
            "type": "link",
            "raw_json": 1,
        }
        try:
            response = httpx.get(
                f"{API_URL}/search?{urlencode(params)}",
                headers=headers,
                timeout=TIMEOUT,
            )
        except httpx.RequestError:
            last_error = "Reddit search was unavailable."
            continue
        if response.status_code == 401:
            global _token
            with _token_lock:
                _token = None
            last_error = "Reddit rejected the access token; check the API credentials."
            continue
        if response.status_code >= 400:
            last_error = "Reddit search was unavailable."
            continue
        try:
            children = response.json().get("data", {}).get("children", [])
        except ValueError:
            last_error = "Reddit returned an unreadable response."
            continue
        results: list[dict] = []
        seen: set[str] = set()
        for child in children:
            post = child.get("data") or {}
            permalink = post.get("permalink")
            if not permalink or permalink in seen:
                continue
            seen.add(permalink)
            result = _result(post)
            if result:
                results.append(result)
            if len(results) >= limit:
                break
        if results:
            with _cache_lock:
                _cache[cache_key] = (now, results, None)
            return results, None
        last_error = "No Reddit threads found for this question."

    note = last_error or "No Reddit threads found for this question."
    with _cache_lock:
        _cache[cache_key] = (now, [], note)
    return [], note
