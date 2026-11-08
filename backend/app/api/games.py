"""Game library API."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_admin
from app.config import FILES_DIR
from app.db import db
from app.services.ingest import unindex_document

router = APIRouter(prefix="/api/games", tags=["games"])


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GameCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    game_type: str = "rpg"
    description: str = Field(default="", max_length=4000)


class GameUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    game_type: str | None = None
    description: str | None = Field(default=None, max_length=4000)


def _game_types(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM game_types ORDER BY sort_order, label").fetchall()
    out = {}
    for row in rows:
        out[row["id"]] = {
            "id": row["id"],
            "label": row["label"],
            "description": row["description"],
            "roles": json.loads(row["roles"]),
            "builtin": bool(row["builtin"]),
        }
    return out


def game_payload(conn: sqlite3.Connection, row: sqlite3.Row, types: dict | None = None) -> dict:
    types = types if types is not None else _game_types(conn)
    counts = {
        r["role"]: r["n"]
        for r in conn.execute(
            "SELECT role, COUNT(*) AS n FROM documents WHERE game_id = ? GROUP BY role",
            (row["id"],),
        )
    }
    doc_count = sum(counts.values())
    chunk_row = conn.execute(
        "SELECT COUNT(*) AS n FROM chunks WHERE game_id = ?", (row["id"],)
    ).fetchone()
    return {
        "id": row["id"],
        "title": row["title"],
        "game_type": row["game_type"],
        "type_label": types.get(row["game_type"], {}).get("label", row["game_type"]),
        "description": row["description"],
        "created_at": row["created_at"],
        "document_count": doc_count,
        "documents_by_role": counts,
        "chunk_count": chunk_row["n"] if chunk_row else 0,
    }


@router.get("")
def list_games():
    with db() as conn:
        types = _game_types(conn)
        rows = conn.execute("SELECT * FROM games ORDER BY lower(title)").fetchall()
        games = [game_payload(conn, row, types) for row in rows]
    return {"games": games, "total": len(games)}


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
def create_game(payload: GameCreate):
    with db() as conn:
        types = _game_types(conn)
        if payload.game_type not in types:
            raise HTTPException(400, f"Unknown game type '{payload.game_type}'.")
        game_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO games (id, title, game_type, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (game_id, payload.title.strip(), payload.game_type, payload.description, utcnow()),
        )
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return game_payload(conn, row, types)


@router.get("/{game_id}")
def get_game(game_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Game not found.")
        types = _game_types(conn)
        return {**game_payload(conn, row, types), "type": types.get(row["game_type"])}


@router.patch("/{game_id}", dependencies=[Depends(require_admin)])
def update_game(game_id: str, payload: GameUpdate):
    with db() as conn:
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Game not found.")
        if payload.game_type is not None and payload.game_type not in _game_types(conn):
            raise HTTPException(400, f"Unknown game type '{payload.game_type}'.")
        fields = payload.model_dump(exclude_none=True)
        if "title" in fields:
            fields["title"] = fields["title"].strip()
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(
                f"UPDATE games SET {assignments} WHERE id = ?",
                [*fields.values(), game_id],
            )
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return game_payload(conn, row)


@router.delete("/{game_id}", dependencies=[Depends(require_admin)])
def delete_game(game_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Game not found.")
        docs = conn.execute(
            "SELECT id, stored_name FROM documents WHERE game_id = ?", (game_id,)
        ).fetchall()
        for doc in docs:
            unindex_document(conn, doc["id"])
            stored = FILES_DIR / doc["stored_name"] if doc["stored_name"] else None
            if stored and stored.exists():
                stored.unlink(missing_ok=True)
        conn.execute("DELETE FROM documents WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM campaigns WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
    return {"deleted": True, "documents": len(docs)}
