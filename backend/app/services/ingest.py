"""Background ingestion and library maintenance."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

from app.config import CHUNK_OVERLAP, CHUNK_SIZE, FILES_DIR
from app.db import db, get_setting, utcnow
from app.extractors import ExtractionError, extract_file, is_indexed
from app.providers.base import ProviderError
from app.services.chunking import prepare_pages, split_text
from app.services.ocr import DEFAULT_LANGUAGE, ocr_available, ocr_file
from app.services.thumbnails import delete_thumbnail, ensure_thumbnail

log = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ruleshelf-ingest")
        return _executor


def submit_ingest(document_id: str) -> None:
    _get_executor().submit(_safe_ingest, document_id)


def shutdown() -> None:
    """Stop accepting work. A later submit (e.g. in tests) starts a new pool."""
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None


def _safe_ingest(document_id: str) -> None:
    try:
        ingest_document(document_id)
    except Exception:  # noqa: BLE001 - background thread must never crash
        log.exception("Unhandled ingestion error for %s", document_id)


def _clear_chunks(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute(
        "DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE document_id = ?)",
        (document_id,),
    )
    conn.execute(
        "DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id = ?)",
        (document_id,),
    )
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))


def unindex_document(conn: sqlite3.Connection, document_id: str) -> None:
    _clear_chunks(conn, document_id)
    delete_thumbnail(document_id)


def ingest_document(document_id: str) -> None:
    with db() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc:
            return
        indexed = is_indexed(doc["original_filename"])
        auto_ocr = get_setting(conn, "auto_ocr", "1") != "0"
        wants_ocr = bool(doc["ocr_requested"])
        if not indexed and not wants_ocr and not auto_ocr:
            conn.execute(
                "UPDATE documents SET status = 'unindexed', error = NULL WHERE id = ?",
                (document_id,),
            )
            return
        language = get_setting(conn, "ocr_language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE
        conn.execute(
            "UPDATE documents SET status = 'processing', error = NULL WHERE id = ?",
            (document_id,),
        )

    path = FILES_DIR / doc["stored_name"]
    try:
        if not path.exists():
            raise ExtractionError("Stored file is missing from disk.")

        pages = []
        if indexed:
            pages = prepare_pages(extract_file(path, doc["original_filename"]))

        should_ocr = ocr_available() and (wants_ocr or (not pages and auto_ocr))
        if should_ocr:
            with db() as conn:
                conn.execute(
                    "UPDATE documents SET status = 'ocr', error = NULL WHERE id = ?",
                    (document_id,),
                )
            log.info("Running OCR on %s (%s)", doc["original_filename"], language)
            pages = prepare_pages(ocr_file(path, doc["original_filename"], language))

        if not pages:
            if not indexed:
                # A stored-only image with no recognisable text stays unindexed.
                with db() as conn:
                    conn.execute(
                        "UPDATE documents SET status = 'unindexed', ocr_requested = 0, "
                        "error = NULL WHERE id = ?",
                        (document_id,),
                    )
                return
            if should_ocr:
                raise ExtractionError(
                    "No text could be extracted, even with OCR. Check the scan quality and "
                    "the OCR language, or upload a searchable copy."
                )
            if not ocr_available():
                raise ExtractionError(
                    "No text could be extracted, and OCR is not available in this build. "
                    "Install Tesseract or upload an OCR'd copy."
                )
            raise ExtractionError(
                "No text could be extracted. This looks like a scanned document; "
                "use Run OCR to recognise it."
            )

        rows: list[tuple] = []
        ordinal = 0
        for page in pages:
            for chunk in split_text(page.text, CHUNK_SIZE, CHUNK_OVERLAP):
                rows.append(
                    (
                        document_id,
                        doc["game_id"],
                        doc["role"],
                        page.number,
                        page.number,
                        ordinal,
                        chunk,
                    )
                )
                ordinal += 1
        if not rows:
            raise ExtractionError("No text could be extracted from this file.")

        with db() as conn:
            current = conn.execute(
                "SELECT 1 FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if not current:
                return  # deleted while we were working
            _clear_chunks(conn, document_id)
            for row in rows:
                cursor = conn.execute(
                    """
                    INSERT INTO chunks
                        (document_id, game_id, role, page_start, page_end, ordinal, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )
                conn.execute(
                    "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                    (cursor.lastrowid, row[-1]),
                )
            conn.execute(
                """
                UPDATE documents
                SET status = 'ready', error = NULL, page_count = ?, chunk_count = ?,
                    indexed_at = ?, ocr_requested = 0
                WHERE id = ?
                """,
                (len(pages), len(rows), utcnow(), document_id),
            )
            # Refresh the FTS index statistics for better query planning.
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")

        log.info("Indexed %s (%d chunks)", doc["original_filename"], len(rows))
        _thumbnail_quietly(document_id)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        message = str(exc) if isinstance(exc, ExtractionError) else f"Indexing failed: {exc}"
        log.warning("Ingestion failed for %s: %s", doc["original_filename"], exc)
        with db() as conn:
            conn.execute(
                "UPDATE documents SET status = 'error', error = ? WHERE id = ?",
                (message[:1000], document_id),
            )
        return

    _embed_document_quietly(document_id)


