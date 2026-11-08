"""Unit tests for cleaning, chunking and query building."""

from __future__ import annotations

from app.extractors import ExtractedPage
from app.services.chunking import prepare_pages, split_text
from app.services.search import build_match_query


def test_split_text_respects_size_and_keeps_content():
    text = " ".join(f"Sentence number {i} about rules and dice." for i in range(120))
    chunks = split_text(text, size=300, overlap=40)
    assert len(chunks) > 1
    assert all(len(chunk) <= 320 for chunk in chunks)
    # Every sentence appears somewhere in the output.
    joined = " ".join(chunks)
    for i in range(120):
        assert f"Sentence number {i}" in joined


def test_split_text_handles_single_long_word():
    chunks = split_text("x" * 5000, size=400, overlap=50)
    assert len(chunks) > 1


def test_dehyphenation_and_header_stripping():
    pages = [
        ExtractedPage(
            number=i,
            text=(
                "Warhammer Fantasy\n"
                f"Combat rules for {chr(96 + i)} with a hyphen-\nated word.\n"
                f"A second unique line about magic {chr(96 + i)}.\n"
                f"A third unique line about beasts {chr(96 + i)}.\n"
                "42"
            ),
        )
        for i in range(1, 9)
    ]
    cleaned = prepare_pages(pages)
    assert "hyphenated" in cleaned[0].text
    assert "Warhammer Fantasy" not in cleaned[0].text
    assert "42" not in cleaned[0].text
    assert "Combat rules for a" in cleaned[0].text


def test_build_match_query_drops_stopwords_and_keeps_phrases():
    match = build_match_query("What happens when a wizard miscasts?")
    assert '"wizard"' in match
    assert '"miscasts"*' in match
    assert '"a"' not in match
    assert build_match_query('"exact phrase" charge') == '"exact phrase" AND "charge"*'


def test_build_match_query_empty():
    assert build_match_query("   ") == ""
