"""PDF text extraction with PyMuPDF (fast, no external binaries)."""

from __future__ import annotations

import re
from collections import Counter

from app.extractors.base import ExtractedPage, ExtractionError
from app.extractors.registration import register_extractor

# A line counts as a heading when its font is clearly larger than body text.
HEADING_RATIO = 1.18
MAX_HEADING_LEVELS = 3
MAX_HEADING_CHARS = 90
MAX_HEADING_WORDS = 12


def _squash(text: str) -> str:
    return " ".join(text.split())


def _page_lines(page, flags) -> list[tuple[str, float, int]]:
    """(text, largest font size, character count) for each visual line."""
    lines: list[tuple[str, float, int]] = []
    data = page.get_text("dict", flags=flags) if flags is not None else page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = _squash("".join(span.get("text", "") for span in line.get("spans", [])))
            size = max(float(span.get("size", 0) or 0) for span in spans)
            lines.append((text, size, sum(len(span["text"].strip()) for span in spans)))
    return lines


def _is_heading_text(text: str) -> bool:
    return (
        3 <= len(text) <= MAX_HEADING_CHARS
        and len(text.split()) <= MAX_HEADING_WORDS
        and re.search(r"[^\W\d_]", text) is not None
        and not text.endswith((".", ",", ";"))
    )


def _heading_levels(all_lines: list[list[tuple[str, float, int]]]) -> tuple[float, dict[float, int]]:
    """Body font size and a level (1 = largest) for each heading font size."""
    weights: Counter[float] = Counter()
    for lines in all_lines:
        for _text, size, chars in lines:
            weights[round(size, 1)] += chars
    if not weights:
        return 0.0, {}
    body = weights.most_common(1)[0][0]
    heading_sizes = sorted(
        {
            round(size, 1)
            for lines in all_lines
            for text, size, _chars in lines
            if size >= body * HEADING_RATIO and _is_heading_text(text)
        },
        reverse=True,
    )
    return body, {
        size: min(index + 1, MAX_HEADING_LEVELS) for index, size in enumerate(heading_sizes)
    }


def _mark_headings(text: str, headings: dict[str, int]) -> str:
    if not headings:
        return text
    out: list[str] = []
    for line in text.splitlines():
        level = headings.get(_squash(line))
        out.append(f"{'#' * level} {line.strip()}" if level else line)
    return "\n".join(out)


def _printed_label(page, index: int) -> str:
    try:
        label = (page.get_label() or "").strip()
    except Exception:  # noqa: BLE001 - labels are optional metadata
        return ""
    return label if label and label != str(index) else ""


def extract_pdf(path: str) -> list[ExtractedPage]:
    try:
        try:
            import pymupdf as fitz  # current package name
        except ImportError:  # older PyMuPDF
            import fitz
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("PyMuPDF is not installed in this build.") from exc

    doc = None
    try:
        doc = fitz.open(path)
        flags = getattr(fitz, "TEXTFLAGS_TEXT", None)
        texts: list[str] = []
        labels: list[str] = []
        all_lines: list[list[tuple[str, float, int]]] = []
        for index, page in enumerate(doc, start=1):
            # "text" is faster; fall back to blocks for awkward layouts.
            text = page.get_text("text") or ""
            if not text.strip():
                text = " ".join(
                    block[4] for block in page.get_text("blocks") if len(block) > 4
                )
            texts.append(text)
            labels.append(_printed_label(page, index))
            all_lines.append(_page_lines(page, flags))

        body, levels = _heading_levels(all_lines)
        pages: list[ExtractedPage] = []
        for index, (text, label, lines) in enumerate(zip(texts, labels, all_lines), start=1):
            headings = {
                line_text: levels[round(size, 1)]
                for line_text, size, _chars in lines
                if body and round(size, 1) in levels and _is_heading_text(line_text)
            }
            pages.append(
                ExtractedPage(number=index, text=_mark_headings(text, headings), printed=label)
            )
        return pages
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises many types
        raise ExtractionError(f"Could not read PDF: {exc}") from exc
    finally:
        if doc is not None:
            doc.close()


register_extractor(
    ["pdf"],
    "PDF",
    extract_pdf,
    description="Text-layer PDFs. Scanned books need OCR first.",
)
