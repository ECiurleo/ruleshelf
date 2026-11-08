"""Durable, human-readable configuration snapshot.

Settings, AI providers and custom game types live in ``/data/config.json``.
The file is written atomically after every change and re-applied on startup, so
editing it (then restarting) or restoring it is enough to recover the exact
configuration. Uploaded files, thumbnails and the library index remain in the
same data folder.
"""

from __future__ import annotations

import json
import logging
import os

from app.config import DATA_DIR
from app.db import all_settings, db, set_setting, utcnow

log = logging.getLogger(__name__)

CONFIG_PATH = DATA_DIR / "config.json"


def _provider_payload(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "base_url": row["base_url"],
        "api_key": row["api_key"],
        "chat_model": row["chat_model"],
        "embed_model": row["embed_model"],
        "enabled": row["enabled"],
        "builtin": row["builtin"],
        "docs_url": row["docs_url"],
        "description": row["description"],
        "created_at": row["created_at"],
    }


def _game_type_payload(row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "description": row["description"],
        "roles": json.loads(row["roles"]),
        "builtin": row["builtin"],
        "sort_order": row["sort_order"],
    }


def snapshot_config() -> None:
    """Write the current configuration to /data/config.json (mode 0600)."""
    with db() as conn:
        payload = {
            "version": 1,
            "saved_at": utcnow(),
            "settings": all_settings(conn),
            "providers": [
                _provider_payload(row)
                for row in conn.execute("SELECT * FROM providers ORDER BY id")
            ],
            "game_types": [
                _game_type_payload(row)
                for row in conn.execute("SELECT * FROM game_types ORDER BY sort_order, id")
            ],
        }

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_name("config.json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, CONFIG_PATH)
    log.info("Configuration saved to %s", CONFIG_PATH)


def apply_config_file() -> bool:
    """Re-apply /data/config.json over the database. Returns True if applied."""
    if not CONFIG_PATH.exists():
        return False
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - never block startup
        log.error("Ignoring unreadable config file %s: %s", CONFIG_PATH, exc)
        return False

    settings = payload.get("settings")
    providers = payload.get("providers")
    game_types = payload.get("game_types")
    if not isinstance(settings, dict) and not isinstance(providers, list):
        log.error("Ignoring config file %s: no settings or providers", CONFIG_PATH)
        return False

    with db() as conn:
        for key, value in (settings or {}).items():
            if isinstance(key, str):
                set_setting(conn, key, str(value))

        for provider in providers or []:
            if not isinstance(provider, dict) or not provider.get("id"):
                continue
            conn.execute(
                """
                INSERT INTO providers
                    (id, name, kind, base_url, api_key, chat_model, embed_model,
                     enabled, builtin, docs_url, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    base_url = excluded.base_url,
                    api_key = excluded.api_key,
                    chat_model = excluded.chat_model,
                    embed_model = excluded.embed_model,
                    enabled = excluded.enabled,
                    builtin = excluded.builtin,
                    docs_url = excluded.docs_url,
                    description = excluded.description
                """,
                (
                    str(provider["id"]),
                    provider.get("name") or provider["id"],
                    provider.get("kind") or "openai_compat",
                    provider.get("base_url") or "",
                    provider.get("api_key") or "",
                    provider.get("chat_model") or "",
                    provider.get("embed_model") or "",
                    int(provider.get("enabled", 1)),
                    int(provider.get("builtin", 0)),
                    provider.get("docs_url") or "",
                    provider.get("description") or "",
                    provider.get("created_at") or utcnow(),
                ),
            )

        for game_type in game_types or []:
            if not isinstance(game_type, dict) or not game_type.get("id"):
                continue
            if game_type.get("builtin"):
                continue
            roles = game_type.get("roles") or []
            conn.execute(
                """
                INSERT INTO game_types (id, label, description, roles, builtin, sort_order)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                    label = excluded.label,
                    description = excluded.description,
                    roles = excluded.roles
                """,
                (
                    str(game_type["id"]),
                    game_type.get("label") or game_type["id"],
                    game_type.get("description") or "",
                    json.dumps(roles),
                    int(game_type.get("sort_order", 100)),
                ),
            )

    log.info("Configuration restored from %s", CONFIG_PATH)
    return True
