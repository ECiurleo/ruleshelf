"""Document upload, listing, re-indexing and raw file access."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import require_admin
from app.config import FILES_DIR, MAX_UPLOAD_BYTES, UPLOADS_DIR
from app.db import db, get_setting, utcnow
from app.extractors import is_indexed, resolve_extension
from app.services.ingest import submit_ingest, unindex_document
from app.services.ocr import is_image_file, ocr_available, ocr_supported
from app.services.thumbnails import delete_thumbnail, ensure_thumbnail

router = APIRouter(prefix="/api/documents", tags=["documents"])

CHUNK = 1024 * 1024


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = None
    campaign_id: str | None = None
    scenario_id: str | None = None
    sort_order: int | None = Field(default=None, ge=0)


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


UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(slots=True)
class UploadTarget:
    game_id: str
    role: str
    campaign_id: str | None
    scenario_id: str | None


def _resolve_target(
    conn,
    game_id: str,
    role: str,
    campaign_id: str | None,
    scenario_id: str | None,
) -> UploadTarget:
    """Validate where a document goes and inherit from a scenario when needed."""
    campaign_id = (campaign_id or "").strip() or None
    scenario_id = (scenario_id or "").strip() or None
    if scenario_id:
        parent = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (scenario_id,)
        ).fetchone()
        if not parent:
            raise HTTPException(400, "Scenario not found.")
        if parent["game_id"] != game_id:
            raise HTTPException(400, "Scenario belongs to another game.")
        if parent["role"] != "campaign":
            raise HTTPException(400, "Only campaign documents can hold scenario files.")
        if parent["scenario_id"]:
            raise HTTPException(400, "A scenario file cannot hold its own files.")
        # Files inherit the scenario's section and campaign.
        role = "campaign"
        campaign_id = parent["campaign_id"]

    roles = {r["id"] for r in _roles_for(conn, game_id)}
    if role not in roles:
        raise HTTPException(400, f"Role '{role}' is not valid for this game type.")
    if campaign_id:
        if role != "campaign":
            raise HTTPException(400, "Only campaign documents can belong to a campaign.")
        campaign = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ? AND game_id = ?",
            (campaign_id, game_id),
        ).fetchone()
        if not campaign:
            raise HTTPException(400, "Campaign not found for this game.")
    return UploadTarget(game_id, role, campaign_id, scenario_id)


def _insert_document(
    conn,
    *,
    document_id: str,
    target: UploadTarget,
    title: str,
    filename: str,
    stored_name: str,
    content_type: str,
    size: int,
    indexed: bool,
) -> dict:
    if target.scenario_id:
        sort_row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM documents "
            "WHERE scenario_id = ?",
            (target.scenario_id,),
        ).fetchone()
    elif target.campaign_id:
        sort_row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM documents "
            "WHERE campaign_id = ? AND scenario_id IS NULL",
            (target.campaign_id,),
        ).fetchone()
    else:
        sort_row = None
    sort_order = sort_row["n"] if sort_row else 0
    conn.execute(
        """
        INSERT INTO documents (
            id, game_id, title, role, campaign_id, scenario_id, sort_order,
            original_filename, stored_name, content_type, size_bytes, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            target.game_id,
            title,
            target.role,
            target.campaign_id,
            target.scenario_id,
            sort_order,
            filename,
            stored_name,
            content_type,
            size,
            "pending" if indexed else "unindexed",
            utcnow(),
        ),
    )
    row = conn.execute(
        "SELECT d.*, c.title AS campaign_title FROM documents d "
        "LEFT JOIN campaigns c ON c.id = d.campaign_id WHERE d.id = ?",
        (document_id,),
    ).fetchone()
    return _doc_payload(conn, row, get_setting(conn, "embedding_model"))


def _upload_meta_path(upload_id: str) -> Path | None:
    if not _UPLOAD_ID.fullmatch(upload_id):
        return None
    return UPLOADS_DIR / f"{upload_id}.json"


def _upload_part_path(upload_id: str) -> Path:
    return UPLOADS_DIR / f"{upload_id}.part"


def _read_upload(upload_id: str) -> dict:
    path = _upload_meta_path(upload_id)
    if not path or not path.exists():
        raise HTTPException(404, "Upload not found or expired.")
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, "Upload not found or expired.") from None


def _clear_upload(upload_id: str) -> None:
    path = _upload_meta_path(upload_id)
    if path:
        path.unlink(missing_ok=True)
    _upload_part_path(upload_id).unlink(missing_ok=True)


