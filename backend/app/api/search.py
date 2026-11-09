"""Search and streaming RAG endpoints."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from itertools import combinations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db import db, get_setting
from app.providers import Provider, ProviderConfig, build_provider
from app.providers.base import ProviderError
from app.services.bgg import search_bgg
from app.services.embeddings import resolve_embedding
from app.services.rag import (
    build_community_messages,
    build_messages,
    references_markdown,
    rewrite_queries,
)
from app.services.reddit import search_reddit
from app.services.search import (
    SearchFilters,
    build_match_query,
    diversify,
    role_info,
    rrf_merge,
    search,
    search_keyword,
)

router = APIRouter(prefix="/api", tags=["search"])


def _optional_embedding(conn: sqlite3.Connection) -> tuple[Provider, str] | None:
    try:
        return resolve_embedding(conn)
    except ProviderError:
        return None


def _answer_results(
    conn: sqlite3.Connection,
    question: str,
    provider: Provider,
    model: str,
    mode: str,
    filters: SearchFilters,
    limit: int,
    embedding: tuple[Provider, str] | None,
) -> tuple[list[dict], str, str | None, list[str]]:
    """Retrieve for the question and a few model-written keyword variants.

    Questions such as "how fast can a dwarf run" rarely contain the rulebook's
    own term ("Movement"), so a single lexical search misses the stat table.
    """
    results, mode_used, note = search(
        conn, question, mode=mode, filters=filters, limit=limit, embedding=embedding
    )
    queries = rewrite_queries(provider, model, question)
    if not queries:
        return results, mode_used, note, []

    lists = [results]
    roles = role_info(conn)
    for expanded in queries:
        try:
            extra, _, _ = search(
                conn,
                expanded,
                mode=mode,
                filters=filters,
                limit=max(limit * 2, 10),
                embedding=embedding,
            )
            if extra:
                lists.append(extra)
        except ProviderError:
            pass

        terms = [t.rstrip("*") for t in re.findall(r'"([^"]+)"', build_match_query(expanded))]
        for first, second in combinations(terms[:4], 2):
            keyword_hits = search_keyword(
                conn, f"{first} {second}", filters, max(limit * 2, 10), roles
            )
            if keyword_hits:
                lists.append(keyword_hits)

    # The question itself outranks the model's expanded keyword variants; the
    # variants add recall but can otherwise drown the exact question.
    weights = [2.5] + [1.0] * (len(lists) - 1)
    merged = rrf_merge(*lists, limit=max(limit * 3, 30), weights=weights)
    return (
        diversify(merged, limit),
        "hybrid" if len(lists) > 1 else mode_used,
        note,
        queries,
    )


def _embedding_info(embedding: tuple[Provider, str] | None, mode_used: str) -> dict | None:
    if not embedding or mode_used == "keyword":
        return None
    provider, model = embedding
    return {
        "provider_id": provider.config.id,
        "provider_name": provider.config.name,
        "model": model,
    }


def _parse_roles(roles: str | None) -> list[str]:
    if not roles:
        return []
    return [role.strip() for role in roles.split(",") if role.strip()]


def _public_result(result: dict) -> dict:
    return {
        "chunk_id": result["chunk_id"],
        "snippet": result["snippet"],
        "page_start": result["page_start"],
        "page_end": result["page_end"],
        "score": round(result["score"], 6),
        "source_type": result.get("source_type", "rules"),
        "url": result.get("url"),
        "document": result["document"],
        "game": result["game"],
    }


@router.get("/search")
def search_endpoint(
    q: str = Query(min_length=1),
    game_id: str | None = None,
    roles: str | None = None,
    document_id: str | None = None,
    mode: str = Query(default="hybrid", pattern="^(keyword|semantic|hybrid)$"),
    limit: int = Query(default=25, ge=1, le=100),
    include_bgg: bool = Query(default=False),
):
    filters = SearchFilters(
        game_id=game_id,
        roles=_parse_roles(roles),
        document_ids=[document_id] if document_id else [],
    )
    with db() as conn:
        embedding = _optional_embedding(conn)
        try:
            results, mode_used, note = search(
                conn,
                q,
                mode=mode,
                filters=filters,
                limit=limit,
                embedding=embedding,
            )
        except ProviderError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        embedding_info = _embedding_info(embedding, mode_used)
        game_row = (
            conn.execute(
                "SELECT title, game_type FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            if game_id
            else None
        )

    bgg_results: list[dict] = []
    bgg_note: str | None = None
    if include_bgg:
        game_title = game_row["title"] if game_row else None
        bgg_results, bgg_note = search_bgg(q, game_title, limit=5)
        for result in bgg_results:
            result["game"] = {
                "id": game_id or "",
                "title": game_title or "BoardGameGeek",
                "game_type": game_row["game_type"] if game_row else "other",
            }
        results = results + bgg_results

    return {
        "query": q,
        "mode": mode,
        "mode_used": mode_used,
        "note": note,
        "count": len(results),
        "embedding": embedding_info,
        "bgg_count": len(bgg_results),
        "bgg_note": bgg_note,
        "results": [_public_result(r) for r in results],
    }


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    game_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    document_id: str | None = None
    mode: str = "hybrid"
    provider_id: str | None = None
    model: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=30)
    temperature: float | None = Field(default=None, ge=0, le=2)
    include_bgg: bool = False
    history: list[dict] = Field(default_factory=list)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/ask")
def ask(payload: AskRequest):
    with db() as conn:
        provider_id = payload.provider_id or get_setting(conn, "default_chat_provider")
        if not provider_id:
            raise HTTPException(
                400, "No chatting provider selected. Choose one in Settings → AI providers."
            )
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ? AND enabled = 1", (provider_id,)
        ).fetchone()
        if not row:
            raise HTTPException(400, "The selected AI provider is missing or disabled.")
        model = (
            payload.model
            or get_setting(conn, "default_chat_model")
            or row["chat_model"]
        )
        if not model:
            raise HTTPException(
                400, f"Choose a chat model for {row['name']} in Settings → AI providers."
            )
        provider = build_provider(ProviderConfig.from_row(row))

        filters = SearchFilters(
            game_id=payload.game_id,
            roles=payload.roles,
            document_ids=[payload.document_id] if payload.document_id else [],
        )
        embedding = _optional_embedding(conn)
        try:
            results, mode_used, note, expanded_queries = _answer_results(
                conn,
                payload.query,
                provider,
                model,
                payload.mode,
                filters,
                payload.top_k or int(get_setting(conn, "rag_top_k", "10") or 10),
                embedding,
            )
        except ProviderError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        embedding_info = _embedding_info(embedding, mode_used)

        # BGG is a second, separate search. Run it alongside the official
        # answer so the referee answer never waits for the forum lookup.
        game_row = (
            conn.execute(
                "SELECT title, game_type FROM games WHERE id = ?", (payload.game_id,)
            ).fetchone()
            if payload.include_bgg and payload.game_id
            else None
        )
        game_title = game_row["title"] if game_row else None
        game_type = game_row["game_type"] if game_row else "other"
        community_state: dict = {
            "bgg": [],
            "reddit": [],
            "bgg_note": None,
            "reddit_note": None,
        }
        community_threads: list[threading.Thread] = []
        reddit_id = get_setting(conn, "reddit_client_id", "") or ""
        reddit_secret = get_setting(conn, "reddit_client_secret", "") or ""
        reddit_enabled = (get_setting(conn, "reddit_enabled", "1") or "1") != "0"

        def _attach_game(found: list[dict], fallback: str) -> None:
            for item in found:
                item["game"] = {
                    "id": payload.game_id or "",
                    "title": game_title or fallback,
                    "game_type": game_type,
                }

        def _run_bgg() -> None:
            try:
                found, note = search_bgg(payload.query, game_title, limit=5)
            except Exception:  # noqa: BLE001 - optional source must not fail the answer
                found, note = [], "BGG web search was unavailable."
            _attach_game(found, "BoardGameGeek")
            community_state["bgg"] = found
            community_state["bgg_note"] = note

        def _run_reddit() -> None:
            try:
                found, note = search_reddit(
                    payload.query,
                    game_title,
                    limit=3,
                    client_id=reddit_id,
                    client_secret=reddit_secret,
                )
            except Exception:  # noqa: BLE001 - optional source must not fail the answer
                found, note = [], "Reddit search was unavailable."
            _attach_game(found, "Reddit")
            community_state["reddit"] = found
            community_state["reddit_note"] = note

        if payload.include_bgg:
            for target in (_run_bgg, _run_reddit):
                if target is _run_reddit and (
                    not reddit_enabled or not reddit_id or not reddit_secret
                ):
                    continue
                thread = threading.Thread(target=target, daemon=True)
                community_threads.append(thread)
                thread.start()

        # The official answer uses rulebooks only; forum posts get their own
        # answer underneath so readers can tell the two apart.
        messages, used = build_messages(conn, payload.query, results, payload.history)
        temperature = (
            payload.temperature
            if payload.temperature is not None
            else float(get_setting(conn, "rag_temperature", "0.2") or 0.2)
        )
        provider_name = row["name"]

    def generate():
        yield _sse(
            "sources",
            {
                "sources": [_public_result(result) for result in used],
                "mode_used": mode_used,
                "note": note,
                "provider": provider_name,
                "model": model,
                "embedding": embedding_info,
                "expanded_queries": expanded_queries,
                "bgg_count": 0,
                "reddit_count": 0,
                "bgg_note": None,
            },
        )
        answered = False
        buffer: list[str] = []
        try:
            for token in provider.chat(messages, model, temperature, max_tokens=2048):
                answered = True
                buffer.append(token)
                yield _sse("token", {"t": token})
        except ProviderError as exc:
            yield _sse("error", {"message": exc.message})
        except Exception as exc:  # noqa: BLE001 - stream must end cleanly
            yield _sse("error", {"message": f"Answering failed: {exc}"})
        if answered:
            cited = sorted(
                {
                    int(match)
                    for match in re.findall(r"\[(\d{1,2})\]", "".join(buffer))
                    if 1 <= int(match) <= len(used)
                }
            )
            references = references_markdown(used, refs=cited or None)
            if references:
                yield _sse("token", {"t": references})

        community_messages: list[dict] = []
        community_used: list[dict] = []
        if payload.include_bgg:
            yield _sse("community_search", {})
            deadline = time.monotonic() + 20.0
            for thread in community_threads:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
                if thread.is_alive():
                    if thread is community_threads[0]:
                        community_state["bgg"] = []
                        community_state["bgg_note"] = (
                            "BGG search timed out; the rulebook answer is unaffected."
                        )
                    else:
                        community_state["reddit"] = []
                        community_state["reddit_note"] = (
                            "Reddit search timed out; the rulebook answer is unaffected."
                        )
            bgg_results = community_state["bgg"]
            reddit_results = community_state["reddit"]
            community_results = bgg_results + reddit_results
            notes = [
                note
                for note in (
                    community_state["bgg_note"],
                    community_state["reddit_note"],
                )
                if note and not note.startswith("No ")
            ]
            community_note = "; ".join(notes) if notes else None

            if community_results:
                community_messages, community_used = build_community_messages(
                    conn,
                    payload.query,
                    community_results,
                    payload.history,
                    start_ref=len(used) + 1,
                )
                if community_used:
                    yield _sse(
                        "community_sources",
                        {
                            "sources": [
                                _public_result(result) for result in community_used
                            ],
                            "count": len(community_used),
                            "bgg_count": len(bgg_results),
                            "reddit_count": len(reddit_results),
                            "note": community_note,
                        },
                    )
            else:
                community_messages, community_used = [], []
                yield _sse(
                    "community_note",
                    {
                        "note": community_note
                        or "No community threads found for this question."
                    },
                )

        if community_used and community_messages:
            ref_start = community_used[0]["ref"]
            ref_end = community_used[-1]["ref"]
            yield _sse(
                "community_start",
                {"count": len(community_used), "ref_start": ref_start},
            )
            community_answered = False
            community_buffer: list[str] = []
            try:
                for token in provider.chat(
                    community_messages, model, temperature, max_tokens=900
                ):
                    community_answered = True
                    community_buffer.append(token)
                    yield _sse("community_token", {"t": token})
            except ProviderError as exc:
                yield _sse("community_error", {"message": exc.message})
            except Exception as exc:  # noqa: BLE001 - stream must end cleanly
                yield _sse(
                    "community_error",
                    {"message": f"Community answer failed: {exc}"},
                )
            if community_answered:
                cited = sorted(
                    {
                        int(match)
                        for match in re.findall(
                            r"\[(\d{1,2})\]", "".join(community_buffer)
                        )
                        if ref_start <= int(match) <= ref_end
                    }
                )
                references = references_markdown(community_used, refs=cited or None)
                if references:
                    yield _sse("community_token", {"t": references})
            yield _sse("community_done", {})

        yield _sse("done", {})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
