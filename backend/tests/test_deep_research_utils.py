"""Tests for deep-research text utilities, focused on source-preserving truncation."""

from app.engine.deep_research.utils import (
    format_sources_block,
    sources_to_entries,
    truncate_preserving_sources,
)


def test_short_text_passes_through_unchanged():
    text = "nothing to truncate here"
    assert truncate_preserving_sources(text, 1000) == text


def test_preserves_every_source_across_concatenated_notes():
    # Two rounds of notes; their combined structured sources must all survive.
    note_a = "Round A findings " + "a" * 4000
    note_b = "Round B findings " + "b" * 4000
    sources = [
        {"title": "A", "url": "http://a.com/one"},
        {"title": "B", "url": "http://b.com/two"},
    ]
    out = truncate_preserving_sources(note_a + "\n" + note_b, 1500, sources=sources)

    assert len(out) <= 1500
    assert "http://a.com/one" in out
    assert "http://b.com/two" in out
    assert "truncated for length" in out


def test_footer_contains_the_full_unbroken_url():
    text = "Findings. " * 500
    sources = [{"title": "Article", "url": "http://example.com/article"}]
    out = truncate_preserving_sources(text, 400, sources=sources)
    assert len(out) <= 400
    assert "http://example.com/article" in out


def test_sources_only_when_budget_too_small_for_body():
    text = "x" * 5000
    sources = [
        {"title": "", "url": "http://a.com/one"},
        {"title": "", "url": "http://b.com/two"},
    ]
    out = truncate_preserving_sources(text, 60, sources=sources)
    assert "http://a.com/one" in out
    # No room for narrative; should be just the sources footer.
    assert out.startswith("### Sources")


def test_no_sources_truncates_on_boundary():
    text = "First paragraph.\n\n" + "y" * 5000
    out = truncate_preserving_sources(text, 200)
    assert len(out) <= 200
    assert out.rstrip().endswith("[...truncated for length]")


def test_too_many_sources_reports_omitted_count():
    sources = [
        {"title": "", "url": f"http://example.com/path-number-{i}"} for i in range(50)
    ]
    out = truncate_preserving_sources("body " + "b" * 2000, 300, sources=sources)
    assert len(out) <= 300
    assert "more source(s) omitted" in out
    assert "http://example.com/path-number-0" in out


def test_sources_to_entries_dedupes_by_url_and_includes_title():
    sources = [
        {"title": "First", "url": "http://a.com/1"},
        {"title": "Dup", "url": "http://a.com/1"},
        {"title": "", "url": "http://b.com/2"},
        "http://c.com/3",
        {"title": "No url", "url": ""},
        {"not": "a url"},
    ]
    assert sources_to_entries(sources) == [
        "First — http://a.com/1",
        "http://b.com/2",
        "http://c.com/3",
    ]


def test_format_sources_block_numbers_sequentially():
    block = format_sources_block(
        [{"title": "T", "url": "http://a.com/1"}, {"title": "", "url": "http://b.com/2"}]
    )
    assert block == "### Sources\n[1] T — http://a.com/1\n[2] http://b.com/2\n"
    assert format_sources_block([]) == ""
    assert format_sources_block(None) == ""


def test_structured_sources_are_authoritative():
    # The body text contains a misleading/garbled URL; the structured sources are
    # the authoritative list and must be what ends up in the footer.
    text = "Body mentions http://garbled-in-text.example " + "z" * 4000
    sources = [
        {"title": "Real Source", "url": "http://authoritative.example/article"},
    ]
    out = truncate_preserving_sources(text, 800, sources=sources)
    assert len(out) <= 800
    # The footer is built only from structured sources (no regex harvesting):
    # the authoritative URL appears, the garbled in-text one never does.
    footer = out.split("### Sources", 1)[1]
    assert "http://authoritative.example/article" in footer
    assert "Real Source" in footer
    assert "garbled-in-text" not in footer
