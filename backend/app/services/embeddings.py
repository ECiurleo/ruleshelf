"""Embeddings: configuration resolution, storage and library backfill."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable

import numpy as np

from app.db import get_setting
from app.providers import Provider, ProviderConfig, build_provider
from app.providers.base import ProviderError
from app.services.chunking import with_section

log = logging.getLogger(__name__)

BATCH_SIZE = 24


def resolve_embedding(
    conn: sqlite3.Connection, provider_id: str | None = None, model: str | None = None
) -> tuple[Provider, str]:
    """Return the configured embedding provider and model, or raise a clear error."""
    provider_id = provider_id or get_setting(conn, "embedding_provider")
    if not provider_id:
        raise ProviderError(
            "Semantic search is not configured. Pick an embedding provider in "
            "Settings → AI providers.",
            409,
        )
    row = conn.execute(
        "SELECT * FROM providers WHERE id = ? AND enabled = 1", (provider_id,)
    ).fetchone()
    if not row:
        raise ProviderError("The configured embedding provider is missing or disabled.", 409)

    model = model or get_setting(conn, "embedding_model") or row["embed_model"]
    if not model:
        raise ProviderError(
            f"No embedding model set for {row['name']}. Choose one in Settings.", 409
        )
    provider = build_provider(ProviderConfig.from_row(row))
    if not getattr(provider, "supports_embeddings", False):
        raise ProviderError(f"{row['name']} cannot generate embeddings.", 409)
    return provider, model


def vector_to_blob(vector: list[float] | np.ndarray) -> tuple[bytes, int]:
    array = np.asarray(vector, dtype=np.float32)
    return array.tobytes(), int(array.shape[0])


def blob_to_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def embed_texts(provider: Provider, model: str, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        vectors.extend(provider.embed(batch, model))
    if len(vectors) != len(texts):
        raise ProviderError(
            f"{provider.config.name} returned {len(vectors)} vectors for {len(texts)} inputs."
        )
    return vectors


def store_embeddings(
    conn: sqlite3.Connection, model: str, chunk_ids: list[int], vectors: list[np.ndarray | list[float]]
) -> None:
    rows = []
    for chunk_id, vector in zip(chunk_ids, vectors, strict=True):
        blob, dim = vector_to_blob(vector)
        rows.append((chunk_id, model, dim, blob))
    conn.executemany(
        "INSERT INTO embeddings (chunk_id, model, dim, vector) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(chunk_id, model) DO UPDATE SET dim = excluded.dim, vector = excluded.vector",
        rows,
    )


def embed_chunks(
    conn: sqlite3.Connection,
    chunks: list[tuple[int, str]],
    provider: Provider,
    model: str,
    force: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Embed ``(chunk_id, text)`` pairs. Returns the number embedded."""
    if not chunks:
        return 0
    done = 0
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        vectors = provider.embed([text for _, text in batch], model)
        if len(vectors) != len(batch):
            raise ProviderError(
                f"{provider.config.name} returned {len(vectors)} vectors for {len(batch)} inputs."
            )
        if force:
            conn.executemany(
                "DELETE FROM embeddings WHERE chunk_id = ? AND model = ?",
                [(chunk_id, model) for chunk_id, _ in batch],
            )
        store_embeddings(conn, model, [chunk_id for chunk_id, _ in batch], vectors)
        conn.commit()
        done += len(batch)
        if progress:
            progress(done, len(chunks))
    return done


def pending_chunks(
    conn: sqlite3.Connection, model: str, game_id: str | None = None, document_id: str | None = None
) -> list[tuple[int, str]]:
    sql = """
        SELECT c.id, c.text, c.section
        FROM chunks c
        LEFT JOIN embeddings e ON e.chunk_id = c.id AND e.model = ?
        WHERE e.chunk_id IS NULL
    """
    params: list = [model]
    if game_id:
        sql += " AND c.game_id = ?"
        params.append(game_id)
    if document_id:
        sql += " AND c.document_id = ?"
        params.append(document_id)
    sql += " ORDER BY c.id"
    return [
        (row["id"], with_section(row["section"], row["text"]))
        for row in conn.execute(sql, params)
    ]


def embedded_count(conn: sqlite3.Connection, model: str) -> int:
    if not model:
        return 0
    row = conn.execute("SELECT COUNT(*) AS n FROM embeddings WHERE model = ?", (model,)).fetchone()
    return row["n"] if row else 0
