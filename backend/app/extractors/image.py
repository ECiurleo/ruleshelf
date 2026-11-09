"""Image uploads: maps, handouts and photos.

These files are stored and previewed but deliberately not text-indexed — there
is no OCR step in the ingest pipeline. Marking them ``indexed=False`` keeps
them out of keyword/semantic search while still letting them live with the
scenario they belong to.
"""

from __future__ import annotations

from app.extractors.base import ExtractedPage
from app.extractors.registration import register_extractor


def extract_image(path: str) -> list[ExtractedPage]:  # pragma: no cover - never called
    return []


register_extractor(
    ["png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff"],
    "Image / map",
    extract_image,
    description="Maps, handouts and photos. Stored for browsing; run OCR first to make them searchable.",
    indexed=False,
)
