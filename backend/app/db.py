"""SQLite access and schema migrations.

The database is a plain file under the data directory. WAL mode + a per-call
connection keeps things simple and safe for the low concurrency of a personal
server. FTS5 provides keyword search; embeddings live in a BLOB table.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app.config import DB_PATH, FILES_DIR
from app.defaults import BUILTIN_PROVIDERS, DEFAULT_SYSTEM_PROMPT, GAME_TYPES

log = logging.getLogger(__name__)

SCHEMA_VERSION = 6

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS games (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    game_type   TEXT NOT NULL DEFAULT 'rpg',
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_types (
    id          TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    roles       TEXT NOT NULL,
    builtin     INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS documents (
    id                TEXT PRIMARY KEY,
    game_id           TEXT NOT NULL,
    title             TEXT NOT NULL,
    role              TEXT NOT NULL DEFAULT 'core',
    campaign_id       TEXT,
    scenario_id       TEXT,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    original_filename TEXT NOT NULL DEFAULT '',
    stored_name       TEXT NOT NULL DEFAULT '',
    content_type      TEXT NOT NULL DEFAULT '',
    size_bytes        INTEGER NOT NULL DEFAULT 0,
    page_count        INTEGER NOT NULL DEFAULT 0,
    chunk_count       INTEGER NOT NULL DEFAULT 0,
    ocr_requested     INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'pending',
    error             TEXT,
    created_at        TEXT NOT NULL,
    indexed_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_game ON documents(game_id);
CREATE INDEX IF NOT EXISTS idx_documents_campaign ON documents(campaign_id);
CREATE INDEX IF NOT EXISTS idx_documents_scenario ON documents(scenario_id);

CREATE TABLE IF NOT EXISTS campaigns (
    id          TEXT PRIMARY KEY,
    game_id     TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaigns_game ON campaigns(game_id);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    game_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    page_start  INTEGER,
    page_end    INTEGER,
    ordinal     INTEGER NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_game ON chunks(game_id);
CREATE INDEX IF NOT EXISTS idx_chunks_game_role ON chunks(game_id, role);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER NOT NULL,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL,
    vector   BLOB NOT NULL,
    PRIMARY KEY (chunk_id, model)
);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model);

CREATE TABLE IF NOT EXISTS providers (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    base_url     TEXT NOT NULL DEFAULT '',
    api_key      TEXT NOT NULL DEFAULT '',
    chat_model   TEXT NOT NULL DEFAULT '',
    embed_model  TEXT NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1,
    builtin      INTEGER NOT NULL DEFAULT 0,
    docs_url     TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'running',
    progress   REAL NOT NULL DEFAULT 0,
    message    TEXT NOT NULL DEFAULT '',
    result     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "default_chat_provider": "ollama",
    "default_chat_model": "",
    "embedding_provider": "",
    "embedding_model": "",
    "rag_top_k": "10",
    "rag_temperature": "0.1",
    "auto_ocr": "1",
    "ocr_language": "eng",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create/upgrade the schema and seed built-ins (idempotent)."""
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            log.info("Creating database schema v1")
            conn.executescript(SCHEMA_V1)
            version = SCHEMA_VERSION

        if version < 3:
            log.info("Migrating database to schema v3 (campaigns)")
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(documents)")
            }
            if "campaign_id" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN campaign_id TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    id          TEXT PRIMARY KEY,
                    game_id     TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_game ON campaigns(game_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_campaign ON documents(campaign_id)"
            )
            version = 3

        if version < 4:
            log.info("Migrating database to schema v4 (users and sessions)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            TEXT PRIMARY KEY,
                    email         TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'viewer',
                    active        INTEGER NOT NULL DEFAULT 1,
                    created_at    TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id    TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
            )
            version = 4

        if version < 5:
            log.info("Migrating database to schema v5 (scenario files)")
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(documents)")
            }
            if "scenario_id" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN scenario_id TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_scenario ON documents(scenario_id)"
            )
            version = 5

        if version < 6:
            log.info("Migrating database to schema v6 (OCR requests)")
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(documents)")
            }
            if "ocr_requested" not in columns:
                conn.execute(
                    "ALTER TABLE documents ADD COLUMN ocr_requested INTEGER NOT NULL DEFAULT 0"
                )
            version = 6

        conn.execute(f"PRAGMA user_version = {version}")
        _seed(conn)


def _seed(conn: sqlite3.Connection) -> None:
    for order, gt in enumerate(GAME_TYPES):
        conn.execute(
            """
            INSERT INTO game_types (id, label, description, roles, builtin, sort_order)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                label = excluded.label,
                description = excluded.description,
                roles = excluded.roles
            WHERE game_types.builtin = 1
            """,
            (
                gt["id"],
                gt["label"],
                gt["description"],
                json.dumps(gt["roles"]),
                gt.get("sort_order", order * 10),
            ),
        )

    for p in BUILTIN_PROVIDERS:
        conn.execute(
            """
            INSERT INTO providers
                (id, name, kind, base_url, chat_model, embed_model, builtin,
                 docs_url, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                docs_url = excluded.docs_url,
                description = excluded.description
            WHERE providers.builtin = 1
            """,
            (
                p["id"],
                p["name"],
                p["kind"],
                p["base_url"],
                p["chat_model"],
                p["embed_model"],
                p.get("docs_url", ""),
                p.get("description", ""),
                utcnow(),
            ),
        )

    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
            (key, value),
        )


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------
def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
