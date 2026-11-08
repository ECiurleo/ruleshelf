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


TIMING_SYSTEM = (
    "Establish timing before applying a rule: identify the phase, step or trigger, "
    "what has already happened by then, and whether the card or effect exists at "
    "that point. Setup steps and round phases resolve in printed order; something "
    "introduced after a step cannot be used during it. Respect when, after, before "
    "and Response wording. If the excerpts do not fix the order, say so instead of "
    "inventing one."
)


def system_prompt(conn: sqlite3.Connection) -> str:
    prompt = get_setting(conn, "system_prompt", DEFAULT_SYSTEM_PROMPT) or DEFAULT_SYSTEM_PROMPT
    # Existing installs keep their stored prompt, so attach the timing rule here
    # unless the prompt already carries it.
    if "establish timing before applying a rule" in prompt.lower():
        return prompt
    return f"{prompt}\n\n{TIMING_SYSTEM}"


def _citation_label(result: dict) -> str:
    game = result["game"]["title"]
    document = result["document"]["title"]
    if result.get("source_type") == "bgg":
        return f"BGG FORUM (unofficial) — {document} — {game}"
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


def build_context(results: Sequence[dict], start_ref: int = 1) -> tuple[str, list[dict]]:
    """Build the citation-numbered context, keeping forum snippets in budget.

    Rulebook excerpts stay first and authoritative, but they must not consume
    the whole window: BGG results are appended last, so reserve room for them
    instead of letting the first long books crowd them out.
    """
    forum = [result for result in results if result.get("source_type") == "bgg"]
    rules = [result for result in results if result.get("source_type") != "bgg"]
    reserved = sum(min(len(result["text"].strip()), 600) + 140 for result in forum)
    rule_budget = max(MAX_CONTEXT_CHARS - reserved, MAX_CONTEXT_CHARS // 2)

    blocks: list[str] = []
    used: list[dict] = []
    total = 0

    def add(result: dict, budget: int) -> None:
        nonlocal total
        text = result["text"].strip()
        if not text:
            return
        if len(text) > MAX_CHUNK_CHARS:
            text = text[:MAX_CHUNK_CHARS].rsplit(" ", 1)[0] + " …"
        ref = start_ref + len(used)
        block = f"[{ref}] {_citation_label(result)}\n{text}"
        if total + len(block) > budget and used:
            return
        blocks.append(block)
        used.append({**result, "ref": ref})
        total += len(block)

    for result in rules:
        add(result, rule_budget)
    for result in forum:
        add(result, MAX_CONTEXT_CHARS)
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
        f"{priority}The numbered excerpts below come from the user's rulebooks and, "
        "when enabled, from BoardGameGeek forum threads.\n\n"
        f"{context}\n\n"
        f"Question: {query}\n\n"
        "Timing comes first. Before applying a rule, identify the phase, step or "
        "trigger the question depends on and what has already happened at that "
        "point. Setup steps and round phases resolve in the order the rules print "
        "them, so a card or effect introduced after a step cannot be used during "
        "that step. Respect 'when', 'after', 'before' and 'Response' wording, and "
        "resolve any ordering the excerpts give. When timing decides the answer, "
        "state it in one short sentence before the ruling, for example: 'The path "
        "deck is built at step 7 and arrival setup is step 8, so a card added after "
        "arrival setup is not in the deck during setup.' If the excerpts do not fix "
        "the order, say the order is unclear instead of inventing one.\n\n"
        "Then answer directly: start with yes or no when the question asks whether "
        "something can happen, and answer every part of a multi-part question. Give "
        "the rule, exact dice, distances and costs, and do any arithmetic the "
        "excerpts support (for example Walk = Movement x 2). When the excerpts "
        "contain comparable entries (other species, weapons, and so on), state the "
        "comparison explicitly with their values.\n\n"
        "Use only these excerpts, citing the excerpt number in square brackets after "
        "every rule statement. Rulebook excerpts are authoritative. Excerpts labeled "
        "BGG FORUM are unofficial community posts: label any claim taken from them "
        "as forum opinion and never let them override a rulebook excerpt. If the "
        "rulebook answers the question, use it and ignore conflicting forum "
        "snippets. Do not call the rules silent when their sequence settles the "
        "question. If the excerpts truly do not answer it, say what is missing."
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt(conn)}]
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": prompt})
    return messages, used


def build_community_messages(
    conn: sqlite3.Connection,
    query: str,
    results: Sequence[dict],
    history: Sequence[dict] | None = None,
    start_ref: int = 1,
) -> tuple[list[dict], list[dict]]:
    """Prompt for a second, clearly unofficial answer drawn from BGG threads.

    ``start_ref`` keeps citation numbers aligned with the combined source list
    shown under the answer, so ``[n]`` opens the right thread card.
    """
    context, used = build_context(results, start_ref=start_ref)
    if not context:
        return [], []

    prompt = (
        "The numbered excerpts below are unofficial BoardGameGeek forum posts, "
        "not rules text. They are being shown to the reader as a separate "
        "community answer underneath the official rulebook answer.\n\n"
        f"{context}\n\n"
        f"Question: {query}\n\n"
        "Answer using only these forum posts. Start with the community consensus, "
        "then note meaningful disagreement or common house rules, and say when a "
        "post's answer depends on a particular step or timing. Cite the excerpt "
        "number in square brackets after each claim. Never present forum opinion as "
        "an official rule, and do not repeat the rulebook answer. If the posts do "
        "not answer the question, say so briefly."
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt(conn)}]
    for turn in (history or [])[-4:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:3000]})
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

        if result.get("source_type") == "bgg":
            lines.append(
                f"- **{number}.** **BGG FORUM** "
                f"[{_escape_markdown(document['title'])}]({result.get('url') or ''})"
                f" — *{_escape_markdown(game['title'])}* · unofficial community post"
            )
            continue

        marker = "**ERRATA** " if document.get("overrides") else ""
        line = (
            f"- **{number}.** {marker}"
            f"[{_escape_markdown(document['title'])}{location}]({url})"
            f" — *{_escape_markdown(game['title'])}*"
        )
        role = document.get("role_label")
        if role:
            line += f" · {_escape_markdown(role)}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)
