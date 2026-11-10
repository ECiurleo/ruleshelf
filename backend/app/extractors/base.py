"""Document extraction primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class ExtractionError(Exception):
    """User-facing extraction failure."""


@dataclass(slots=True)
class ExtractedPage:
    """One citable unit.

    Pages are natural for PDFs and EPUB chapters; other formats use a single
    page and rely on chunking. ``number`` may be None when the format has no
    stable pagination.
    """

    number: int | None
    text: str
    label: str = ""
    # The page number printed in the book, when it differs from the PDF index.
    printed: str = ""


Extractor = Callable[[str], list[ExtractedPage]]


def mark_html_headings(soup) -> None:
    """Turn <h1>-<h4> into Markdown heading lines so chunking can track sections."""
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        title = " ".join(tag.get_text(" ").split())
        if title:
            tag.replace_with(f"\n{'#' * int(tag.name[1])} {title}\n")
        else:
            tag.decompose()