def _sweep_uploads() -> None:
    """Drop abandoned chunked uploads after a day."""
    cutoff = time.time() - 24 * 3600
    try:
        for path in UPLOADS_DIR.glob("*"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best effort
        pass


def _doc_payload(conn, row, embedding_model: str) -> dict:
    embedded = 0
    if embedding_model:
        embedded = conn.execute(
            "SELECT COUNT(*) AS n FROM embeddings e JOIN chunks c ON c.id = e.chunk_id "
            "WHERE c.document_id = ? AND e.model = ?",
            (row["id"], embedding_model),
        ).fetchone()["n"]
    try:
        campaign_title = row["campaign_title"]
    except (IndexError, KeyError):
        campaign_title = None
    file_count = conn.execute(
        "SELECT COUNT(*) AS n FROM documents WHERE scenario_id = ?", (row["id"],)
    ).fetchone()["n"]
    return {
        "id": row["id"],
        "game_id": row["game_id"],
        "title": row["title"],
        "role": row["role"],
        "campaign_id": row["campaign_id"],
        "campaign_title": campaign_title,
        "scenario_id": row["scenario_id"],
        "file_count": file_count,
        "indexed": is_indexed(row["original_filename"]) or row["chunk_count"] > 0,
        "is_image": is_image_file(row["original_filename"]),
        "can_ocr": ocr_available() and ocr_supported(row["original_filename"]),
        "ocr_requested": bool(row["ocr_requested"]),
        "sort_order": row["sort_order"],
        "original_filename": row["original_filename"],
        "content_type": row["content_type"],
        "size_bytes": row["size_bytes"],
        "page_count": row["page_count"],
        "chunk_count": row["chunk_count"],
        "embedded_chunks": embedded,
        "thumbnail_url": f"/api/documents/{row['id']}/thumbnail?v="
        + quote(row["indexed_at"] or row["created_at"] or "", safe=""),
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
        sql = (
            "SELECT d.*, c.title AS campaign_title FROM documents d "
            "LEFT JOIN campaigns c ON c.id = d.campaign_id"
        )
        clauses = []
        if game_id:
            clauses.append("d.game_id = ?")
            params.append(game_id)
        if role:
            clauses.append("d.role = ?")
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


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
async def upload_document(
    game_id: str = Form(...),
    role: str = Form("core"),
    title: str = Form(""),
    campaign_id: str = Form(""),
    scenario_id: str = Form(""),
    file: UploadFile = File(...),
):
    filename = Path(file.filename or "upload").name or "upload"
    ext = resolve_extension(filename)
    indexed = is_indexed(filename)
    with db() as conn:
        target_info = _resolve_target(conn, game_id, role, campaign_id, scenario_id)

    document_id = uuid.uuid4().hex
    stored_name = f"{document_id}.{ext}"
    destination = FILES_DIR / stored_name
    size = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413,
                        f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
                    )
                handle.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        destination.unlink(missing_ok=True)
        raise HTTPException(500, f"Could not store upload: {exc}") from exc

    default_title = Path(filename).stem
    title = (title or default_title).strip()[:200] or default_title
    content_type = file.content_type or "application/octet-stream"

    with db() as conn:
        payload = _insert_document(
            conn,
            document_id=document_id,
            target=target_info,
            title=title,
            filename=filename,
            stored_name=stored_name,
            content_type=content_type,
            size=size,
            indexed=indexed,
        )
    if indexed:
        submit_ingest(document_id)
    return payload


class UploadInit(BaseModel):
    game_id: str = Field(min_length=1)
    role: str = "core"
    title: str = Field(default="", max_length=200)
    campaign_id: str | None = None
    scenario_id: str | None = None
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    content_type: str = "application/octet-stream"


@router.post("/uploads", status_code=201, dependencies=[Depends(require_admin)])
def init_upload(payload: UploadInit):
    """Start a chunked upload.

    Chunking keeps every request small enough to pass proxies with a per-request
    body limit (Cloudflare caps them at 100 MB) while still allowing large books.
    """
    filename = Path(payload.filename).name or "upload"
    ext = resolve_extension(filename)
    if payload.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
        )
    with db() as conn:
        target = _resolve_target(
            conn, payload.game_id, payload.role, payload.campaign_id, payload.scenario_id
        )
    _sweep_uploads()
    upload_id = uuid.uuid4().hex
    meta = {
        "game_id": target.game_id,
        "role": target.role,
        "campaign_id": target.campaign_id,
        "scenario_id": target.scenario_id,
        "title": payload.title.strip()[:200],
        "filename": filename,
        "content_type": payload.content_type or "application/octet-stream",
        "size": payload.size,
        "ext": ext,
        "indexed": is_indexed(filename),
    }
    _upload_meta_path(upload_id).write_text(json.dumps(meta))
    _upload_part_path(upload_id).touch()
    return {
        "upload_id": upload_id,
        "chunk_size": UPLOAD_CHUNK_BYTES,
        "size": payload.size,
    }


