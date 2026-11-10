"""Standalone HTML files."""

from __future__ import annotations

from pathlib import Path

from app.extractors.base import ExtractedPage, ExtractionError, mark_html_headings
from app.extractors.registration import register_extractor


def extract_html(path: str) -> list[ExtractedPage]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("HTML support is not installed in this build.") from exc

    try:
        raw = Path(path).read_bytes().decode("utf-8", errors="replace")
        soup = BeautifulSoup(raw, "html.parser")
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Could not read HTML: {exc}") from exc

    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    mark_html_headings(soup)
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    if not text:
        raise ExtractionError("This HTML file contains no readable text.")
    return [ExtractedPage(number=1, text=text, label=soup.title.string if soup.title else "")]


register_extractor(["html", "htm"], "HTML", extract_html)
