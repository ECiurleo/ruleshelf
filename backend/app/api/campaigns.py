"""Campaign groups: a named container for campaign stages/documents."""

from __future__ import annotations

import sqlite3
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import db, utcnow

router = APIRouter(prefix="/api", tags=["campaigns"])


class CampaignCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    sort_order: int | None = None


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = None


def _payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "game_id": row["game_id"],
        "title": row["title"],
        "description": row["description"],
        "sort_order": row["sort_order"],
        "document_count": row["document_count"] if "document_count" in row.keys() else 0,
        "created_at": row["created_at"],
    }


def _require_game(conn: sqlite3.Connection, game_id: str) -> None:
    if not conn.execute("SELECT 1 FROM games WHERE id = ?", (game_id,)).fetchone():
        raise HTTPException(404, "Game not found.")


def _campaign_rows(conn: sqlite3.Connection, game_id: str):
    return conn.execute(
        """
        SELECT c.*, COUNT(d.id) AS document_count
        FROM campaigns c
        LEFT JOIN documents d ON d.campaign_id = c.id
        WHERE c.game_id = ?
        GROUP BY c.id
        ORDER BY c.sort_order, lower(c.title)
        """,
        (game_id,),
    ).fetchall()


@router.get("/games/{game_id}/campaigns")
def list_campaigns(game_id: str):
    with db() as conn:
        _require_game(conn, game_id)
        rows = _campaign_rows(conn, game_id)
        return {"campaigns": [_payload(row) for row in rows], "total": len(rows)}


@router.post("/games/{game_id}/campaigns", status_code=201)
def create_campaign(game_id: str, payload: CampaignCreate):
    with db() as conn:
        _require_game(conn, game_id)
        sort_order = payload.sort_order
        if sort_order is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM campaigns WHERE game_id = ?",
                (game_id,),
            ).fetchone()
            sort_order = row["n"] if row else 0
        campaign_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO campaigns (id, game_id, title, description, sort_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                game_id,
                payload.title.strip(),
                payload.description.strip(),
                sort_order,
                utcnow(),
            ),
        )
        row = conn.execute(
            """
            SELECT c.*, 0 AS document_count FROM campaigns c WHERE c.id = ?
            """,
            (campaign_id,),
        ).fetchone()
        return _payload(row)


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, payload: CampaignUpdate):
    with db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Campaign not found.")
        fields = payload.model_dump(exclude_none=True)
        if "title" in fields:
            fields["title"] = fields["title"].strip()
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(
                f"UPDATE campaigns SET {assignments} WHERE id = ?",
                [*fields.values(), campaign_id],
            )
        rows = _campaign_rows(conn, row["game_id"])
        updated = next((item for item in rows if item["id"] == campaign_id), None)
        return _payload(updated) if updated else {"id": campaign_id}


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Campaign not found.")
        ungrouped = conn.execute(
            "UPDATE documents SET campaign_id = NULL WHERE campaign_id = ?", (campaign_id,)
        ).rowcount
        conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    return {"deleted": True, "ungrouped": ungrouped}
