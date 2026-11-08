"""Document upload, listing, re-indexing and raw file access."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import FILES_DIR, MAX_UPLOAD_BYTES
from app.db import db, get_setting, utcnow
from app.extractors import resolve_extension
from app.services.ingest import submit_ingest, unindex_document

router = APIRouter(prefix="/api/documents", tags=["documents"])

CHUNK = 1024 * 1024


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = None
    sort_order: int | None = None


def _roles_for(conn, game_id: str) -> list[dict]:
    row = conn.execute(
        "SELECT t.roles FROM games g JOIN game_types t ON t.id = g.game_type WHERE g.id = ?",
        (game_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Game not found.")
    try:
        return json.loads(row["roles"])
    except json.JSONDecodeError:
        return []


def _doc_payload(conn, row, embedding_model: str) -> dict:
    embedded = 0
    if embedding_model:
        embedded = conn.execute(
            "SELECT COUNT(*) AS n FROM embeddings e JOIN chunks c ON c.id = e.chunk_id "
            "WHERE c.document_id = ? AND e.model = ?",
            (row["id"], embedding_model),
        ).fetchone()["n"]
    return {
        "id": row["id"],
        "game_id": row["game_id"],
        "title": row["title"],
        "role": row["role"],
        "sort_order": row["sort_order"],
        "original_filename": row["original_filename"],
        "content_type": row["content_type"],
        "size_bytes": row["size_bytes"],
        "page_count": row["page_count"],
        "chunk_count": row["chunk_count"],
        "embedded_chunks": embedded,
        "status": row["status"],
        "error": row["error"],
        "created_at": row["created_at"],
        "indexed_at": row["indexed_at"],
    }


@router.get("")
def list_documents(game_id: str | None = None, role: str | None = None):
    embedding_model = ""
    with db() as conn:
        embedding_model = get_setting(conn, "embedding_model")
        params: list = []
        sql = "SELECT * FROM documents"
        clauses = []
        if game_id:
            clauses.append("game_id = ?")
            params.append(game_id)
        if role:
            clauses.append("role = ?")
            params.append(role)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(sql, params).fetchall()
        docs = [_doc_payload(conn, row, embedding_model) for row in rows]

        order: list[str] = []
        order_index: dict[str, int] = {}
        if game_id:
            order = [r["id"] for r in _roles_for(conn, game_id)]
            order_index = {role_id: index for index, role_id in enumerate(order)}
        docs.sort(key=lambda d: (order_index.get(d["role"], 99), d["sort_order"], d["title"].lower()))
    return {"documents": docs, "total": len(docs)}


@router.post("", status_code=201)
async def upload_document(
    game_id: str = Form(...),
    role: str = Form("core"),
    title: str = Form(""),
    file: UploadFile = File(...),
):
    filename = file.filename or "upload"
    ext = resolve_extension(filename)
    with db() as conn:
        roles = {r["id"] for r in _roles_for(conn, game_id)}
        if role not in roles:
            raise HTTPException(400, f"Role '{role}' is not valid for this game type.")

    document_id = uuid.uuid4().hex
    stored_name = f"{document_id}.{ext}"
    target = FILES_DIR / stored_name
    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413,
                        f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
                    )
                handle.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise HTTPException(500, f"Could not store upload: {exc}") from exc

    default_title = Path(filename).stem
    title = (title or default_title).strip()[:200] or default_title
    content_type = file.content_type or "application/octet-stream"

    with db() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                id, game_id, title, role, original_filename, stored_name, content_type,
                size_bytes, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                document_id,
                game_id,
                title,
                role,
                filename,
                stored_name,
                content_type,
                size,
                utcnow(),
            ),
        )
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        payload = _doc_payload(conn, row, get_setting(conn, "embedding_model"))
    submit_ingest(document_id)
    return payload


@router.get("/{document_id}")
def get_document(document_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        return _doc_payload(conn, row, get_setting(conn, "embedding_model"))


@router.patch("/{document_id}")
def update_document(document_id: str, payload: DocumentUpdate):
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        fields = payload.model_dump(exclude_none=True)
        if "role" in fields:
            valid = {r["id"] for r in _roles_for(conn, row["game_id"])}
            if fields["role"] not in valid:
                raise HTTPException(400, f"Role '{fields['role']}' is not valid for this game.")
            conn.execute(
                "UPDATE chunks SET role = ? WHERE document_id = ?",
                (fields["role"], document_id),
            )
        if "title" in fields:
            fields["title"] = fields["title"].strip()
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(
                f"UPDATE documents SET {assignments} WHERE id = ?",
                [*fields.values(), document_id],
            )
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return _doc_payload(conn, row, get_setting(conn, "embedding_model"))


@router.delete("/{document_id}")
def delete_document(document_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        unindex_document(conn, document_id)
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    if row["stored_name"]:
        (FILES_DIR / row["stored_name"]).unlink(missing_ok=True)
    return {"deleted": True}


@router.post("/{document_id}/reindex")
def reindex_document(document_id: str):
    with db() as conn:
        row = conn.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        conn.execute(
            "UPDATE documents SET status = 'pending', error = NULL WHERE id = ?", (document_id,)
        )
    submit_ingest(document_id)
    return {"status": "pending"}


@router.get("/{document_id}/file")
def document_file(
    document_id: str, download: bool = Query(default=False)
):
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
    path = FILES_DIR / row["stored_name"]
    if not path.exists():
        raise HTTPException(404, "Stored file is missing.")
    filename = row["original_filename"] or path.name
    return FileResponse(
        path,
        media_type=row["content_type"] or "application/octet-stream",
        filename=filename,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{document_id}/pages")
def document_page(document_id: str, page: int = Query(default=1, ge=1)):
    """Full text of one page/chapter, used by the reader drawer."""
    with db() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc:
            raise HTTPException(404, "Document not found.")
        rows = conn.execute(
            """
            SELECT id, text, page_start, page_end, ordinal
            FROM chunks
            WHERE document_id = ? AND page_start <= ? AND page_end >= ?
            ORDER BY ordinal
            """,
            (document_id, page, page),
        ).fetchall()
        max_page = conn.execute(
            "SELECT MAX(page_start) AS m FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchone()["m"]
    return {
        "document": {"id": doc["id"], "title": doc["title"], "role": doc["role"]},
        "page": page,
        "total_pages": max_page or 0,
        "chunks": [{"id": r["id"], "text": r["text"], "ordinal": r["ordinal"]} for r in rows],
    }
