"""Text cleaning and chunking.

Rulebooks repeat running headers on every page and PDF extraction breaks words
across lines; both hurt search relevance, so we strip them first.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.extractors import ExtractedPage

_DEHYPHENATE = re.compile(r"(\w)-\s*\n\s*(\w)")
_BLANK_RUN = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t\u00a0]+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;:])\s+|\n{2,}")
_HEADING = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*$")
_PAGE_NUMBER = re.compile(r"(?:page\s*)?(\d{1,4})", re.IGNORECASE)
MAX_SECTION_CHARS = 200


@dataclass(slots=True)
class Chunk:
    page: int | None
    printed: str
    section: str
    text: str


def _normalise(page: str) -> str:
    text = page.replace("\r\n", "\n").replace("\r", "\n")
    text = _DEHYPHENATE.sub(r"\1\2", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def _signature(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def strip_running_headers(pages: list[ExtractedPage]) -> list[ExtractedPage]:
    """Drop repeated headers/footers (including page numbers) when confident."""
    non_empty = [p for p in pages if p.text.strip()]
    if len(non_empty) < 5:
        return pages

    top_counts: Counter[str] = Counter()
    bottom_counts: Counter[str] = Counter()
    for page in non_empty:
        lines = [line for line in page.text.splitlines() if line.strip()]
        # Short pages are all edge; do not risk deleting their content.
        if len(lines) < 5:
            continue
        for signature in {_signature(line) for line in lines[:2]}:
            top_counts[signature] += 1
        for signature in {_signature(line) for line in lines[-2:]}:
            bottom_counts[signature] += 1

    threshold = max(3, math.ceil(len(non_empty) * 0.6))
    top_repeated = {sig for sig, count in top_counts.items() if count >= threshold}
    bottom_repeated = {sig for sig, count in bottom_counts.items() if count >= threshold}
    if not top_repeated and not bottom_repeated:
        return pages

    cleaned: list[ExtractedPage] = []
    for page in pages:
        lines = page.text.splitlines()
        printed = page.printed
        removed: list[str] = []
        while lines and _signature(lines[0]) in top_repeated:
            removed.append(lines.pop(0))
        while lines and _signature(lines[-1]) in bottom_repeated:
            removed.append(lines.pop())
        if not printed:
            for line in removed:
                match = _PAGE_NUMBER.fullmatch(line.strip())
                if match:
                    printed = match.group(1)
                    break
        cleaned.append(
            ExtractedPage(
                number=page.number, text="\n".join(lines), label=page.label, printed=printed
            )
        )
    return cleaned


def prepare_pages(pages: list[ExtractedPage]) -> list[ExtractedPage]:
    normalised = [
        ExtractedPage(
            number=p.number, text=_normalise(p.text), label=p.label, printed=p.printed
        )
        for p in pages
    ]
    normalised = [p for p in normalised if p.text]
    return strip_running_headers(normalised)


def _hard_split(text: str, size: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > size:
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:size])
            word = word[size:]
        if not current:
            current = word
        elif len(current) + len(word) + 1 <= size:
            current = f"{current} {word}"
        else:
            parts.append(current)
            current = word
    if current:
        parts.append(current)
    return parts


def split_text(text: str, size: int = 1100, overlap: int = 160) -> list[str]:
    """Split into overlapping, sentence-aligned windows of at most ``size``."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    units: list[str] = []
    for piece in _SENTENCE_BOUNDARY.split(text):
        if not piece or not piece.strip():
            continue
        piece = piece.strip()
        if len(piece) <= size:
            units.append(piece)
        else:
            units.extend(_hard_split(piece, size))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        if len(current) + len(unit) + 1 <= size:
            current = f"{current} {unit}"
            continue
        chunks.append(current.strip())
        tail = current[-overlap:] if overlap > 0 else ""
        if tail:
            space = tail.find(" ")
            if space != -1:
                tail = tail[space + 1 :]
        current = f"{tail} {unit}".strip() if tail else unit

    if current.strip():
        chunks.append(current.strip())
    # A pathological overlap can produce empty/duplicate tails; keep text only.
    return [chunk for chunk in chunks if chunk]


def with_section(section: str, text: str) -> str:
    """Chunk text prefixed with its heading breadcrumb, for search indexes."""
    return f"{section}\n{text}" if section else text


def _section_name(stack: list[str]) -> str:
    name = " > ".join(stack)
    return name if len(name) <= MAX_SECTION_CHARS else "…" + name[-(MAX_SECTION_CHARS - 1) :]


def chunk_pages(
    pages: list[ExtractedPage], size: int = 1100, overlap: int = 160
) -> list[Chunk]:
    """Split pages into chunks that never cross a heading.

    Headings arrive as Markdown lines (``## Charge Reactions``). Each chunk is
    tagged with the heading breadcrumb in force, which carries across pages.
    """
    chunks: list[Chunk] = []
    stack: list[str] = []
    for page in pages:
        if page.label and page.label.strip():
            stack = [page.label.strip()]
        segments: list[tuple[str, list[str]]] = [(_section_name(stack), [])]
        has_body = False
        previous_level = 0
        for line in page.text.split("\n"):
            match = _HEADING.match(line.strip())
            if not match:
                segments[-1][1].append(line)
                if line.strip():
                    has_body = True
                previous_level = 0
                continue
            level = len(match.group(1))
            title = match.group(2).strip()
            if previous_level == level and stack:
                # A long heading wrapped onto the next line.
                stack[-1] = f"{stack[-1]} {title}"
            else:
                stack = stack[: level - 1] + [title]
            previous_level = level
            if has_body:
                segments.append((_section_name(stack), [title]))
                has_body = False
            else:
                # Consecutive headings (chapter, then section) share one segment.
                segments[-1] = (_section_name(stack), [*segments[-1][1], title])

        for section, lines in segments:
            text = "\n".join(lines).strip()
            for piece in split_text(text, size, overlap):
                chunks.append(Chunk(page.number, page.printed, section, piece))
    return chunks
