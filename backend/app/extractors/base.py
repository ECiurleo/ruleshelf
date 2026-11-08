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


Extractor = Callable[[str], list[ExtractedPage]]
