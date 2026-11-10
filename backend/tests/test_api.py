"""API integration tests covering the core library workflow."""

from __future__ import annotations

import numpy as np
import pytest

from app.config import UPLOADS_DIR
from app.db import db, get_setting, set_setting
from app.extractors.base import ExtractedPage
from app.providers.base import ModelInfo, Provider, ProviderConfig
from app.services.ocr import ocr_available
from app.services.search import SearchFilters, search_semantic
from tests.conftest import make_text_document, upload_document, wait_until_ready


def test_api_requires_login(anon_client):
    assert anon_client.get("/api/games").status_code == 401
    assert anon_client.get("/api/health").status_code == 200


def test_login_logout(anon_client):
    response = anon_client.post(
        "/api/auth/login",
        json={"email": "admin@ruleshelf.test", "password": "testadmin123"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert anon_client.get("/api/auth/me").status_code == 200
    assert anon_client.post("/api/auth/logout").status_code == 200
    assert anon_client.get("/api/auth/me").status_code == 401


def test_viewer_can_read_but_not_write(client, viewer_client, game):
    assert viewer_client.get("/api/games").status_code == 200
    assert viewer_client.get("/api/providers").status_code == 403
    assert (
        viewer_client.post(
            "/api/games",
            json={"title": "Blocked", "game_type": "rpg", "description": ""},
        ).status_code
        == 403
    )
    assert viewer_client.get("/api/search", params={"q": "combat"}).status_code == 200
    assert viewer_client.put("/api/settings", json={"rag_top_k": 3}).status_code == 403
    assert client.get("/api/games").status_code == 200


def test_user_management_and_protection(client):
    created = client.post(
        "/api/users",
        json={
            "email": "newviewer@ruleshelf.test",
            "password": "newviewer123",
            "role": "viewer",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    listed = client.get("/api/users").json()["users"]
    assert any(user["email"] == "newviewer@ruleshelf.test" for user in listed)

    promoted = client.patch(f"/api/users/{user_id}", json={"role": "admin"}).json()
    assert promoted["role"] == "admin"
    demoted = client.patch(f"/api/users/{user_id}", json={"role": "viewer"}).json()
    assert demoted["role"] == "viewer"

    assert client.delete(f"/api/users/{user_id}").json()["deleted"] is True

    me = client.get("/api/auth/me").json()["user"]
    assert client.delete(f"/api/users/{me['id']}").status_code == 400
    assert client.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 400


def test_change_own_password(client):
    response = client.post(
        "/api/auth/password",
        json={"current_password": "testadmin123", "new_password": "newadmin123"},
    )
    assert response.status_code == 200, response.text
    # Restore the fixture password for the rest of the suite.
    client.post(
        "/api/auth/password",
        json={"current_password": "newadmin123", "new_password": "testadmin123"},
    )


def test_create_and_list_game(client, game):
    listing = client.get("/api/games").json()
    assert listing["total"] == 1
    assert listing["games"][0]["title"] == "Test Game"
    assert listing["games"][0]["game_type"] == "rpg"

    types = {item["id"] for item in client.get("/api/game-types").json()["game_types"]}
    assert {"rpg", "boardgame", "wargame"} <= types


def test_upload_index_and_search(client, game):
    document = upload_document(client, game["id"])
    ready = wait_until_ready(client, document["id"])
    assert ready["status"] == "ready", ready
    assert ready["chunk_count"] >= 3
    assert ready["page_count"] == 3

    response = client.get("/api/search", params={"q": "miscast table", "mode": "keyword"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    top = payload["results"][0]
    assert top["page_start"] == 2
    assert "mark" in top["snippet"]
    assert top["document"]["role"] == "core"
    assert top["game"]["id"] == game["id"]


def test_search_scope_and_role_filters(client, game):
    document = upload_document(client, game["id"], role="campaign", title="The Enemy Within")
    wait_until_ready(client, document["id"])
    core = upload_document(client, game["id"], role="core", title="Core")
    wait_until_ready(client, core["id"])

    campaign_only = client.get(
        "/api/search", params={"q": "miscast", "mode": "keyword", "roles": "campaign"}
    ).json()
    assert campaign_only["count"] == 1
    assert campaign_only["results"][0]["document"]["role"] == "campaign"

    other_game = client.post(
        "/api/games", json={"title": "Other", "game_type": "boardgame", "description": ""}
    ).json()
    document2 = upload_document(client, other_game["id"], role="core", title="Other core")
    wait_until_ready(client, document2["id"])

    all_results = client.get("/api/search", params={"q": "miscast", "mode": "keyword"}).json()
    scoped = client.get(
        "/api/search",
        params={"q": "miscast", "mode": "keyword", "game_id": game["id"]},
    ).json()
    assert all_results["count"] == 3
    assert scoped["count"] == 2


def test_semantic_search_ranks_nearest_neighbour(client, game):
    document = upload_document(client, game["id"])
    wait_until_ready(client, document["id"])

    with db() as conn:
        chunk = conn.execute(
            "SELECT id FROM chunks WHERE document_id = ? ORDER BY id", (document["id"],)
        ).fetchone()
        other = conn.execute(
            "SELECT id FROM chunks WHERE document_id = ? ORDER BY id DESC", (document["id"],)
        ).fetchone()
        conn.execute(
            "INSERT INTO embeddings (chunk_id, model, dim, vector) VALUES (?, 'test-model', 3, ?)",
            (chunk["id"], np.asarray([1.0, 0.0, 0.0], dtype=np.float32).tobytes()),
        )
        conn.execute(
            "INSERT INTO embeddings (chunk_id, model, dim, vector) VALUES (?, 'test-model', 3, ?)",
            (other["id"], np.asarray([0.0, 1.0, 0.0], dtype=np.float32).tobytes()),
        )

    class FakeEmbedder(Provider):
        supports_embeddings = True

        def list_models(self):
            return [ModelInfo(id="test-model", kind="embedding")]

        def embed(self, texts, model):
            return [[1.0, 0.0, 0.0] for _ in texts]

    with db() as conn:
        results = search_semantic(
            conn,
            FakeEmbedder(ProviderConfig(id="fake", name="Fake", kind="fake", base_url="")),
            "test-model",
            "charge",
            SearchFilters(game_id=game["id"]),
            limit=5,
        )
    assert results[0]["chunk_id"] == chunk["id"]


def test_game_delete_cascades(client, game):
    document = upload_document(client, game["id"])
    wait_until_ready(client, document["id"])

    assert client.delete(f"/api/games/{game['id']}").json()["deleted"] is True
    assert client.get("/api/games").json()["total"] == 0
    assert client.get(f"/api/documents/{document['id']}").status_code == 404
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        # FTS rows are removed alongside the chunks.
        assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 0


def test_provider_crud_and_driver_registry(client):
    listing = client.get("/api/providers").json()
    kinds = {driver["kind"] for driver in listing["drivers"]}
    assert {"openai_compat", "anthropic", "ollama"} <= kinds
    assert {provider["id"] for provider in listing["providers"]} >= {
        "openai",
        "anthropic",
        "deepseek",
        "qwen",
        "ollama",
    }

    created = client.post(
        "/api/providers",
        json={
            "name": "Local gateway",
            "kind": "openai_compat",
            "base_url": "http://localhost:1234/v1",
            "api_key": "secret",
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]
    assert created.json()["has_api_key"] is True
    assert "api_key" not in created.json()

    updated = client.patch(
        f"/api/providers/{provider_id}", json={"chat_model": "local-model"}
    ).json()
    assert updated["chat_model"] == "local-model"
    assert client.delete(f"/api/providers/{provider_id}").json()["deleted"] is True

    # Built-ins can be disabled but not deleted.
    assert client.delete("/api/providers/openai").status_code == 400


def test_ask_requires_provider(client, game):
    document = upload_document(client, game["id"])
    wait_until_ready(client, document["id"])

    with db() as conn:
        conn.execute("DELETE FROM providers")
    response = client.post("/api/ask", json={"query": "miscast", "game_id": game["id"]})
    assert response.status_code == 400
    assert "provider" in response.json()["detail"].lower()


def test_config_snapshot_is_written_and_restored(client):
    import json
    import stat

    from app.services.config_store import CONFIG_PATH, apply_config_file

    assert CONFIG_PATH.exists()
    assert stat.S_IMODE(CONFIG_PATH.stat().st_mode) == 0o600
    snapshot = json.loads(CONFIG_PATH.read_text())
    assert "settings" in snapshot
    assert "providers" in snapshot
    assert "game_types" in snapshot

    client.put("/api/settings", json={"rag_top_k": 9})
    snapshot = json.loads(CONFIG_PATH.read_text())
    assert snapshot["settings"]["rag_top_k"] == "9"

    with db() as conn:
        set_setting(conn, "rag_top_k", "2")
    assert apply_config_file() is True
    with db() as conn:
        assert get_setting(conn, "rag_top_k") == "9"


def test_campaign_groups_and_stages(client, game):
    campaign = client.post(
        f"/api/games/{game['id']}/campaigns",
        json={"title": "The Enemy Within"},
    )
    assert campaign.status_code == 201, campaign.text
    campaign_id = campaign.json()["id"]

    stage = upload_document(
        client,
        game["id"],
        role="campaign",
        title="Shadows over Bögenhafen",
        campaign_id=campaign_id,
    )
    ready = wait_until_ready(client, stage["id"])
    assert ready["campaign_id"] == campaign_id
    assert ready["campaign_title"] == "The Enemy Within"

    listing = client.get(f"/api/games/{game['id']}/campaigns").json()
    assert listing["total"] == 1
    assert listing["campaigns"][0]["document_count"] == 1

    # Move the stage out and back.
    cleared = client.patch(f"/api/documents/{stage['id']}", json={"campaign_id": None}).json()
    assert cleared["campaign_id"] is None
    assert client.get(f"/api/games/{game['id']}/campaigns").json()["campaigns"][0][
        "document_count"
    ] == 0

    moved = client.patch(
        f"/api/documents/{stage['id']}",
        json={"campaign_id": campaign_id, "sort_order": 4},
    ).json()
    assert moved["campaign_title"] == "The Enemy Within"
    assert moved["sort_order"] == 4

    # Deleting a campaign ungroups its stages instead of deleting them.
    assert client.delete(f"/api/campaigns/{campaign_id}").json()["ungrouped"] == 1
    still_there = client.get(f"/api/documents/{stage['id']}").json()
    assert still_there["campaign_id"] is None

    # Campaign-only validation.
    other = client.post(
        f"/api/games/{game['id']}/campaigns", json={"title": "Other"}
    ).json()
    response = client.post(
        "/api/documents",
        data={
            "game_id": game["id"],
            "role": "core",
            "title": "Invalid",
            "campaign_id": other["id"],
        },
        files={"file": ("rules.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_scenario_holds_multiple_files(client, game):
    campaign = client.post(
        f"/api/games/{game['id']}/campaigns", json={"title": "The Enemy Within"}
    ).json()

    scenario = upload_document(
        client,
        game["id"],
        role="campaign",
        title="Power Behind the Throne",
        campaign_id=campaign["id"],
    )
    maps = upload_document(
        client,
        game["id"],
        role="campaign",
        title="Endpaper Maps",
        campaign_id=campaign["id"],
        scenario_id=scenario["id"],
    )
    cards = upload_document(
        client,
        game["id"],
        role="campaign",
        title="Cards",
        campaign_id=campaign["id"],
        scenario_id=scenario["id"],
    )
    wait_until_ready(client, scenario["id"])
    wait_until_ready(client, maps["id"])
    ready_cards = wait_until_ready(client, cards["id"])

    parent = client.get(f"/api/documents/{scenario['id']}").json()
    assert parent["file_count"] == 2
    assert parent["scenario_id"] is None
    assert ready_cards["scenario_id"] == scenario["id"]
    assert ready_cards["campaign_id"] == campaign["id"]
    assert ready_cards["role"] == "campaign"
    assert (maps["sort_order"], cards["sort_order"]) == (0, 1)

    # A file belongs to its scenario: it cannot be re-filed on its own.
    assert (
        client.patch(f"/api/documents/{maps['id']}", json={"campaign_id": None}).status_code
        == 400
    )

    # Only top-level campaign documents can hold files.
    core = upload_document(client, game["id"], title="Core")
    invalid = client.post(
        "/api/documents",
        data={"game_id": game["id"], "role": "campaign", "scenario_id": core["id"]},
        files={"file": ("nested.txt", b"nested", "text/plain")},
    )
    assert invalid.status_code == 400
    # ...and a file cannot hold files of its own.
    nested = client.post(
        "/api/documents",
        data={"game_id": game["id"], "role": "campaign", "scenario_id": maps["id"]},
        files={"file": ("nested.txt", b"nested", "text/plain")},
    )
    assert nested.status_code == 400

    # Moving the scenario moves its files with it.
    other = client.post(
        f"/api/games/{game['id']}/campaigns", json={"title": "Other"}
    ).json()
    client.patch(f"/api/documents/{scenario['id']}", json={"campaign_id": other["id"]})
    assert client.get(f"/api/documents/{maps['id']}").json()["campaign_id"] == other["id"]

    # Deleting a scenario deletes its attached files.
    assert client.delete(f"/api/documents/{scenario['id']}").json()["files_deleted"] == 2
    assert client.get(f"/api/documents/{maps['id']}").status_code == 404
    assert client.get(f"/api/documents/{cards['id']}").status_code == 404


def test_campaigns_are_deleted_with_the_game(client, game):
    campaign = client.post(
        f"/api/games/{game['id']}/campaigns", json={"title": "Temp"}
    ).json()
    document = upload_document(
        client, game["id"], role="campaign", title="Stage", campaign_id=campaign["id"]
    )
    wait_until_ready(client, document["id"])
    assert client.delete(f"/api/games/{game['id']}").status_code == 200
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 0


def make_png() -> bytes:
    """A small real PNG so PyMuPDF can read it back for the thumbnail."""
    import pymupdf

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=80, height=100)
        page.draw_rect(page.rect, color=(0.2, 0.3, 0.4), fill=(0.82, 0.72, 0.55))
        return page.get_pixmap().tobytes("png")
    finally:
        doc.close()


def test_image_files_are_stored_but_not_indexed(client, game):
    with db() as conn:
        set_setting(conn, "auto_ocr", "0")
    campaign = client.post(
        f"/api/games/{game['id']}/campaigns", json={"title": "The Enemy Within"}
    ).json()
    scenario = upload_document(
        client,
        game["id"],
        role="campaign",
        title="Power Behind the Throne",
        campaign_id=campaign["id"],
    )
    wait_until_ready(client, scenario["id"])

    image = upload_document(
        client,
        game["id"],
        role="campaign",
        title="Endpaper map",
        campaign_id=campaign["id"],
        scenario_id=scenario["id"],
        content=make_png(),
        filename="endpaper-map.png",
        content_type="image/png",
    )
    assert image["status"] == "unindexed"
    assert image["indexed"] is False
    assert image["chunk_count"] == 0
    assert image["scenario_id"] == scenario["id"]
    assert client.get(f"/api/documents/{scenario['id']}").json()["file_count"] == 1

    # Stored-only files never reach the text index.
    search = client.get(
        "/api/search",
        params={"q": "zzzznothing", "mode": "keyword", "game_id": game["id"]},
    ).json()
    assert search["count"] == 0
    assert client.post(f"/api/documents/{image['id']}/reindex").status_code == 400

    # The image itself becomes the thumbnail.
    thumb = client.get(f"/api/documents/{image['id']}/thumbnail")
    assert thumb.status_code == 200
    assert thumb.content[:3] == b"\xff\xd8\xff"

    # Image formats are advertised as stored-only.
    formats = client.get("/api/formats").json()["formats"]
    image_format = next(item for item in formats if "png" in item["extensions"])
    assert image_format["indexed"] is False

    # Deleting the scenario takes the stored image with it.
    assert client.delete(f"/api/documents/{scenario['id']}").json()["files_deleted"] == 1
    assert client.get(f"/api/documents/{image['id']}").status_code == 404
    with db() as conn:
        set_setting(conn, "auto_ocr", "1")


def test_chunked_upload_reassembles_the_file(client, game):
    campaign = client.post(
        f"/api/games/{game['id']}/campaigns", json={"title": "The Enemy Within"}
    ).json()
    data = make_text_document()
    init = client.post(
        "/api/documents/uploads",
        json={
            "game_id": game["id"],
            "role": "campaign",
            "title": "Death on the Reik",
            "campaign_id": campaign["id"],
            "filename": "death-on-the-reik.txt",
            "size": len(data),
            "content_type": "text/plain",
        },
    )
    assert init.status_code == 201, init.text
    upload = init.json()
    upload_id = upload["upload_id"]
    assert upload["chunk_size"] > 0

    cut = len(data) // 2
    for offset, chunk in ((0, data[:cut]), (cut, data[cut:])):
        response = client.put(
            f"/api/documents/uploads/{upload_id}?offset={offset}",
            content=chunk,
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["received"] == offset + len(chunk)

    done = client.post(f"/api/documents/uploads/{upload_id}/complete")
    assert done.status_code == 201, done.text
    document = done.json()
    assert document["title"] == "Death on the Reik"
    assert document["size_bytes"] == len(data)
    assert document["campaign_title"] == "The Enemy Within"
    ready = wait_until_ready(client, document["id"])
    assert ready["status"] == "ready"
    assert ready["page_count"] == 3
    # Temporary pieces are cleaned up after completion.
    assert not (UPLOADS_DIR / f"{upload_id}.part").exists()
    assert not (UPLOADS_DIR / f"{upload_id}.json").exists()


def test_chunked_upload_checks_offsets_and_size(client, game):
    init = client.post(
        "/api/documents/uploads",
        json={
            "game_id": game["id"],
            "role": "core",
            "filename": "book.txt",
            "size": 10,
        },
    ).json()
    upload_id = init["upload_id"]

    # Out-of-order chunk.
    response = client.put(
        f"/api/documents/uploads/{upload_id}?offset=5", content=b"abc"
    )
    assert response.status_code == 409

    # Finishing before all bytes arrived.
    response = client.put(
        f"/api/documents/uploads/{upload_id}?offset=0", content=b"12345"
    )
    assert response.status_code == 200
    assert client.post(f"/api/documents/uploads/{upload_id}/complete").status_code == 400

    # Cancelling removes the pending upload.
    assert client.delete(f"/api/documents/uploads/{upload_id}").status_code == 200
    assert (
        client.put(f"/api/documents/uploads/{upload_id}?offset=0", content=b"x").status_code
        == 404
    )


def make_blank_pdf() -> bytes:
    """A one-page PDF with vector art but no text layer, like a scanned page."""
    import pymupdf

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=200, height=260)
        page.draw_rect(page.rect, color=(0.1, 0.1, 0.1), fill=(0.9, 0.85, 0.7))
        return doc.tobytes()
    finally:
        doc.close()


def make_scanned_pdf(text: str = "KEMPERBAD DOCKS") -> bytes:
    """A PDF whose only page is a raster image of text — a scan, not a text PDF."""
    import pymupdf

    source = pymupdf.open()
    try:
        page = source.new_page(width=420, height=180)
        page.insert_text((30, 100), text, fontsize=30, fontname="hebo")
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    finally:
        source.close()

    scanned = pymupdf.open()
    try:
        page = scanned.new_page(width=pixmap.width, height=pixmap.height)
        page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        return scanned.tobytes()
    finally:
        scanned.close()


@pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed")
def test_real_ocr_reads_a_scanned_page(client, game):
    document = upload_document(
        client,
        game["id"],
        title="Real scan",
        content=make_scanned_pdf(),
        filename="real-scan.pdf",
        content_type="application/pdf",
    )
    ready = wait_until_ready(client, document["id"], timeout=120)
    assert ready["status"] == "ready", ready["error"]
    assert ready["chunk_count"] >= 1
    hits = client.get(
        "/api/search",
        params={"q": "KEMPERBAD", "mode": "keyword", "game_id": game["id"]},
    ).json()
    assert hits["count"] >= 1


def test_ocr_settings_default_to_on(client):
    info = client.get("/api/settings").json()["info"]
    assert info["auto_ocr"] is True
    assert info["ocr_language"] == "eng"


def test_auto_ocr_indexes_a_scanned_pdf_and_manual_ocr_works(client, game, monkeypatch):
    recognisable = [ExtractedPage(number=1, text="The Reik is wide and cold.")]

    def fake_ocr(path, original_filename=None, language="eng"):
        return recognisable

    monkeypatch.setattr("app.services.ingest.ocr_available", lambda: True)
    monkeypatch.setattr("app.services.ingest.ocr_file", fake_ocr)
    monkeypatch.setattr("app.api.documents.ocr_available", lambda: True)

    scan = make_blank_pdf()
    automatic = upload_document(
        client,
        game["id"],
        title="Scanned chapter",
        content=scan,
        filename="scan.pdf",
        content_type="application/pdf",
    )
    ready = wait_until_ready(client, automatic["id"])
    assert ready["status"] == "ready"
    assert ready["chunk_count"] >= 1
    assert ready["can_ocr"] is True

    # With automatic OCR off, the scan fails until OCR is requested.
    with db() as conn:
        set_setting(conn, "auto_ocr", "0")
    try:
        manual = upload_document(
            client,
            game["id"],
            title="Another scan",
            content=scan,
            filename="scan2.pdf",
            content_type="application/pdf",
        )
        failed = wait_until_ready(client, manual["id"])
        assert failed["status"] == "error"
        assert "No text could be extracted" in (failed["error"] or "")

        assert client.post(f"/api/documents/{manual['id']}/ocr").status_code == 200
        fixed = wait_until_ready(client, manual["id"])
        assert fixed["status"] == "ready"
        assert fixed["chunk_count"] >= 1
    finally:
        with db() as conn:
            set_setting(conn, "auto_ocr", "1")


def test_manual_ocr_turns_a_stored_image_into_a_searchable_document(client, game, monkeypatch):
    monkeypatch.setattr("app.services.ingest.ocr_available", lambda: True)
    monkeypatch.setattr(
        "app.services.ingest.ocr_file",
        lambda path, original_filename=None, language="eng": [
            ExtractedPage(number=1, text="Kemperbad docks and river wards.")
        ],
    )
    monkeypatch.setattr("app.api.documents.ocr_available", lambda: True)

    with db() as conn:
        set_setting(conn, "auto_ocr", "0")
    try:
        image = upload_document(
            client,
            game["id"],
            role="campaign",
            title="River map",
            content=make_png(),
            filename="river-map.png",
            content_type="image/png",
        )
        assert image["status"] == "unindexed"
        assert image["indexed"] is False
        assert image["can_ocr"] is True

        assert client.post(f"/api/documents/{image['id']}/ocr").status_code == 200
        ready = wait_until_ready(client, image["id"])
        assert ready["status"] == "ready"
        assert ready["indexed"] is True
        assert ready["chunk_count"] >= 1
    finally:
        with db() as conn:
            set_setting(conn, "auto_ocr", "1")

    # Plain text is not an OCR candidate.
    text = upload_document(client, game["id"], title="Plain text")
    assert client.post(f"/api/documents/{text['id']}/ocr").status_code == 400


def test_queue_all_failed_documents_for_ocr(client, game, monkeypatch):
    monkeypatch.setattr("app.services.ingest.ocr_available", lambda: True)
    monkeypatch.setattr(
        "app.services.ingest.ocr_file",
        lambda path, original_filename=None, language="eng": [
            ExtractedPage(number=1, text="Recognised by the bulk OCR queue.")
        ],
    )
    monkeypatch.setattr("app.api.documents.ocr_available", lambda: True)

    with db() as conn:
        set_setting(conn, "auto_ocr", "0")
    try:
        scan = make_blank_pdf()
        first = upload_document(
            client, game["id"], title="First scan", content=scan,
            filename="first.pdf", content_type="application/pdf",
        )
        second = upload_document(
            client, game["id"], title="Second scan", content=scan,
            filename="second.pdf", content_type="application/pdf",
        )
        broken = upload_document(
            client, game["id"], title="Empty text", content=b"   ",
            filename="empty.txt", content_type="text/plain",
        )
        for document in (first, second, broken):
            assert wait_until_ready(client, document["id"])["status"] == "error"

        response = client.post(f"/api/documents/ocr-failed?game_id={game['id']}")
        assert response.status_code == 200
        # Only OCR-capable failures are queued; the empty text file is skipped.
        assert response.json() == {"queued": 2}

        for document in (first, second):
            ready = wait_until_ready(client, document["id"])
            assert ready["status"] == "ready"
            assert ready["chunk_count"] >= 1
        assert client.get(f"/api/documents/{broken['id']}").json()["status"] == "error"
    finally:
        with db() as conn:
            set_setting(conn, "auto_ocr", "1")


def test_thumbnail_is_generated_and_removed(client, game):
    document = upload_document(client, game["id"])
    ready = wait_until_ready(client, document["id"])
    assert ready["thumbnail_url"].startswith(f"/api/documents/{document['id']}/thumbnail")

    response = client.get(ready["thumbnail_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"
    assert len(response.content) > 500

    assert client.delete(f"/api/documents/{document['id']}").status_code == 200
    assert client.get(f"/api/documents/{document['id']}/thumbnail").status_code == 404


def test_references_include_document_page_and_link():
    from app.services.rag import references_markdown

    results = [
        {
            "document": {
                "id": "doc1",
                "title": "Core Rules",
                "role_label": "Core rules",
            },
            "game": {"title": "Warhammer Fantasy Roleplay 4e"},
            "page_start": 3,
            "page_end": 3,
        },
        {
            "document": {"id": "doc2", "title": "Zoo [deluxe]", "role_label": ""},
            "game": {"title": "WFRP"},
            "page_start": None,
            "page_end": None,
        },
    ]
    markdown = references_markdown(results)
    assert "#### References" in markdown
    assert "Core Rules, p. 3" in markdown
    assert "/api/documents/doc1/file#page=3" in markdown
    assert "Warhammer Fantasy Roleplay 4e" in markdown
    assert "Zoo \\[deluxe\\]" in markdown
    assert "#### References" in markdown

    # Only cited excerpts are listed, keeping the original [n] numbering.
    cited = references_markdown(results, refs=[2])
    assert "Core Rules" not in cited
    assert "**2.** [Zoo" in cited


def test_rewrite_queries_filters_and_limits():
    from app.services.rag import rewrite_queries

    class RewriteProvider(Provider):
        def chat(self, messages, model, temperature=0.2, max_tokens=2048):
            yield "dwarf movement\n- Movement Table walk run\n1. dwarf running speed\n"

    provider = RewriteProvider(ProviderConfig(id="fake", name="Fake", kind="fake", base_url=""))
    assert rewrite_queries(provider, "fake-model", "how fast can a dwarf run") == [
        "dwarf movement",
        "Movement Table walk run",
        "dwarf running speed",
    ]


def test_settings_report_chat_readiness(client):
    assert client.get("/api/settings").json()["info"]["chat_ready"] is False
    client.put(
        "/api/settings",
        json={
            "default_chat_provider": "ollama",
            "default_chat_model": "llama3.1:8b-instruct-q4_K_M",
        },
    )
    info = client.get("/api/settings").json()["info"]
    assert info["chat_ready"] is True
    assert info["chat_model_active"] == "llama3.1:8b-instruct-q4_K_M"
    client.put(
        "/api/settings",
        json={"default_chat_provider": "", "default_chat_model": ""},
    )


def test_game_types_expose_errata_precedence(client):
    types = {item["id"]: item for item in client.get("/api/game-types").json()["game_types"]}
    for game_type in ("rpg", "boardgame", "wargame"):
        roles = {role["id"]: role for role in types[game_type]["roles"]}
        assert "errata" in roles
        assert roles["errata"]["precedence"] == 100
        assert roles["core"]["precedence"] == 0


def test_errata_outranks_identical_core_text(client, game):
    core = upload_document(client, game["id"], role="core", title="Core Rules")
    errata = upload_document(client, game["id"], role="errata", title="Official Errata")
    wait_until_ready(client, core["id"])
    wait_until_ready(client, errata["id"])

    response = client.get(
        "/api/search", params={"q": "charge reaction", "mode": "keyword"}
    ).json()
    assert response["count"] == 2
    first = response["results"][0]
    assert first["document"]["role"] == "errata"
    assert first["document"]["overrides"] is True
    assert first["document"]["precedence"] == 100
    assert first["document"]["role_label"] == "Errata / corrections"
    assert response["results"][1]["document"]["overrides"] is False


def test_diversify_stops_one_document_filling_the_page():
    from app.services.search import diversify

    results = [
        {
            "chunk_id": f"a{index}",
            "document": {"id": "errata"},
        }
        for index in range(6)
    ] + [
        {"chunk_id": f"b{index}", "document": {"id": "core"}} for index in range(2)
    ]
    selected = diversify(results, limit=5)
    assert len(selected) == 5
    assert sum(1 for item in selected if item["document"]["id"] == "errata") == 3
    assert any(item["document"]["id"] == "core" for item in selected)


def test_answer_prompt_reasons_about_step_order():
    from app.db import db
    from app.services.rag import build_messages

    with db() as conn:
        messages, _used = build_messages(conn, "Can this happen during setup?", [])

    prompt = messages[-1]["content"]
    assert "Answer in this order." in prompt
    assert "Order:" in prompt
    assert "Unclear or Not stated" in prompt
    assert "for each part" in prompt
    assert "Separate baseline from exception" in prompt
    assert "available only from the step that introduces it onward" in prompt
    assert "only with numbers from this list" in prompt
    assert "Do not print" in prompt


def test_system_prompt_removes_legacy_lead_with_answer(client):
    from app.db import db, get_setting, set_setting
    from app.services.rag import system_prompt

    with db() as conn:
        previous = get_setting(conn, "system_prompt")
        set_setting(
            conn,
            "system_prompt",
            "Custom referee. Put the direct answer in the first sentence. Keep this.",
        )
        cleaned = system_prompt(conn)
    if previous is not None:
        with db() as conn:
            set_setting(conn, "system_prompt", previous)

    assert "Put the direct answer" not in cleaned
    assert "Keep this." in cleaned
    assert "takes precedence over any instruction to lead with the answer" in cleaned


def test_official_prompt_ignores_forum_results():
    from app.db import db
    from app.services.rag import build_messages

    forum = {
        "source_type": "bgg",
        "url": "https://boardgamegeek.com/thread/123/question",
        "document": {"id": "", "title": "Forum thread", "role_label": "BGG forum"},
        "game": {"title": "A Game"},
        "page_start": None,
        "page_end": None,
        "text": "Forum opinion.",
    }
    with db() as conn:
        messages, used = build_messages(conn, "Question?", [forum])

    assert used == []
    prompt = messages[-1]["content"]
    assert "(No excerpts were retrieved" in prompt
    assert "BGG FORUM" not in prompt


def test_community_prompt_excludes_official_history():
    from app.db import db
    from app.services.rag import build_community_messages

    forum = {
        "source_type": "bgg",
        "url": "https://boardgamegeek.com/thread/123/question",
        "document": {"id": "", "title": "Forum thread", "role_label": "BGG forum"},
        "game": {"title": "A Game"},
        "page_start": None,
        "page_end": None,
        "text": "Two of three posters agree on the timing.",
    }
    history = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "Official answer with [3]"},
        {"role": "user", "content": "Follow-up question"},
    ]
    with db() as conn:
        messages, _used = build_community_messages(
            conn, "Follow-up question", [forum], history=history
        )

    history_messages = messages[1:-1]
    assert [message["role"] for message in history_messages] == ["user", "user"]
    assert all("Official answer" not in message["content"] for message in history_messages)
    prompt = messages[-1]["content"]
    assert "which you cannot see" in prompt
    assert "how many posts support it" in prompt
    assert "Do not use earlier turns as sources" in prompt


def test_reddit_toggle_setting(client):
    saved = client.put(
        "/api/settings", json={"reddit_enabled": False}
    ).json()
    assert saved["info"]["reddit_enabled"] is False
    saved = client.put("/api/settings", json={"reddit_enabled": True}).json()
    assert saved["info"]["reddit_enabled"] is True


def test_reddit_result_is_labelled_and_linked():
    from app.services.reddit import _make_result

    result = _make_result(
        "Flood errata",
        "https://www.reddit.com/r/Earthborne_Rangers/comments/17htk3n/flood_errata/",
        "Does the errata for Flood apply to both cards?",
    )
    assert result is not None
    assert result["source_type"] == "reddit"
    assert result["url"].startswith("https://www.reddit.com/r/Earthborne_Rangers/")
    assert result["document"]["title"] == "Flood errata"
    assert result["document"]["role_label"] == "Reddit · r/Earthborne_Rangers"


def test_reddit_plain_search_filters_by_game(monkeypatch):
    from app.services import reddit

    def fake_yahoo(query: str, limit: int = 10) -> list[dict]:
        return [
            {
                "title": "Flood errata",
                "url": "https://www.reddit.com/r/Earthborne_Rangers/comments/17htk3n/flood_errata/",
                "snippet": "Does the errata for Flood apply to both cards?",
            },
            {
                "title": "Forbidden Island flood",
                "url": "https://www.reddit.com/r/boardgames/comments/donr9j/forbidden/",
                "snippet": "An unrelated flood card question.",
            },
        ]

    monkeypatch.setattr(reddit, "search_yahoo", fake_yahoo)
    results, note = reddit.search_reddit(
        "unique flood errata question about Earthborne Rangers",
        "Earthborne Rangers",
        3,
    )
    assert note is None
    assert len(results) == 1
    assert results[0]["document"]["title"] == "Flood errata"
    assert "Earthborne_Rangers" in results[0]["url"]


def test_reddit_queries_use_game_and_question_terms():
    from app.services.reddit import _reddit_queries

    queries = _reddit_queries(
        "if i draw a Flood card during location setup do I automatically fail "
        "its condition?",
        "Earthborne Rangers",
    )
    assert len(queries) <= 6
    assert any(
        query.startswith('site:reddit.com "Earthborne Rangers"') for query in queries
    )
    assert any("flood" in query.lower() for query in queries)


def test_rag_marks_reddit_sources_as_unofficial():
    from app.services.rag import build_context, references_markdown

    result = {
        "source_type": "reddit",
        "url": "https://www.reddit.com/r/EarthborneRangers/comments/abc/thread/",
        "document": {
            "id": "",
            "title": "Flood card timing",
            "role_label": "Reddit · r/EarthborneRangers",
            "overrides": False,
        },
        "game": {"title": "Earthborne Rangers"},
        "page_start": None,
        "page_end": None,
        "text": "A poster says the flood is added after setup.",
    }
    context, used = build_context([result])
    assert "REDDIT (unofficial)" in context
    markdown = references_markdown(used)
    assert "**REDDIT**" in markdown
    assert "unofficial Reddit post" in markdown


def test_bgg_queries_broaden_long_questions():
    from app.services.bgg import _bgg_queries

    queries = _bgg_queries(
        "if i draw a Flood card during location setup do I automatically fail "
        "its condition?",
        "Earthborne Rangers",
    )
    assert len(queries) <= 14
    assert queries[0].startswith("site:boardgamegeek.com/thread")
    assert any('"flood card" setup' in query for query in queries)
    assert any("Earthborne Rangers" in query for query in queries)


def test_rewrite_prompt_requests_sequence_sections():
    from app.services.rag import REWRITE_SYSTEM

    assert "sequence section" in REWRITE_SYSTEM
    assert "setup steps" in REWRITE_SYSTEM
    assert "order of play" in REWRITE_SYSTEM


def test_rag_marks_errata_as_overriding():
    from app.services.rag import build_context, references_markdown

    results = [
        {
            "document": {
                "id": "errata1",
                "title": "Official Errata",
                "role_label": "Errata / corrections",
                "overrides": True,
                "precedence": 100,
            },
            "game": {"title": "WFRP"},
            "page_start": 3,
            "page_end": 3,
            "text": "Charge reactions now allow Stand and Shoot.",
        }
    ]
    context, used = build_context(results)
    assert "ERRATA (official correction)" in context
    markdown = references_markdown(used)
    assert "Errata takes precedence" in markdown
    assert "**ERRATA**" in markdown
    assert "/api/documents/errata1/file#page=3" in markdown


def test_rag_marks_bgg_forum_sources_as_unofficial():
    from app.services.rag import build_context, references_markdown

    results = [
        {
            "source_type": "bgg",
            "url": "https://boardgamegeek.com/thread/123/rules-question",
            "document": {
                "id": "",
                "title": "Rules question",
                "role_label": "BGG forum",
                "overrides": False,
            },
            "game": {"title": "Earthborne Rangers"},
            "page_start": None,
            "page_end": None,
            "text": "The forum says to resolve the card this way.",
        }
    ]
    context, used = build_context(results)
    assert "BGG FORUM (unofficial)" in context
    markdown = references_markdown(used)
    assert "**BGG FORUM**" in markdown
    assert "https://boardgamegeek.com/thread/123/rules-question" in markdown
    assert "unofficial community post" in markdown
    assert "/api/documents/" not in markdown


def test_rag_keeps_forum_excerpts_when_rulebooks_fill_the_context():
    from app.services.rag import MAX_CONTEXT_CHARS, build_context

    def rulebook(index: int) -> dict:
        return {
            "document": {
                "id": f"doc{index}",
                "title": f"Rulebook {index}",
                "role_label": "Core rules",
                "overrides": False,
            },
            "game": {"title": "WFRP"},
            "page_start": 1,
            "page_end": 1,
            "text": "x" * 2_200,
        }

    forum = {
        "source_type": "bgg",
        "url": "https://boardgamegeek.com/thread/999/edge-case",
        "document": {
            "id": "",
            "title": "Edge case thread",
            "role_label": "BGG forum",
            "overrides": False,
        },
        "game": {"title": "WFRP"},
        "page_start": None,
        "page_end": None,
        "text": "The forum discusses this edge case.",
    }

    context, used = build_context([rulebook(i) for i in range(10)] + [forum])
    assert len(context) <= MAX_CONTEXT_CHARS + 500
    assert [entry["source_type"] for entry in used if entry.get("source_type") == "bgg"] == [
        "bgg"
    ]
    assert "BGG FORUM (unofficial)" in context


def test_community_answer_uses_global_reference_numbers():
    from app.db import db
    from app.services.rag import build_community_messages

    forum = {
        "source_type": "bgg",
        "url": "https://boardgamegeek.com/thread/321/rules-question",
        "document": {
            "id": "",
            "title": "Rules question",
            "role_label": "BGG forum",
            "overrides": False,
        },
        "game": {"title": "Earthborne Rangers"},
        "page_start": None,
        "page_end": None,
        "text": "The community resolves this during the travel phase.",
    }

    with db() as conn:
        messages, used = build_community_messages(
            conn, "When does this resolve?", [forum], start_ref=4
        )

    assert used and used[0]["ref"] == 4
    prompt = messages[-1]["content"]
    assert "[4] BGG FORUM (unofficial)" in prompt
    assert "unofficial community forum posts" in prompt
    assert "BoardGameGeek and Reddit" in prompt
    assert "which you cannot see" in prompt


def test_change_document_section_updates_chunks_and_campaign(client, game):
    from app.db import db

    document = upload_document(client, game["id"], role="other", title="One Day Missions")
    wait_until_ready(client, document["id"])

    moved = client.patch(
        f"/api/documents/{document['id']}", json={"role": "campaign"}
    ).json()
    assert moved["role"] == "campaign"
    with db() as conn:
        chunk_roles = {
            row["role"]
            for row in conn.execute(
                "SELECT role FROM chunks WHERE document_id = ?", (document["id"],)
            )
        }
    assert chunk_roles == {"campaign"}

    campaign = client.post(
        f"/api/games/{game['id']}/campaigns",
        json={"title": "One-Day Missions", "description": ""},
    ).json()
    assigned = client.patch(
        f"/api/documents/{document['id']}",
        json={"campaign_id": campaign["id"]},
    ).json()
    assert assigned["campaign_id"] == campaign["id"]

    moved_back = client.patch(
        f"/api/documents/{document['id']}", json={"role": "other"}
    ).json()
    assert moved_back["role"] == "other"
    assert moved_back["campaign_id"] is None

    invalid = client.patch(
        f"/api/documents/{document['id']}", json={"role": "not-a-section"}
    )
    assert invalid.status_code == 400


def test_unsupported_upload_rejected(client, game):
    response = client.post(
        "/api/documents",
        data={"game_id": game["id"], "role": "core", "title": "Book"},
        files={"file": ("notes.xyz", b"hello", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]


def test_invalid_role_rejected(client, game):
    response = client.post(
        "/api/documents",
        data={"game_id": game["id"], "role": "banana", "title": "Book"},
        files={"file": ("rules.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_sqlite_schema_has_fts(client):
    with db() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
        }
    assert {
        "games",
        "documents",
        "campaigns",
        "chunks",
        "chunks_fts",
        "embeddings",
        "providers",
        "users",
        "sessions",
    } <= tables