def _thumbnail_quietly(document_id: str) -> None:
    """Best-effort: a broken cover must never fail ingestion."""
    try:
        with db() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row:
            ensure_thumbnail(row)
    except Exception as exc:  # noqa: BLE001
        log.warning("Thumbnail failed for %s: %s", document_id, exc)


def _embed_document_quietly(document_id: str) -> None:
    """Embedding is best-effort: a missing key must not fail ingestion."""
    from app.services.embeddings import embed_chunks, pending_chunks, resolve_embedding

    try:
        with db() as conn:
            provider, model = resolve_embedding(conn)
            chunks = pending_chunks(conn, model, document_id=document_id)
            if not chunks:
                return
            embed_chunks(conn, chunks, provider, model)
            log.info("Embedded %d chunks for %s", len(chunks), document_id)
    except ProviderError as exc:
        log.warning("Skipping embeddings for %s: %s", document_id, exc.message)
    except Exception as exc:  # noqa: BLE001
        log.warning("Embedding failed for %s: %s", document_id, exc)


# ---------------------------------------------------------------------------
# Library-wide embedding job
# ---------------------------------------------------------------------------
def create_embed_job(game_id: str | None = None, force: bool = False) -> str:
    import uuid

    job_id = uuid.uuid4().hex
    now = utcnow()
    with db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, kind, status, progress, message, created_at, updated_at) "
            "VALUES (?, 'embed', 'queued', 0, 'Queued', ?, ?)",
            (job_id, now, now),
        )
    _get_executor().submit(_safe_embed_job, job_id, game_id, force)
    return job_id


def _safe_embed_job(job_id: str, game_id: str | None, force: bool) -> None:
    try:
        _run_embed_job(job_id, game_id, force)
    except Exception as exc:  # noqa: BLE001
        log.exception("Embedding job %s failed", job_id)
        _update_job(job_id, status="error", message=str(exc)[:500])


def _update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    result: dict | None = None,
) -> None:
    fields = ["updated_at = ?"]
    params: list = [utcnow()]
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if progress is not None:
        fields.append("progress = ?")
        params.append(progress)
    if message is not None:
        fields.append("message = ?")
        params.append(message)
    if result is not None:
        fields.append("result = ?")
        params.append(json.dumps(result))
    params.append(job_id)
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", params)


def _run_embed_job(job_id: str, game_id: str | None, force: bool) -> None:
    from app.services.embeddings import embed_chunks, pending_chunks, resolve_embedding

    with db() as conn:
        provider, model = resolve_embedding(conn)
        if force:
            if game_id:
                conn.execute(
                    "DELETE FROM embeddings WHERE model = ? AND chunk_id IN "
                    "(SELECT id FROM chunks WHERE game_id = ?)",
                    (model, game_id),
                )
            else:
                conn.execute("DELETE FROM embeddings WHERE model = ?", (model,))
        chunks = pending_chunks(conn, model, game_id=game_id)

    total = len(chunks)
    if total == 0:
        _update_job(
            job_id,
            status="done",
            progress=1.0,
            message="Everything is already embedded.",
            result={"embedded": 0, "model": model},
        )
        return

    _update_job(job_id, status="running", message=f"Embedding 0 of {total} chunks")

    def progress(done: int, _total: int) -> None:
        _update_job(
            job_id,
            progress=done / total,
            message=f"Embedding {done} of {total} chunks",
        )

    with db() as conn:
        embedded = embed_chunks(conn, chunks, provider, model, progress=progress)

    _update_job(
        job_id,
        status="done",
        progress=1.0,
        message=f"Embedded {embedded} chunks with {model}.",
        result={"embedded": embedded, "model": model},
    )
