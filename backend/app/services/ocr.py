"""Local optical character recognition with Tesseract.

OCR is opt-in per document and can also run automatically on upload (the
``auto_ocr`` setting). The ``ocr_cpu`` setting trades speed for CPU:

- low:    200 dpi, one page at a time, a short pause between pages
- medium: 300 dpi, one page at a time
- high:   300 dpi, up to four pages in parallel

PyMuPDF renders PDF pages to images and the Tesseract command-line tool reads
them. Using separate processes matters: Tesseract's Leptonica is not thread-safe
inside one process, but independent processes are. Only one document is OCR'd at
a time across the server, so a queue cannot saturate the CPU.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from app.extractors.base import ExtractedPage, ExtractionError

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "eng"
EFFORT_LEVELS = ("low", "medium", "high")
OCR_EFFORT = {
    "low": {"dpi": 200, "workers": 1, "pause": 0.15},
    "medium": {"dpi": 300, "workers": 1, "pause": 0.0},
    "high": {"dpi": 300, "workers": 4, "pause": 0.0},
}
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

# One document at a time, regardless of effort. High effort parallelises pages
# *within* the document instead of running several documents at once.
_OCR_LOCK = threading.Lock()


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


def normalise_effort(effort: str | None) -> str:
    value = (effort or "").strip().lower()
    return value if value in OCR_EFFORT else "medium"


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover - older PyMuPDF
        import fitz  # type: ignore[no-redef]
    return fitz


def _tesseract_image(image: str | Path, language: str, dpi: int) -> str:
    binary = shutil.which("tesseract")
    if not binary:  # pragma: no cover - guarded by ocr_available
        raise ExtractionError("OCR is not available in this build.")
    command = [binary, str(image), "stdout", "-l", language]
    if dpi:
        command += ["--dpi", str(dpi)]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=600, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExtractionError(f"OCR failed ({language}): {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit code {result.returncode}"
        raise ExtractionError(f"OCR failed ({language}): {message}")
    return result.stdout or ""


def _ocr_pdf(
    path: str | Path, language: str, dpi: int, workers: int, pause: float
) -> list[ExtractedPage]:
    """Render pages one batch at a time and OCR them with Tesseract processes.

    Rendering stays on one thread (PyMuPDF documents are not thread-safe) and
    only ``workers`` page images exist on disk at once. Tesseract itself runs in
    separate processes, which is safe to parallelise.
    """
    fitz = _fitz()
    doc = fitz.open(str(path))
    try:
        count = doc.page_count
        if not count:
            return []
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        texts: list[str] = []
        with tempfile.TemporaryDirectory(prefix="ruleshelf-ocr-") as temporary:
            directory = Path(temporary)
            with ThreadPoolExecutor(
                max_workers=min(workers, os.cpu_count() or 1)
            ) as pool:
                for start_index in range(0, count, workers):
                    images: list[Path] = []
                    for index in range(
                        start_index, min(start_index + workers, count)
                    ):
                        if pause:
                            time.sleep(pause)
                        pixmap = doc[index].get_pixmap(
                            matrix=matrix, alpha=False, colorspace=fitz.csRGB
                        )
                        image = directory / f"page-{index + 1:04d}.png"
                        pixmap.save(str(image))
                        images.append(image)
                    if workers > 1:
                        texts.extend(
                            pool.map(
                                lambda image: _tesseract_image(image, language, dpi),
                                images,
                            )
                        )
                    else:
                        texts.append(_tesseract_image(images[0], language, dpi))
                    for image in images:
                        image.unlink(missing_ok=True)
    finally:
        doc.close()
    return [
        ExtractedPage(number=index + 1, text=text)
        for index, text in enumerate(texts)
    ]


def ocr_file(
    path: str | Path,
    original_filename: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    effort: str = "medium",
) -> list[ExtractedPage]:
    """Return OCR text for a PDF or image, one ExtractedPage per page."""
    if not ocr_available():
        raise ExtractionError(
            "OCR is not available in this build. Install Tesseract and restart."
        )
    name = original_filename or str(path)
    suffix = Path(name).suffix.lower()
    lang = normalise_language(language)
    settings = OCR_EFFORT[normalise_effort(effort)]
    try:
        with _OCR_LOCK:
            if suffix == ".pdf":
                return _ocr_pdf(
                    path,
                    lang,
                    settings["dpi"],
                    settings["workers"],
                    settings["pause"],
                )
            text = _tesseract_image(path, lang, settings["dpi"])
            return [ExtractedPage(number=1, text=text)]
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - rendering/subprocess raise many types
        raise ExtractionError(
            f"OCR failed ({lang}): {exc}. Check that the language data is installed."
        ) from exc
