"""Cover thumbnails for uploaded documents.

PDFs use their first page; EPUBs use the declared cover image (falling back to
the first image). Everything else gets a generated typographic card. Images are
cached under ``/data/thumbnails`` and regenerated on re-index.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.config import THUMBNAILS_DIR

log = logging.getLogger(__name__)

THUMB_WIDTH = 480
JPEG_QUALITY = 82
PLACEHOLDER_WIDTH = 480
PLACEHOLDER_HEIGHT = 640


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:  # older PyMuPDF
        import fitz  # type: ignore[no-redef]
    return fitz


def thumbnail_path(document_id: str) -> Path:
    return THUMBNAILS_DIR / f"{document_id}.jpg"


def delete_thumbnail(document_id: str) -> None:
    thumbnail_path(document_id).unlink(missing_ok=True)


def _encode_pdf_page(path: Path) -> bytes:
    fitz = _fitz()
    doc = fitz.open(str(path))
    try:
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
        page = doc[0]
        scale = THUMB_WIDTH / max(page.rect.width, 1)
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB
        )
        return pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    finally:
        doc.close()


def _encode_image_bytes(data: bytes) -> bytes:
    fitz = _fitz()
    doc = fitz.open(stream=data, filetype=None)
    try:
        if doc.page_count == 0:
            raise ValueError("image has no pages")
        page = doc[0]
        scale = min(THUMB_WIDTH / max(page.rect.width, 1), 2.0)
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB
        )
        return pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    finally:
        doc.close()


def _epub_cover(path: Path) -> bytes:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path))
    candidates: list[bytes] = []
    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        candidates.append(item.get_content())

    if not candidates:
        for value, attrs in book.get_metadata("OPF", "cover"):
            item_id = attrs.get("content") if attrs else value
            item = book.get_item_with_id(item_id) if item_id else None
            if item is not None:
                candidates.append(item.get_content())

    images = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
    if not candidates:
        for item in images:
            if "cover" in (item.get_name() or "").lower():
                candidates.append(item.get_content())
                break
    if not candidates and images:
        candidates.append(images[0].get_content())

    for data in candidates:
        try:
            return _encode_image_bytes(data)
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
    raise ValueError("no usable cover image in EPUB")


def _placeholder(row) -> bytes:
    fitz = _fitz()
    title = (row["title"] or "Untitled").strip()
    role = (row["role"] or "").replace("_", " ").title()
    filename = row["original_filename"] or ""
    extension = Path(filename).suffix.lstrip(".").upper() or "FILE"

    doc = fitz.open()
    try:
        page = doc.new_page(width=PLACEHOLDER_WIDTH, height=PLACEHOLDER_HEIGHT)
        page.draw_rect(page.rect, color=None, fill=(0.065, 0.075, 0.09))
        page.draw_rect(
            fitz.Rect(0, 0, PLACEHOLDER_WIDTH, 10), color=None, fill=(0.88, 0.60, 0.37)
        )
        page.draw_rect(
            fitz.Rect(56, 92, 424, 430),
            color=(0.20, 0.23, 0.28),
            fill=(0.11, 0.13, 0.16),
            width=2,
        )
        page.draw_line(
            fitz.Point(80, 120), fitz.Point(400, 120), color=(0.88, 0.60, 0.37), width=2
        )

        rect = fitz.Rect(82, 150, 398, 330)
        for size in (26, 22, 18, 15):
            if page.insert_textbox(
                rect,
                title,
                fontsize=size,
                fontname="helv",
                color=(0.92, 0.90, 0.86),
                lineheight=1.25,
            ) >= 0:
                break

        if role:
            page.insert_textbox(
                fitz.Rect(82, 344, 398, 380),
                role,
                fontsize=12,
                fontname="helv",
                color=(0.88, 0.60, 0.37),
            )
        page.insert_textbox(
            fitz.Rect(82, 560, 398, 580),
            "RULESHELF",
            fontsize=9,
            fontname="helv",
            color=(0.48, 0.53, 0.60),
        )
        page.insert_textbox(
            fitz.Rect(82, 580, 398, 602),
            extension,
            fontsize=9,
            fontname="helv",
            color=(0.48, 0.53, 0.60),
        )
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False, colorspace=fitz.csRGB)
        return pixmap.tobytes("jpeg", jpg_quality=85)
    finally:
        doc.close()


def render_thumbnail(row) -> bytes:
    path = Path(row["stored_name"]) if row["stored_name"] else None
    source = None
    if path:
        from app.config import FILES_DIR

        source = FILES_DIR / path.name
    extension = Path(row["original_filename"] or "").suffix.lower()

    if source and source.exists() and extension == ".pdf":
        try:
            return _encode_pdf_page(source)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not render PDF cover for %s: %s", row["id"], exc)
    if source and source.exists() and extension == ".epub":
        try:
            return _epub_cover(source)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not extract EPUB cover for %s: %s", row["id"], exc)

    return _placeholder(row)


def ensure_thumbnail(row, force: bool = False) -> Path | None:
    target = thumbnail_path(row["id"])
    if target.exists() and not force:
        return target
    try:
        data = render_thumbnail(row)
    except Exception as exc:  # noqa: BLE001 - never block the document
        log.warning("Thumbnail generation failed for %s: %s", row["id"], exc)
        return None

    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return target
