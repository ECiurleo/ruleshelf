"""EPUB extraction, one citable unit per spine document (chapter)."""

from __future__ import annotations

from app.extractors.base import ExtractedPage, ExtractionError, mark_html_headings
from app.extractors.registration import register_extractor


def extract_epub(path: str) -> list[ExtractedPage]:
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("EPUB support is not installed in this build.") from exc

    try:
        book = epub.read_epub(path, options={"ignore_ncx": False})
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Could not read EPUB: {exc}") from exc

    # Map hrefs to human titles from the table of contents.
    titles: dict[str, str] = {}
    for item in book.toc:
        if isinstance(item, tuple):
            section, children = item
            href = (section.href or "").split("#")[0]
            titles[href] = section.title or ""
            for child in children:
                titles[(child.href or "").split("#")[0]] = child.title or ""
        else:
            titles[(item.href or "").split("#")[0]] = item.title or ""

    pages: list[ExtractedPage] = []
    number = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_content()
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        mark_html_headings(soup)
        text = soup.get_text("\n")
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not text.strip():
            continue
        number += 1
        href = (item.get_name() or "").split("#")[0]
        title = titles.get(href) or href
        pages.append(ExtractedPage(number=number, text=text, label=title))

    if not pages:
        raise ExtractionError("This EPUB has no readable chapters.")
    return pages


register_extractor(
    ["epub"],
    "EPUB",
    extract_epub,
    description="One citable unit per chapter.",
)
