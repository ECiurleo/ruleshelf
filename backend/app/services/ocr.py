"""Local optical character recognition with Tesseract via PyMuPDF.

OCR is opt-in per document and can also run automatically on upload (the
``auto_ocr`` setting). Tesseract is installed in the container; development
machines without it simply get ``ocr_available() == False`` and the UI hides
the action.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from app.extractors.base import ExtractedPage, ExtractionError

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "eng"
OCR_DPI = 300
OCR_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
}

# Debian installs tessdata here; PyMuPDF picks it up via TESSDATA_PREFIX.
_TESSDATA_CANDIDATES = (
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
)


@lru_cache(maxsize=1)
def ocr_available() -> bool:
    return bool(shutil.which("tesseract"))


@lru_cache(maxsize=1)
def ocr_languages() -> list[str]:
    binary = shutil.which("tesseract")
    if not binary:
        return []
    try:
        result = subprocess.run(
            [binary, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env specific
        return []
    lines = [line.strip() for line in result.stdout.splitlines()]
    return sorted(line for line in lines[1:] if line and " " not in line)


def ocr_supported(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in OCR_EXTENSIONS


def is_image_file(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in (OCR_EXTENSIONS - {".pdf"})


def normalise_language(language: str | None) -> str:
    value = (language or "").strip().lower()
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "+_-")
    return cleaned or DEFAULT_LANGUAGE


def _ensure_tessdata() -> None:
    if os.environ.get("TESSDATA_PREFIX"):
        return
    for candidate in _TESSDATA_CANDIDATES:
        if Path(candidate).is_dir():
            os.environ["TESSDATA_PREFIX"] = candidate
            return


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover - older PyMuPDF
        import fitz  # type: ignore[no-redef]
    return fitz


def ocr_file(
    path: str | Path,
    original_filename: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> list[ExtractedPage]:
    """Return OCR text for a PDF or image, one ExtractedPage per page."""
    if not ocr_available():
        raise ExtractionError(
            "OCR is not available in this build. Install Tesseract and restart."
        )
    _ensure_tessdata()
    fitz = _fitz()
    name = original_filename or str(path)
    suffix = Path(name).suffix.lower()
    lang = normalise_language(language)
    pages: list[ExtractedPage] = []
    doc = None
    try:
        if suffix == ".pdf":
            doc = fitz.open(str(path))
        else:
            doc = fitz.open(stream=Path(path).read_bytes(), filetype=None)
        for index, page in enumerate(doc, start=1):
            textpage = page.get_textpage_ocr(language=lang, dpi=OCR_DPI, full=True)
            text = page.get_text("text", textpage=textpage) or ""
            pages.append(ExtractedPage(number=index, text=text))
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - PyMuPDF/Tesseract raise many types
        raise ExtractionError(
            f"OCR failed ({lang}): {exc}. Check that the language data is installed."
        ) from exc
    finally:
        if doc is not None:
            doc.close()
    return pages
