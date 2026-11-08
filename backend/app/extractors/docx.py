"""DOCX extraction, grouped by heading for readable citations."""

from __future__ import annotations

from app.extractors.base import ExtractedPage, ExtractionError
from app.extractors.registration import register_extractor


def extract_docx(path: str) -> list[ExtractedPage]:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("DOCX support is not installed in this build.") from exc

    try:
        document = docx.Document(path)
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Could not read DOCX: {exc}") from exc

    sections: list[tuple[str, list[str]]] = []
    current_title = "Document"
    current: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style else ""
        if style.startswith("heading") or style == "title":
            if current:
                sections.append((current_title, current))
            current_title = text
            current = []
        else:
            current.append(text)

    if current:
        sections.append((current_title, current))
    if not sections:
        raise ExtractionError("This DOCX contains no readable text.")

    return [
        ExtractedPage(number=index, text="\n\n".join(lines), label=title)
        for index, (title, lines) in enumerate(sections, start=1)
    ]


register_extractor(
    ["docx"],
    "Word document",
    extract_docx,
    description="Grouped by heading.",
)
