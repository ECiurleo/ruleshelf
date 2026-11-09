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
    "rulebook index. Return 1 to 3 lines of 2 to 4 words, using likely rule, "
    "section or table names and the game's own nouns from the question. If the "
    "question asks whether something can happen at a point in play (setup, a "
    "phase, a turn, a trigger), make one line the name of that sequence section, "
    "such as \"setup steps\", \"turn sequence\" or \"order of play\". No "
    "numbering, quotes or explanation."
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


ORDER_SYSTEM = (
    "Order of play matters. Before applying any rule, check what has already "
    "happened, and what exists, at the point the question is about. Each question "
    "comes with an Order and Answer format; follow it, and it takes precedence over "
    "any instruction to lead with the answer. Cite [n] only from the current "
    "excerpt list; never invent rules, page numbers or book names."
)

COMMUNITY_SYSTEM = (
    "You summarise unofficial tabletop community posts from BoardGameGeek and "
    "Reddit for a reader. Use only the numbered posts, never present forum opinion "
    "as an official rule, and never invent posts, rules, page numbers or links."
)

_LEGACY_LEAD = re.compile(r"Put the direct answer in the first sentence\.\s*", re.IGNORECASE)
_LEGACY_FORMULA = re.compile(
    r"\s*\(for example Walk = Movement x 2, Run = Movement x 4\)", re.IGNORECASE
)
_ORDER_MARKER = "takes precedence over any instruction to lead with the answer"


def system_prompt(conn: sqlite3.Connection) -> str:
    prompt = get_setting(conn, "system_prompt", DEFAULT_SYSTEM_PROMPT) or DEFAULT_SYSTEM_PROMPT
    # Existing installs keep their stored prompt, and older ones still say
    # "answer first". Remove that conflict and append the order pointer.
    prompt = _LEGACY_LEAD.sub("", prompt)
    prompt = _LEGACY_FORMULA.sub("", prompt).strip()
    if _ORDER_MARKER not in prompt.lower():
        prompt = f"{prompt}\n\n{ORDER_SYSTEM}"
    return prompt


