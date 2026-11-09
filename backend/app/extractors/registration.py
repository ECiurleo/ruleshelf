"""Extractor registry implementation (kept separate to avoid import cycles)."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from app.extractors.base import ExtractedPage, ExtractionError, Extractor


@dataclass(slots=True)
class ExtractorSpec:
    extensions: tuple[str, ...]
    label: str
    func: Extractor
    description: str = ""
    # False for files that are stored and previewed but never text-indexed
    # (maps, handouts and other images).
    indexed: bool = True


_EXTRACTORS: dict[str, ExtractorSpec] = {}


def register_extractor(
    extensions: list[str] | tuple[str, ...],
    label: str,
    func: Extractor,
    description: str = "",
    indexed: bool = True,
) -> None:
    spec = ExtractorSpec(
        extensions=tuple(ext.lower().lstrip(".") for ext in extensions),
        label=label,
        func=func,
        description=description,
        indexed=indexed,
    )
    for ext in spec.extensions:
        _EXTRACTORS[ext] = spec


def _discover() -> None:
    if _EXTRACTORS:
        return
    import app.extractors as package

    for module in pkgutil.iter_modules(package.__path__):
        if module.name.startswith("_") or module.name in {"base", "registration"}:
            continue
        importlib.import_module(f"{package.__name__}.{module.name}")


def supported_extensions() -> list[dict]:
    _discover()
    seen: dict[tuple[str, ...], ExtractorSpec] = {}
    for spec in _EXTRACTORS.values():
        seen[spec.extensions] = spec
    return [
        {
            "extensions": list(spec.extensions),
            "label": spec.label,
            "description": spec.description,
            "indexed": spec.indexed,
        }
        for spec in sorted(seen.values(), key=lambda s: s.label)
    ]


def resolve_extension(filename: str) -> str:
    _discover()
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in _EXTRACTORS:
        allowed = ", ".join(sorted(f".{e}" for e in _EXTRACTORS))
        raise ExtractionError(
            f"Unsupported file type '.{ext}'. Supported: {allowed or 'none'}."
        )
    return ext


def is_indexed(filename: str) -> bool:
    """Whether this file type is text-indexed (images are stored only)."""
    _discover()
    ext = Path(filename).suffix.lower().lstrip(".")
    spec = _EXTRACTORS.get(ext)
    return spec.indexed if spec else True


def extract_file(path: str | Path, original_filename: str | None = None) -> list[ExtractedPage]:
    _discover()
    name = original_filename or str(path)
    ext = Path(name).suffix.lower().lstrip(".")
    spec = _EXTRACTORS.get(ext)
    if not spec:
        resolve_extension(name)  # raises with a helpful message
        raise ExtractionError("Unsupported file type.")  # pragma: no cover
    pages = spec.func(str(path))
    pages = [p for p in pages if p.text and p.text.strip()]
    if not pages:
        raise ExtractionError(
            "No text could be extracted. If this is a scanned book, run OCR on it "
            "first (for example with ocrmypdf) and upload the searchable PDF."
        )
    return pages
