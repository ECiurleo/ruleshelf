"""Health, settings, game types, stats and background jobs."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.config import (
    APP_NAME,
    APP_VERSION,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DATA_DIR,
    MAX_UPLOAD_BYTES,
)
from app.db import all_settings, db, get_setting, set_setting
from app.extractors import supported_extensions
from app.providers.base import ProviderError
from app.services.embeddings import resolve_embedding
from app.services.ingest import create_embed_job

router = APIRouter(prefix="/api", tags=["meta"])

EDITABLE_SETTINGS = {
    "default_chat_provider",
    "default_chat_model",
    "embedding_provider",
    "embedding_model",
    "rag_top_k",
    "rag_temperature",
    "system_prompt",
}


@router.get("/health")
def health():
    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION}


@router.get("/stats")
def stats():
    with db() as conn:
        def count(sql: str, params: tuple = ()) -> int:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0

        model = get_setting(conn, "embedding_model")
        by_status = {
            row["status"]: row["n"]
            for row in conn.execute("SELECT status, COUNT(*) AS n FROM documents GROUP BY status")
        }
        return {
            "games": count("SELECT COUNT(*) FROM games"),
            "documents": count("SELECT COUNT(*) FROM documents"),
            "chunks": count("SELECT COUNT(*) FROM chunks"),
            "embedded_chunks": count(
                "SELECT COUNT(*) FROM embeddings WHERE model = ?", (model,)
            ) if model else 0,
            "documents_by_status": by_status,
            "formats": len(supported_extensions()),
            "data_dir": str(DATA_DIR),
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsUpdate(BaseModel):
    default_chat_provider: str | None = None
    default_chat_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    rag_top_k: int | None = Field(default=None, ge=1, le=30)
    rag_temperature: float | None = Field(default=None, ge=0, le=2)
    system_prompt: str | None = Field(default=None, max_length=8000)


def _settings_payload(conn: sqlite3.Connection) -> dict:
    settings = all_settings(conn)
    provider_names = {
        row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM providers")
    }
    embedding_provider = settings.get("embedding_provider", "")
    embedding_model = settings.get("embedding_model", "")
    if embedding_provider and embedding_model:
        try:
            resolve_embedding(conn)
            embedding_ready, embedding_error = True, None
        except ProviderError as exc:
            embedding_ready, embedding_error = False, exc.message
    else:
        embedding_ready, embedding_error = False, "No embedding provider selected."
    return {
        "settings": settings,
        "info": {
            "app_name": APP_NAME,
            "version": APP_VERSION,
            "data_dir": str(DATA_DIR),
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "formats": supported_extensions(),
            "embedding_ready": embedding_ready,
            "embedding_error": embedding_error,
            "embedding_model_active": embedding_model,
            "provider_names": provider_names,
        },
    }


@router.get("/settings")
def get_settings():
    with db() as conn:
        return _settings_payload(conn)


@router.put("/settings")
def update_settings(payload: SettingsUpdate):
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    with db() as conn:
        for key, value in values.items():
            if key not in EDITABLE_SETTINGS:
                continue
            if key in {"default_chat_provider", "embedding_provider"} and value:
                exists = conn.execute(
                    "SELECT 1 FROM providers WHERE id = ? AND enabled = 1", (value,)
                ).fetchone()
                if not exists:
                    raise HTTPException(400, f"Provider '{value}' is not available.")
            set_setting(conn, key, str(value))
            if key == "embedding_provider":
                # Clear a stale model from a previous provider.
                row = conn.execute(
                    "SELECT embed_model FROM providers WHERE id = ?", (value,)
                ).fetchone()
                if row and row["embed_model"]:
                    set_setting(conn, "embedding_model", row["embed_model"])
                else:
                    set_setting(conn, "embedding_model", "")
        return _settings_payload(conn)


# ---------------------------------------------------------------------------
# Game types
# ---------------------------------------------------------------------------
class RoleDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)

    @field_validator("id")
    @classmethod
    def slug(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_")
        if not cleaned.replace("_", "").isalnum():
            raise ValueError("Role id must be alphanumeric.")
        return cleaned


class GameTypeCreate(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    roles: list[RoleDefinition] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def slug(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_")
        if not cleaned.replace("_", "").isalnum():
            raise ValueError("Type id must be alphanumeric.")
        return cleaned


@router.get("/game-types")
def list_game_types():
    with db() as conn:
        rows = conn.execute("SELECT * FROM game_types ORDER BY sort_order, label").fetchall()
        counts = {
            row["game_type"]: row["n"]
            for row in conn.execute("SELECT game_type, COUNT(*) AS n FROM games GROUP BY game_type")
        }
        return {
            "game_types": [
                {
                    "id": row["id"],
                    "label": row["label"],
                    "description": row["description"],
                    "roles": json.loads(row["roles"]),
                    "builtin": bool(row["builtin"]),
                    "game_count": counts.get(row["id"], 0),
                }
                for row in rows
            ]
        }


@router.post("/game-types", status_code=201)
def create_game_type(payload: GameTypeCreate):
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM game_types WHERE id = ?", (payload.id,)).fetchone()
        if exists:
            raise HTTPException(409, f"Game type '{payload.id}' already exists.")
        conn.execute(
            "INSERT INTO game_types (id, label, description, roles, builtin, sort_order) "
            "VALUES (?, ?, ?, ?, 0, 100)",
            (
                payload.id,
                payload.label.strip(),
                payload.description.strip(),
                json.dumps([role.model_dump() for role in payload.roles]),
            ),
        )
        return {**payload.model_dump(), "builtin": False, "game_count": 0}


@router.delete("/game-types/{type_id}")
def delete_game_type(type_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM game_types WHERE id = ?", (type_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Game type not found.")
        if row["builtin"]:
            raise HTTPException(400, "Built-in game types cannot be deleted.")
        used = conn.execute(
            "SELECT COUNT(*) AS n FROM games WHERE game_type = ?", (type_id,)
        ).fetchone()["n"]
        if used:
            raise HTTPException(400, f"{used} game(s) still use this type.")
        conn.execute("DELETE FROM game_types WHERE id = ?", (type_id,))
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Embedding jobs
# ---------------------------------------------------------------------------
class EmbedRequest(BaseModel):
    game_id: str | None = None
    force: bool = False


@router.post("/embeddings/build", status_code=202)
def build_embeddings(payload: EmbedRequest):
    with db() as conn:
        try:
            resolve_embedding(conn)
        except ProviderError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        if payload.game_id:
            exists = conn.execute(
                "SELECT 1 FROM games WHERE id = ?", (payload.game_id,)
            ).fetchone()
            if not exists:
                raise HTTPException(404, "Game not found.")
    job_id = create_embed_job(payload.game_id, payload.force)
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job not found.")
        return {
            "id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "progress": row["progress"],
            "message": row["message"],
            "result": row["result"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


@router.get("/formats")
def formats():
    return {"formats": supported_extensions()}