def _citation_label(result: dict) -> str:
    game = result["game"]["title"]
    document = result["document"]["title"]
    if result.get("source_type") in {"bgg", "reddit"}:
        source = "BGG FORUM" if result.get("source_type") == "bgg" else "REDDIT"
        return f"{source} (unofficial) — {document} — {game}"
    role = result["document"].get("role_label") or ""
    page = result.get("page_start")
    parts = [game, document]
    label_prefix = ""
    if result["document"].get("overrides"):
        label_prefix = "ERRATA (official correction) — "
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
    forum = [
        result for result in results if result.get("source_type") in {"bgg", "reddit"}
    ]
    rules = [
        result for result in results if result.get("source_type") not in {"bgg", "reddit"}
    ]
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
    # BGG threads are answered separately; never let them enter the official
    # context or consume its excerpt budget.
    rule_results = [
        result
        for result in results
        if result.get("source_type") not in {"bgg", "reddit"}
    ]
    context, used = build_context(rule_results)
    if not context:
        context = "(No excerpts were retrieved from the library.)"

    errata = any(result["document"].get("overrides") for result in rule_results)
    priority = (
        "Excerpts marked ERRATA are official corrections. Each replaces only the "
        "text it corrects, within any scope it names (a mission, card, edition). "
        "Apply it on top of the core rule and keep the rest of that rule. If errata "
        "entries conflict, say so.\n\n"
        if errata
        else ""
    )
    prompt = (
        f"{priority}Numbered excerpts from the user's rulebooks:\n\n"
        f"{context}\n\n"
        f"Question: {query}\n\n"
        "Answer in this order.\n\n"
        "1. Parts. Split the question into its parts (for example: can it happen, "
        "when, what follows). Answer each part on its own. A \"no\" to an earlier "
        "part does not settle a later one: say the later part does not arise at that "
        "point, then give what the excerpts state for when it does.\n\n"
        "2. Order. If the question depends on setup, a phase, a turn, initiative, a "
        "combat step, a trigger or any timing window, write \"Order:\" and one to "
        "three lines. Each line must quote the clause that fixes the order, keeping "
        "its sequence words (before, after, then, finally, once, when), and cite the "
        "excerpt. Never drop a sequence word or compress several steps into one. "
        "Then state the sequence in plain order. A card, token or effect is "
        "available only from the step that introduces it onward: if an excerpt says "
        "it is shuffled in, put into play or attached after step X, it is absent "
        "during step X and every earlier step. Do not say it can exist earlier unless "
        "an excerpt explicitly says so. Separate baseline from exception: use the "
        "general setup or phase list as the baseline, and if an excerpt gives a "
        "mission-, card- or scenario-specific instruction, label it and say exactly "
        "where it is inserted; never splice it into the baseline as if it were part "
        "of the normal sequence. When in doubt about whether timing matters, include "
        "Order: it is safer to state the sequence than to skip it.\n\n"
        "3. Answer. Begin with Yes, No, Unclear or Not stated for each part (label "
        "them (a), (b) when there is more than one), then the reason. For a "
        "\"can I do X during Y\" question, say whether X exists in the baseline at "
        "Y; a later specific insertion does not make it exist earlier. Keep the whole "
        "answer to roughly 3 to 8 sentences. Do not print \"1. Parts\", "
        "\"2. Order\" or \"3. Answer\" as headings; write \"Order:\" once, then "
        "the verdict paragraph.\n"
        "No: the rules or their order rule it out. This is a complete answer. Name "
        "the blocking step or condition.\n"
        "Unclear: both steps appear but their order is not given. Name them.\n"
        "Not stated: nothing relevant is in the excerpts. After everything the "
        "excerpts do show, say in one sentence what is missing.\n"
        "Do not open with \"the excerpts do not establish\" when order settles the "
        "question.\n\n"
        "Wording, as the excerpts use it: then, after and finally put a step later; "
        "before puts it earlier, and an effect worded \"before X\" is unusable once "
        "X has started; when, whenever and once name a trigger (\"once\" can also "
        "mean a limit); Response and similar windows open only after their named "
        "trigger and only for effects available then; instead, would, prevent and "
        "skip change an event before it happens, so check what depends on the "
        "original event. For nested or simultaneous triggers use the order the "
        "excerpts give; if none is given, say so rather than assuming one. A "
        "numbered or explicitly sequenced list fixes order; a passing mention does "
        "not.\n\n"
        "Sources. Use only the excerpts that bear on the question and ignore the "
        "rest. Cite [n] after every rule statement, only with numbers from this list "
        "(numbers in earlier turns referred to other lists), and cite the excerpt "
        "that states the point, not one that merely shares a term. Do the arithmetic "
        "the excerpts support and show the numbers; when they list comparable "
        "entries, compare them with their values. Keep to roughly 3 to 8 sentences."
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
    """Prompt for the separate, clearly unofficial answer from BGG threads.

    ``start_ref`` keeps citation numbers aligned with the combined source list
    shown under the answer. Official answers are deliberately excluded from the
    history so they cannot leak into this call.
    """
    context, used = build_context(results, start_ref=start_ref)
    if not context:
        return [], []

    prompt = (
        "The numbered excerpts below are unofficial community forum posts "
        "(BoardGameGeek and Reddit), not rules text. They appear under the official "
        "answer as a separate community answer, which you cannot see.\n\n"
        f"{context}\n\n"
        f"Question: {query}\n\n"
        "Report what the posters say, using only these posts.\n"
        "- Start with the majority view and how many posts support it (for example "
        "\"2 of 4 posts\"). If there is no majority, say the posts differ.\n"
        "- Then give meaningful disagreement and any house rules, labelled as house "
        "rules.\n"
        "- Where an answer depends on a step, phase or timing, give the order the "
        "poster describes. Do not work out the order yourself.\n"
        "- When a post quotes or paraphrases a rule, say the poster is quoting it. "
        "Never write \"the rules say\" or present anything as official.\n"
        "- Cite [n] after each claim, only with numbers from this list, using the "
        "post that makes the claim.\n"
        "- Do not use earlier turns as sources. If the posts do not answer the "
        "question, say so in one sentence."
    )

    messages: list[dict] = [{"role": "system", "content": COMMUNITY_SYSTEM}]
    user_turns = [
        turn
        for turn in (history or [])
        if turn.get("role") == "user" and (turn.get("content") or "").strip()
    ][-4:]
    for turn in user_turns:
        messages.append(
            {"role": "user", "content": turn["content"].strip()[:3000]}
        )
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

        if result.get("source_type") in {"bgg", "reddit"}:
            source = "BGG FORUM" if result.get("source_type") == "bgg" else "REDDIT"
            site = "community post" if source == "BGG FORUM" else "Reddit post"
            lines.append(
                f"- **{number}.** **{source}** "
                f"[{_escape_markdown(document['title'])}]({result.get('url') or ''})"
                f" — *{_escape_markdown(game['title'])}* · unofficial {site}"
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
