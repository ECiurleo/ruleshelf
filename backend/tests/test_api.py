"""API integration tests covering the core library workflow."""

from __future__ import annotations

import numpy as np

from app.db import db, get_setting, set_setting
from app.providers.base import ModelInfo, Provider, ProviderConfig
from app.services.search import SearchFilters, search_semantic
from tests.conftest import upload_document, wait_until_ready


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
    assert "unofficial BoardGameGeek forum posts" in prompt
    assert "do not repeat the rulebook answer" in prompt


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
