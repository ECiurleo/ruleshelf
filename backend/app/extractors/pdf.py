"""PDF text extraction with PyMuPDF (fast, no external binaries)."""

from __future__ import annotations

from app.extractors.base import ExtractedPage, ExtractionError
from app.extractors.registration import register_extractor


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
        pages: list[ExtractedPage] = []
        for index, page in enumerate(doc, start=1):
            # "text" is faster; fall back to blocks for awkward layouts.
            text = page.get_text("text") or ""
            if not text.strip():
                text = " ".join(
                    block[4] for block in page.get_text("blocks") if len(block) > 4
                )
            pages.append(ExtractedPage(number=index, text=text))
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
