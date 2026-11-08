"""AI provider configuration CRUD and connectivity tests."""

from __future__ import annotations

import sqlite3
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import db, set_setting, utcnow
from app.providers import ProviderConfig, build_provider, driver_specs, get_driver
from app.providers.base import ProviderError
from app.services.config_store import snapshot_config

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "base_url": row["base_url"],
        "chat_model": row["chat_model"],
        "embed_model": row["embed_model"],
        "enabled": bool(row["enabled"]),
        "builtin": bool(row["builtin"]),
        "docs_url": row["docs_url"],
        "description": row["description"],
        "has_api_key": bool(row["api_key"]),
    }


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(min_length=1, max_length=40)
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=500)
    chat_model: str = Field(default="", max_length=200)
    embed_model: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=400)


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    chat_model: str | None = Field(default=None, max_length=200)
    embed_model: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=400)
    enabled: bool | None = None


@router.get("")
def list_providers():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM providers ORDER BY builtin DESC, lower(name)"
        ).fetchall()
    return {"providers": [_payload(row) for row in rows], "drivers": driver_specs()}


@router.post("", status_code=201)
def create_provider(payload: ProviderCreate):
    spec = get_driver(payload.kind)  # raises 400 for unknown kinds
    if spec.requires_api_key and not payload.api_key:
        # Allowed: the user may add the key later. Just surface the expectation.
        pass
    provider_id = uuid.uuid4().hex
    with db() as conn:
        conn.execute(
            """
            INSERT INTO providers
                (id, name, kind, base_url, api_key, chat_model, embed_model,
                 enabled, builtin, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
            """,
            (
                provider_id,
                payload.name.strip(),
                payload.kind,
                payload.base_url.strip(),
                payload.api_key.strip(),
                payload.chat_model.strip(),
                payload.embed_model.strip(),
                payload.description.strip(),
                utcnow(),
            ),
        )
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        payload = _payload(row)
    snapshot_config()
    return payload


@router.patch("/{provider_id}")
def update_provider(provider_id: str, payload: ProviderUpdate):
    with db() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Provider not found.")

        fields = payload.model_dump(exclude_unset=True)
        if "enabled" in fields and fields["enabled"] is not None:
            fields["enabled"] = 1 if fields["enabled"] else 0
        if "api_key" in fields and fields["api_key"] is None:
            fields.pop("api_key")
        for key in ("name", "base_url", "chat_model", "embed_model", "description", "api_key"):
            if key in fields and isinstance(fields[key], str):
                fields[key] = fields[key].strip()

        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(
                f"UPDATE providers SET {assignments} WHERE id = ?",
                [*fields.values(), provider_id],
            )

        # Keep the global defaults pointing at something that exists.
        if "enabled" in fields and not fields["enabled"]:
            if get_setting_provider(conn, "default_chat_provider") == provider_id:
                set_setting(conn, "default_chat_provider", "")
            if get_setting_provider(conn, "embedding_provider") == provider_id:
                set_setting(conn, "embedding_provider", "")
                set_setting(conn, "embedding_model", "")
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        payload = _payload(row)
    snapshot_config()
    return payload


def get_setting_provider(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


@router.delete("/{provider_id}")
def delete_provider(provider_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Provider not found.")
        if row["builtin"]:
            raise HTTPException(
                400,
                "Built-in providers can be disabled but not removed. "
                "Switch off 'Enabled' instead.",
            )
        if get_setting_provider(conn, "default_chat_provider") == provider_id:
            set_setting(conn, "default_chat_provider", "")
        if get_setting_provider(conn, "embedding_provider") == provider_id:
            set_setting(conn, "embedding_provider", "")
            set_setting(conn, "embedding_model", "")
        conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
    snapshot_config()
    return {"deleted": True}


def _provider_for(conn: sqlite3.Connection, provider_id: str):
    row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Provider not found.")
    return build_provider(ProviderConfig.from_row(row))


@router.get("/{provider_id}/models")
def provider_models(provider_id: str):
    with db() as conn:
        provider = _provider_for(conn, provider_id)
    try:
        models = provider.list_models()
    except ProviderError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return {"models": [{"id": m.id, "kind": m.kind} for m in models], "count": len(models)}


@router.post("/{provider_id}/test")
def test_provider(provider_id: str):
    with db() as conn:
        provider = _provider_for(conn, provider_id)
    try:
        message = provider.test()
    except ProviderError as exc:
        return {"ok": False, "message": exc.message}
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": message}
