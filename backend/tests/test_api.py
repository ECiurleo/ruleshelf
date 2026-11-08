"""API integration tests covering the core library workflow."""

from __future__ import annotations

import numpy as np

from app.db import db
from app.providers.base import ModelInfo, Provider, ProviderConfig
from app.services.search import SearchFilters, search_semantic
from tests.conftest import upload_document, wait_until_ready


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
    assert "2. [Zoo" in cited


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
    assert "ERRATA (overrides core rules)" in context
    markdown = references_markdown(used)
    assert "Errata takes precedence" in markdown
    assert "**ERRATA**" in markdown
    assert "/api/documents/errata1/file#page=3" in markdown


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
    assert {"games", "documents", "chunks", "chunks_fts", "embeddings", "providers"} <= tables
