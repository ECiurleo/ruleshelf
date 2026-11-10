"""Unit tests for OCR sizing and normalisation (no Tesseract required)."""

from __future__ import annotations

from app.services.ocr import (
    MAX_OCR_SIDE,
    _scale_for,
    is_image_file,
    normalise_effort,
    normalise_language,
    ocr_supported,
)


def test_render_scale_is_capped_for_large_pages():
    # A normal A4 page at 300 dpi renders at its natural scale.
    assert _scale_for(595, 842, 300) == 300 / 72
    # A huge map page is capped so Tesseract never sees an oversized image.
    scale = _scale_for(4000, 3000, 300)
    assert 4000 * scale <= MAX_OCR_SIDE + 0.01
    assert 3000 * scale <= MAX_OCR_SIDE
    assert scale < 300 / 72


def test_ocr_normalisation_helpers():
    assert normalise_effort("LOW") == "low"
    assert normalise_effort("high") == "high"
    assert normalise_effort("nonsense") == "medium"
    assert normalise_effort(None) == "medium"
    assert normalise_language("ENG+DEU") == "eng+deu"
    assert normalise_language("") == "eng"
    assert ocr_supported("map.PNG")
    assert ocr_supported("book.pdf")
    assert is_image_file("map.PNG")
    assert not is_image_file("book.pdf")
