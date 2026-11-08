"""Test configuration: isolate the data directory before importing the app."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

# config.py resolves paths at import time, so this must happen first.
_TEST_DIR = Path(tempfile.mkdtemp(prefix="ruleshelf-tests-"))
os.environ["RULESHELF_DATA_DIR"] = str(_TEST_DIR)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import FILES_DIR, THUMBNAILS_DIR  # noqa: E402
from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.config_store import CONFIG_PATH  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    init_db()
    yield
    shutil.rmtree(_TEST_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_library():
    with db() as conn:
        conn.execute("DELETE FROM embeddings")
        conn.execute("DELETE FROM chunks_fts")
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM documents")
        conn.execute("DELETE FROM campaigns")
        conn.execute("DELETE FROM games")
        conn.execute("DELETE FROM jobs")
    for path in FILES_DIR.glob("*"):
        path.unlink(missing_ok=True)
    for path in THUMBNAILS_DIR.glob("*"):
        path.unlink(missing_ok=True)
    CONFIG_PATH.unlink(missing_ok=True)
    init_db()  # re-seed built-in providers/types if a test deleted them
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def game(client):
    response = client.post(
        "/api/games",
        json={"title": "Test Game", "game_type": "rpg", "description": ""},
    )
    assert response.status_code == 201
    return response.json()


SAMPLE_PAGES = [
    "Combat basics. A charge reaction is declared when an enemy completes a charge move. "
    "The defender may hold, stand and shoot, or flee. Holding grants one point of advantage.",
    "Magic. When a wizard rolls a double on a casting test, roll on the miscast table. "
    "A result of seven or more opens a rift and the wizard gains a mutation.",
    "The Imperial Zoo of Altdorf houses griffons and demigryphs. Animal handling is required "
    "to calm a beast. The zoo keeper will pay fifty gold crowns for a live specimen.",
]


def make_text_document(pages: list[str] | None = None) -> bytes:
    return "\f".join(pages or SAMPLE_PAGES).encode("utf-8")


def upload_document(
    client,
    game_id: str,
    *,
    role: str = "core",
    title: str = "Core Rules",
    campaign_id: str | None = None,
):
    data = {"game_id": game_id, "role": role, "title": title}
    if campaign_id:
        data["campaign_id"] = campaign_id
    response = client.post(
        "/api/documents",
        data=data,
        files={"file": (f"{uuid.uuid4().hex}.txt", make_text_document(), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def wait_until_ready(client, document_id: str, timeout: float = 10.0) -> dict:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/documents/{document_id}").json()
        if payload["status"] in {"ready", "error"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("document did not finish indexing in time")
