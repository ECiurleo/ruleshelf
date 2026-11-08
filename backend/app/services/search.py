"""Keyword, semantic and hybrid retrieval."""

from __future__ import annotations

import html
import json
import re
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from app.providers import Provider
from app.providers.base import ProviderError
from app.services.embeddings import blob_to_vector

RRF_K = 60
HIGHLIGHT_OPEN = "\x01"
HIGHLIGHT_CLOSE = "\x02"

# Common words carry no retrieval signal and make snippets noisy.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does",
    "for", "from", "how", "i", "if", "in", "is", "it", "its", "me", "my", "of",
    "on", "or", "should", "so", "that", "the", "their", "then", "there", "this",
    "to", "was", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",
}


@dataclass(slots=True)
class SearchFilters:
    game_id: str | None = None
    roles: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)

    def conditions(self, alias: str = "c") -> tuple[list[str], list]:
        clauses: list[str] = []
        params: list = []
        if self.game_id:
            clauses.append(f"{alias}.game_id = ?")
            params.append(self.game_id)
        if self.roles:
            placeholders = ", ".join("?" for _ in self.roles)
            clauses.append(f"{alias}.role IN ({placeholders})")
            params.extend(self.roles)
        if self.document_ids:
            placeholders = ", ".join("?" for _ in self.document_ids)
            clauses.append(f"{alias}.document_id IN ({placeholders})")
            params.extend(self.document_ids)
        return clauses, params