@router.put("/uploads/{upload_id}", dependencies=[Depends(require_admin)])
async def upload_chunk(
    upload_id: str, request: Request, offset: int = Query(default=0, ge=0)
):
    """Append one chunk of a chunked upload at the given byte offset."""
    meta = _read_upload(upload_id)
    part = _upload_part_path(upload_id)
    current = part.stat().st_size if part.exists() else 0
    if offset != current:
        raise HTTPException(409, f"Chunk out of order: expected offset {current}.")
    declared = int(meta["size"])
    received = 0
    limit_message = (
        f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
    )
    try:
        with part.open("ab") as handle:
            async for chunk in request.stream():
                received += len(chunk)
                if current + received > declared:
                    raise HTTPException(400, "Upload is larger than the declared size.")
                if current + received > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, limit_message)
                handle.write(chunk)
    except HTTPException:
        with part.open("r+b") as handle:
            handle.truncate(current)
        raise
    return {"received": current + received, "size": declared}


@router.post(
    "/uploads/{upload_id}/complete",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def complete_upload(upload_id: str):
    meta = _read_upload(upload_id)
    part = _upload_part_path(upload_id)
    actual = part.stat().st_size if part.exists() else 0
    declared = int(meta["size"])
    if actual != declared:
        raise HTTPException(
            400, f"Upload incomplete: {actual} of {declared} bytes received."
        )

    filename = meta["filename"]
    indexed = bool(meta["indexed"])
    with db() as conn:
        # Re-validate: the campaign or scenario may have moved during the upload.
        target = _resolve_target(
            conn, meta["game_id"], meta["role"], meta["campaign_id"], meta["scenario_id"]
        )

    document_id = uuid.uuid4().hex
    stored_name = f"{document_id}.{meta['ext']}"
    destination = FILES_DIR / stored_name
    os.replace(part, destination)

    default_title = Path(filename).stem
    title = (meta["title"] or default_title).strip()[:200] or default_title
    try:
        with db() as conn:
            payload = _insert_document(
                conn,
                document_id=document_id,
                target=target,
                title=title,
                filename=filename,
                stored_name=stored_name,
                content_type=meta["content_type"],
                size=actual,
                indexed=indexed,
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    _clear_upload(upload_id)
    if indexed:
        submit_ingest(document_id)
    return payload


@router.delete("/uploads/{upload_id}", dependencies=[Depends(require_admin)])
def cancel_upload(upload_id: str):
    _read_upload(upload_id)
    _clear_upload(upload_id)
    return {"deleted": True}


@router.post("/{document_id}/ocr", dependencies=[Depends(require_admin)])
def ocr_document(document_id: str):
    """Queue OCR for one document, replacing its index with recognised text."""
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        if not ocr_supported(row["original_filename"]):
            raise HTTPException(400, "This file type cannot be OCR'd.")
        if not ocr_available():
            raise HTTPException(
                400, "OCR is not available in this build. Install Tesseract and restart."
            )
        conn.execute(
            "UPDATE documents SET status = 'pending', error = NULL, ocr_requested = 1 "
            "WHERE id = ?",
            (document_id,),
        )
    submit_ingest(document_id)
    return {"status": "pending"}


@router.get("/{document_id}/thumbnail")
def document_thumbnail(document_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Document not found.")
    path = ensure_thumbnail(row)
    if not path or not path.exists():
        raise HTTPException(404, "No thumbnail available.")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/{document_id}")
def get_document(document_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT d.*, c.title AS campaign_title FROM documents d "
            "LEFT JOIN campaigns c ON c.id = d.campaign_id WHERE d.id = ?",
            (document_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        return _doc_payload(conn, row, get_setting(conn, "embedding_model"))


@router.patch("/{document_id}", dependencies=[Depends(require_admin)])
def update_document(document_id: str, payload: DocumentUpdate):
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")

        raw = payload.model_dump(exclude_unset=True)
        campaign_supplied = "campaign_id" in raw
        campaign_value = raw.pop("campaign_id", None)
        scenario_supplied = "scenario_id" in raw
        scenario_value = raw.pop("scenario_id", None)
        fields = {key: value for key, value in raw.items() if value is not None}
        target_role = fields.get("role", row["role"])
        file_count = conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE scenario_id = ?", (document_id,)
        ).fetchone()["n"]

        if "role" in fields:
            valid = {r["id"] for r in _roles_for(conn, row["game_id"])}
            if fields["role"] not in valid:
                raise HTTPException(400, f"Role '{fields['role']}' is not valid for this game.")
            if file_count and fields["role"] != "campaign":
                raise HTTPException(
                    400,
                    "This scenario has attached files; remove them before moving it out of "
                    "Campaigns.",
                )
            conn.execute(
                "UPDATE chunks SET role = ? WHERE document_id = ?",
                (fields["role"], document_id),
            )
            if target_role != "campaign":
                conn.execute(
                    "UPDATE documents SET campaign_id = NULL, scenario_id = NULL WHERE id = ?",
                    (document_id,),
                )
                campaign_supplied = False
                scenario_supplied = False

        if scenario_supplied and scenario_value:
            if target_role != "campaign":
                raise HTTPException(400, "Only campaign documents can belong to a scenario.")
            if file_count:
                raise HTTPException(
                    400,
                    "This scenario already has files; it cannot be attached to another scenario.",
                )
            if scenario_value == document_id:
                raise HTTPException(400, "A scenario cannot contain itself.")
            parent = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (scenario_value,)
            ).fetchone()
            if not parent or parent["game_id"] != row["game_id"]:
                raise HTTPException(400, "Scenario not found for this game.")
            if parent["role"] != "campaign":
                raise HTTPException(400, "Only campaign documents can hold scenario files.")
            if parent["scenario_id"]:
                raise HTTPException(400, "A scenario file cannot hold its own files.")
            conn.execute(
                "UPDATE documents SET scenario_id = ?, campaign_id = ? WHERE id = ?",
                (scenario_value, parent["campaign_id"], document_id),
            )
            campaign_supplied = False
        elif scenario_supplied:
            conn.execute(
                "UPDATE documents SET scenario_id = NULL WHERE id = ?", (document_id,)
            )

        if campaign_supplied:
            if row["scenario_id"] and not scenario_supplied:
                raise HTTPException(
                    400, "This file belongs to a scenario; move the whole scenario instead."
                )
            if campaign_value:
                if target_role != "campaign":
                    raise HTTPException(400, "Only campaign documents can belong to a campaign.")
                campaign = conn.execute(
                    "SELECT 1 FROM campaigns WHERE id = ? AND game_id = ?",
                    (campaign_value, row["game_id"]),
                ).fetchone()
                if not campaign:
                    raise HTTPException(400, "Campaign not found for this game.")
            conn.execute(
                "UPDATE documents SET campaign_id = ? WHERE id = ?",
                (campaign_value or None, document_id),
            )
            if file_count:
                conn.execute(
                    "UPDATE documents SET campaign_id = ? WHERE scenario_id = ?",
                    (campaign_value or None, document_id),
                )

        if "title" in fields:
            fields["title"] = fields["title"].strip()
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(
                f"UPDATE documents SET {assignments} WHERE id = ?",
                [*fields.values(), document_id],
            )
        row = conn.execute(
            "SELECT d.*, c.title AS campaign_title FROM documents d "
            "LEFT JOIN campaigns c ON c.id = d.campaign_id WHERE d.id = ?",
            (document_id,),
        ).fetchone()
        return _doc_payload(conn, row, get_setting(conn, "embedding_model"))


@router.delete("/{document_id}", dependencies=[Depends(require_admin)])
def delete_document(document_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        children = conn.execute(
            "SELECT * FROM documents WHERE scenario_id = ?", (document_id,)
        ).fetchall()
        for child in children:
            unindex_document(conn, child["id"])
        unindex_document(conn, document_id)
        conn.execute("DELETE FROM documents WHERE scenario_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    for item in (row, *children):
        if item["stored_name"]:
            (FILES_DIR / item["stored_name"]).unlink(missing_ok=True)
        delete_thumbnail(item["id"])
    return {"deleted": True, "files_deleted": len(children)}


@router.post("/{document_id}/reindex", dependencies=[Depends(require_admin)])
def reindex_document(document_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT id, original_filename FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        if not is_indexed(row["original_filename"]):
            raise HTTPException(
                400,
                "This file type is stored for browsing. Use Run OCR to recognise text in it.",
            )
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
