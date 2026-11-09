"""Plain web search used by the optional community sources.

Yahoo's HTML results are Bing-backed and, unlike Bing's RSS endpoint, return
Reddit and BoardGameGeek links for ordinary natural-language queries without
an API key. Results are only used for titles, URLs and snippets; pages are
never scraped.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=10.0)
YAHOO_URL = "https://search.yahoo.com/search"
_RU = re.compile(r"/RU=([^/]+)/")
_SLUG = re.compile(r"[^A-Za-z0-9]+")


def _unwrap(href: str) -> str:
    href = (href or "").strip()
    match = _RU.search(href)
    if match:
        href = unquote(match.group(1))
    if href.startswith("//"):
        href = "https:" + href
    return href


def _slug_title(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug, flags=re.IGNORECASE)
    title = " ".join(part for part in _SLUG.split(slug) if part)
    return title[:1].upper() + title[1:] if title else ""


def search_yahoo(query: str, limit: int = 10) -> list[dict]:
    """Return ``{title, url, snippet}`` from Yahoo's public HTML results."""
    query = " ".join((query or "").split())
    if not query:
        return []
    try:
        response = httpx.get(
            YAHOO_URL,
            params={"p": query, "n": max(limit, 10)},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
    except httpx.RequestError:
        return []
    if response.status_code >= 400:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()
    for block in soup.select("div.dd.algo"):
        link = block.select_one(".compTitle a") or block.select_one("a[href]")
        if not link:
            continue
        url = _unwrap(link.get("href") or "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        snippet_element = block.select_one(".compText") or block.select_one(".aAbs")
        snippet = (
            snippet_element.get_text(" ", strip=True) if snippet_element else ""
        )
        title = _slug_title(url)
        if not title:
            title = link.get_text(" ", strip=True)
        results.append(
            {
                "title": title[:300],
                "url": url,
                "snippet": " ".join(snippet.split())[:1200],
            }
        )
        if len(results) >= limit:
            break
    return results