def role_labels(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    for row in conn.execute("SELECT id, roles FROM game_types"):
        try:
            roles = json.loads(row["roles"])
        except json.JSONDecodeError:
            roles = []
        labels[row["id"]] = {r.get("id"): r.get("label", r.get("id", "")) for r in roles}
    return labels


def build_match_query(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Quoted phrases are preserved, remaining tokens are AND-ed, and the final
    token gets a prefix wildcard so "beasti" finds "bestiary".
    """
    query = query.strip()
    if not query:
        return ""
    phrases = re.findall(r'"([^"]+)"', query)
    rest = re.sub(r'"[^"]+"', " ", query)
    tokens = [t for t in re.findall(r"[\w'-]+", rest, flags=re.UNICODE) if t]
    meaningful = [t for t in tokens if t.lower() not in STOPWORDS]
    if meaningful:
        tokens = meaningful
    parts = [f'"{phrase}"' for phrase in phrases]
    for index, token in enumerate(tokens):
        suffix = "*" if index == len(tokens) - 1 and len(token) >= 3 else ""
        parts.append(f'"{token}"{suffix}')
    return " AND ".join(parts)


def _render_fts_snippet(raw: str | None) -> str:
    if not raw:
        return ""
    parts = raw.split(HIGHLIGHT_OPEN)
    rendered = [html.escape(parts[0])]
    for part in parts[1:]:
        if HIGHLIGHT_CLOSE in part:
            marked, rest = part.split(HIGHLIGHT_CLOSE, 1)
            rendered.append(f"<mark>{html.escape(marked)}</mark>{html.escape(rest)}")
        else:
            rendered.append(html.escape(part))
    return "".join(rendered)


def _query_terms(query: str) -> list[str]:
    terms = [
        term
        for term in re.findall(r"[\w'-]{3,}", query.lower(), flags=re.UNICODE)
        if term not in STOPWORDS
    ]
    seen: list[str] = []
    for term in terms:
        if term not in seen:
            seen.append(term)
    return seen[:6]


def _highlight_window(text: str, query: str, radius: int = 280) -> str:
    terms = _query_terms(query)
    lowered = text.lower()
    first = None
    for term in terms:
        pos = lowered.find(term)
        if pos != -1 and (first is None or pos < first):
            first = pos
    if first is None:
        window = text[: radius * 2]
        return html.escape(window) + ("…" if len(text) > len(window) else "")

    start = max(0, first - radius // 2)
    end = min(len(text), first + radius)
    window = text[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""

    if not terms:
        return prefix + html.escape(window) + suffix

    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    out: list[str] = []
    cursor = 0
    for match in pattern.finditer(window):
        out.append(html.escape(window[cursor : match.start()]))
        out.append(f"<mark>{html.escape(match.group(0))}</mark>")
        cursor = match.end()
    out.append(html.escape(window[cursor:]))
    return prefix + "".join(out) + suffix


def _row_to_result(row: sqlite3.Row, snippet: str, score: float, labels: dict) -> dict:
    return {
        "chunk_id": row["id"],
        "text": row["text"],
        "snippet": snippet,
        "score": score,
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "document": {
            "id": row["document_id"],
            "title": row["document_title"],
            "role": row["role"],
            "role_label": labels.get(row["game_type"], {}).get(
                row["role"], row["role"].replace("_", " ").title()
            ),
        },
        "game": {
            "id": row["game_id"],
            "title": row["game_title"],
            "game_type": row["game_type"],
        },
    }


def search_keyword(
    conn: sqlite3.Connection,
    query: str,
    filters: SearchFilters,
    limit: int = 25,
    labels: dict | None = None,
) -> list[dict]:
    match = build_match_query(query)
    if not match:
        return []
    labels = labels if labels is not None else role_labels(conn)
    clauses, params = filters.conditions("c")

    for expression in (match, match.replace(" AND ", " OR ")):
        sql = f"""
            SELECT c.id, c.text, c.page_start, c.page_end, c.document_id, c.game_id,
                   c.role, d.title AS document_title, g.title AS game_title,
                   g.game_type,
                   snippet(chunks_fts, 0, '{HIGHLIGHT_OPEN}', '{HIGHLIGHT_CLOSE}',
                           ' … ', 48) AS snip,
                   bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN documents d ON d.id = c.document_id
            JOIN games g ON g.id = c.game_id
            WHERE chunks_fts MATCH ?
              {'AND ' + ' AND '.join(clauses) if clauses else ''}
            ORDER BY rank
            LIMIT ?
        """
        rows = conn.execute(sql, [expression, *params, limit]).fetchall()
        if rows:
            return [
                _row_to_result(
                    row, _render_fts_snippet(row["snip"]), float(-row["rank"]), labels
                )
                for row in rows
            ]
    return []


def search_semantic(
    conn: sqlite3.Connection,
    provider: Provider,
    model: str,
    query: str,
    filters: SearchFilters,
    limit: int = 25,
    labels: dict | None = None,
) -> list[dict]:
    labels = labels if labels is not None else role_labels(conn)
    clauses, params = filters.conditions("c")
    sql = f"""
        SELECT c.id, c.text, c.page_start, c.page_end, c.document_id, c.game_id,
               c.role, d.title AS document_title, g.title AS game_title,
               g.game_type, e.vector, e.dim
        FROM embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        JOIN games g ON g.id = c.game_id
        WHERE e.model = ?
          {'AND ' + ' AND '.join(clauses) if clauses else ''}
    """
    rows = conn.execute(sql, [model, *params]).fetchall()
    if not rows:
        return []

    query_vector = np.asarray(provider.embed([query], model)[0], dtype=np.float32)
    query_norm = float(np.linalg.norm(query_vector)) or 1.0

    matrix = np.vstack([blob_to_vector(row["vector"]) for row in rows])
    if matrix.shape[1] != query_vector.shape[0]:
        raise ProviderError(
            "The stored embeddings were made with a different model dimension. "
            "Re-embed the library in Settings.",
            409,
        )
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1.0
    scores = (matrix @ query_vector) / (norms * query_norm)

    order = np.argsort(scores)[::-1][:limit]
    # Embedding scores are anisotropic: unrelated text still sits around 0.4.
    # Keep the neighbourhood of the best hit instead of returning the whole book.
    if len(order):
        cutoff = float(scores[order[0]]) - 0.15
        order = np.array([index for index in order if scores[index] >= cutoff])
    return [
        _row_to_result(
            rows[index],
            _highlight_window(rows[index]["text"], query),
            float(scores[index]),
            labels,
        )
        for index in order
    ]


def rrf_merge(*ranked_lists: list[dict], limit: int) -> list[dict]:
    combined: dict[int, dict] = {}
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for position, item in enumerate(ranked):
            chunk_id = item["chunk_id"]
            combined.setdefault(chunk_id, item)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position + 1)
    ordered = sorted(combined.values(), key=lambda item: scores[item["chunk_id"]], reverse=True)
    for item in ordered:
        item["score"] = round(scores[item["chunk_id"]], 6)
        item["retrieval"] = "hybrid"
    return ordered[:limit]


def search(
    conn: sqlite3.Connection,
    query: str,
    mode: str = "hybrid",
    filters: SearchFilters | None = None,
    limit: int = 25,
    embedding: tuple[Provider, str] | None = None,
) -> tuple[list[dict], str, str | None]:
    """Return (results, mode_used, note)."""
    filters = filters or SearchFilters()
    labels = role_labels(conn)
    mode = mode if mode in {"keyword", "semantic", "hybrid"} else "hybrid"
    pool = max(limit * 4, 40)

    if mode == "keyword":
        return search_keyword(conn, query, filters, limit, labels), "keyword", None

    if mode == "semantic":
        if not embedding:
            raise ProviderError(
                "Semantic search needs an embedding provider. Configure one in Settings.",
                409,
            )
        provider, model = embedding
        results = search_semantic(conn, provider, model, query, filters, limit, labels)
        return results, "semantic", None

    # Hybrid: keyword always works, semantic is a bonus.
    keyword_hits = search_keyword(conn, query, filters, pool, labels)
    if not embedding:
        return keyword_hits[:limit], "keyword", (
            "Semantic search is off (no embedding provider), showing keyword results."
        )
    provider, model = embedding
    try:
        semantic_hits = search_semantic(conn, provider, model, query, filters, pool, labels)
    except ProviderError as exc:
        return keyword_hits[:limit], "keyword", f"Semantic search unavailable: {exc.message}"
    if not semantic_hits:
        return keyword_hits[:limit], "keyword", "No semantic matches yet; showing keyword results."
    merged = rrf_merge(keyword_hits, semantic_hits, limit=limit)
    return merged, "hybrid", None
