"""Extractor registry — see ``registration.py`` for the implementation.

Adding a format: create ``app/extractors/<name>.py``, implement
``extract(path) -> list[ExtractedPage]`` and call ``register_extractor`` at
module level. Restart; the extension is accepted by uploads immediately.
"""

from __future__ import annotations

from app.extractors.base import ExtractedPage, ExtractionError, Extractor
from app.extractors.registration import (
    ExtractorSpec,
    extract_file,
    register_extractor,
    resolve_extension,
    supported_extensions,
)

__all__ = [
    "ExtractedPage",
    "ExtractionError",
    "Extractor",
    "ExtractorSpec",
    "extract_file",
    "register_extractor",
    "resolve_extension",
    "supported_extensions",
]
