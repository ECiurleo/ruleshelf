"""Plain text and Markdown. A form feed (\\f) starts a new page."""

from __future__ import annotations

from pathlib import Path

from app.extractors.base import ExtractedPage, ExtractionError
from app.extractors.registration import register_extractor


def _read_text(path: str) -> str:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Could not decode this text file.")


def extract_text(path: str) -> list[ExtractedPage]:
    text = _read_text(path)
    if not text.strip():
        raise ExtractionError("This file is empty.")
    parts = text.split("\f")
    if len(parts) == 1:
        return [ExtractedPage(number=1, text=text)]
    return [
        ExtractedPage(number=index, text=part)
        for index, part in enumerate(parts, start=1)
        if part.strip()
    ]


register_extractor(
    ["txt", "md", "markdown", "text", "rst"],
    "Text / Markdown",
    extract_text,
    description="Plain text, Markdown and reStructuredText.",
)
