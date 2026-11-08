"""Retrieval-augmented answering: prompt construction for the chat providers."""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Sequence

from app.db import get_setting
from app.defaults import DEFAULT_SYSTEM_PROMPT

log = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 16_000
MAX_CHUNK_CHARS = 2_200

REWRITE_SYSTEM = (
    "You convert tabletop rules questions into concise keyword searches for a "
    "rulebook index. Return 1 to 3 lines. Each line must be 2 to 4 words, using "
    "likely rule, section or table names. No numbering, quotes or explanation."
)


def rewrite_queries(provider, model: str, question: str) -> list[str]:
    """Ask the chat model for a few short index-friendly queries."""
    try:
        response = "".join(
            provider.chat(
                [
                    {"role": "system", "content": REWRITE_SYSTEM},
                    {"role": "user", "content": question},
                ],
                model,
                temperature=0.0,
                max_tokens=100,
            )
        )
    except Exception as exc:  # noqa: BLE001 - expansion is optional
        log.warning("Query rewrite failed: %s", exc)
        return []

    queries: list[str] = []
    seen = {question.strip().lower()}
    for raw in response.splitlines():
        line = raw.strip()
        line = re.sub(r"^[-*•\d.\s]+", "", line)
        line = line.strip(" \t\"'")
        if not line or len(line) > 80:
            continue
        words = line.split()
        if not (2 <= len(words) <= 6):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(line)
        if len(queries) >= 3:
            break
    return queries

_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>])")


def _escape_markdown(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def system_prompt(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "system_prompt", DEFAULT_SYSTEM_PROMPT) or DEFAULT_SYSTEM_PROMPT


def _citation_label(result: dict) -> str:
    game = result["game"]["title"]
    document = result["document"]["title"]
    role = result["document"].get("role_label") or ""
    page = result.get("page_start")
    parts = [game, document]
    label_prefix = ""
    if result["document"].get("overrides"):
        label_prefix = "ERRATA (overrides core rules) — "
    if role:
        parts.append(role)
    label = " — ".join(parts)
    if page:
        if result.get("page_end") and result["page_end"] != page:
            label += f", pp. {page}–{result['page_end']}"
        else:
            label += f", p. {page}"
    return label_prefix + label


def build_context(results: Sequence[dict]) -> tuple[str, list[dict]]:
    blocks: list[str] = []
    used: list[dict] = []
    total = 0
    for result in results:
        text = result["text"].strip()
        if len(text) > MAX_CHUNK_CHARS:
            text = text[:MAX_CHUNK_CHARS].rsplit(" ", 1)[0] + " …"
        block = f"[{len(used) + 1}] {_citation_label(result)}\n{text}"
        if total + len(block) > MAX_CONTEXT_CHARS and used:
            break
        blocks.append(block)
        used.append({**result, "ref": len(used) + 1})
        total += len(block)
    return "\n\n".join(blocks), used


def build_messages(
    conn: sqlite3.Connection,
    query: str,
    results: Sequence[dict],
    history: Sequence[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    context, used = build_context(results)
    if not context:
        context = "(No excerpts were retrieved from the library.)"

    errata = any(result["document"].get("overrides") for result in results)
    priority = (
        "IMPORTANT: excerpts marked ERRATA are official corrections that supersede "
        "conflicting core rules. Use the errata text as the current rule.\n\n"
        if errata
        else ""
    )
    prompt = (
        f"{priority}The numbered excerpts below come from the user's rulebooks.\n\n"
        f"{context}\n\n"
        f"Question: {query}\n\n"
        "Answer using only these excerpts, citing the excerpt number in square "
        "brackets after every rule statement. Put the direct answer in the first "
        "sentence. When the excerpts give a formula or table, do the arithmetic "
        "(for example Walk = Movement x 2 and Run = Movement x 4) and state the "
        "numbers. When the excerpts contain comparable entries (other species, "
        "weapons, and so on), state the comparison explicitly with their values. "
        "If the excerpts do not answer it, say what is missing."
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt(conn)}]
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": prompt})
    return messages, used


def references_markdown(results: Sequence[dict], refs: Sequence[int] | None = None) -> str:
    """Deterministic citation block appended after every answer.

    The model is told not to write its own references; this guarantees each
    answer ends with the document title, page number and a link to the source.
    ``refs`` limits the block to the excerpts the answer actually cited; the
    numbers stay aligned with the inline ``[n]`` markers.
    """
    if not results:
        return ""
    selected: list[tuple[int, dict]] = []
    for index, result in enumerate(results, start=1):
        number = int(result.get("ref") or index)
        if refs is None or number in refs:
            selected.append((number, result))
    if not selected:
        return ""

    lines = ["", "", "---", "", "#### References", ""]
    if any(result["document"].get("overrides") for _, result in selected):
        lines.append(
            "> **Errata takes precedence** over the core rules where they conflict."
        )
        lines.append("")
    for number, result in selected:
        document = result["document"]
        game = result["game"]
        page = result.get("page_start")
        page_end = result.get("page_end")
        if page and page_end and page_end != page:
            location = f", pp. {page}–{page_end}"
        elif page:
            location = f", p. {page}"
        else:
            location = ""

        url = f"/api/documents/{document['id']}/file"
        if page:
            url += f"#page={page}"

        marker = "**ERRATA** " if document.get("overrides") else ""
        line = (
            f"{number}. {marker}[{_escape_markdown(document['title'])}{location}]({url})"
            f" — *{_escape_markdown(game['title'])}*"
        )
        role = document.get("role_label")
        if role:
            line += f" · {_escape_markdown(role)}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)
