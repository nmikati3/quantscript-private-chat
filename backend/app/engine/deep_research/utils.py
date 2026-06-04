"""Utility functions for deep research without LangChain dependencies."""

import pandas as pd
from typing import List, Dict, Any, Optional

_TRUNCATION_MARKER = "\n\n[...truncated for length]\n\n"


def sources_to_entries(sources: Optional[List[Any]]) -> List[str]:
    """Normalise structured source records into de-duplicated citation labels.

    Accepts the structured records captured from the web-search results — each a
    ``{"title", "url"}`` dict (extra keys ignored) or a bare URL string — and
    returns ``"title — url"`` (or just ``"url"``) labels, de-duplicated by URL in
    first-seen order. This is the authoritative path: it relies on the URLs the
    search layer actually returned rather than re-parsing them out of prose.
    """
    if not sources:
        return []
    entries: List[str] = []
    seen = set()
    for source in sources:
        if isinstance(source, str):
            url, title = source.strip(), ""
        elif isinstance(source, dict):
            url = str(source.get("url", "")).strip()
            title = str(source.get("title", "")).strip()
        else:
            continue
        if not url or url in seen:
            continue
        seen.add(url)
        entries.append(f"{title} — {url}" if title else url)
    return entries


def format_sources_block(sources: Optional[List[Any]]) -> str:
    """Render a complete, sequentially-numbered Sources block from structured records.

    Returns an empty string when there are no usable sources. Unlike the footer
    used during truncation, this does not enforce a length budget — use it to
    guarantee an authoritative citation list in the final report input.
    """
    entries = sources_to_entries(sources)
    if not entries:
        return ""
    lines = "\n".join(f"[{i}] {entry}" for i, entry in enumerate(entries, 1))
    return f"### Sources\n{lines}\n"


def _truncate_on_boundary(text: str, max_chars: int) -> str:
    """Trim ``text`` to at most ``max_chars``, preferring a clean break.

    Tries to end on a paragraph, then line, then sentence boundary so the kept
    narrative is not severed mid-word. Falls back to a hard cut only when no
    boundary sits reasonably close to the limit.
    """
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    window = text[:max_chars]
    # Don't accept a boundary so early that we throw away most of the budget.
    floor = int(max_chars * 0.6)
    for separator in ("\n\n", "\n", ". "):
        idx = window.rfind(separator)
        if idx >= floor:
            # Keep the sentence-ending period; drop trailing newlines.
            end = idx + (1 if separator == ". " else 0)
            return window[:end].rstrip()
    return window.rstrip()


def _build_sources_footer(entries: List[str], max_chars: int) -> str:
    """Render a numbered, sequentially-cited Sources footer within ``max_chars``.

    ``entries`` are pre-formatted citation labels (e.g. ``"Title — url"`` or a
    bare URL). Keeps whole lines only (never a half entry). If the full list does
    not fit, retains as many leading sources as possible and appends a count of
    the rest.
    """
    header = "### Sources\n"
    if max_chars <= len(header):
        return ""

    lines: List[str] = []
    used = len(header)
    omitted = 0
    for i, entry in enumerate(entries, 1):
        line = f"[{i}] {entry}\n"
        if used + len(line) <= max_chars:
            lines.append(line)
            used += len(line)
        else:
            omitted += 1

    if omitted:
        note = f"[...{omitted} more source(s) omitted]\n"
        # Drop trailing whole lines until the omission note fits.
        while lines and used + len(note) > max_chars:
            used -= len(lines.pop())
            omitted += 1
            note = f"[...{omitted} more source(s) omitted]\n"
        if used + len(note) <= max_chars:
            lines.append(note)

    if not lines:
        return ""
    return header + "".join(lines)


def truncate_preserving_sources(
    text: str,
    max_chars: int,
    sources: Optional[List[Any]] = None,
) -> str:
    """Truncate ``text`` to ~``max_chars`` while retaining every source URL.

    Research findings carry a citation/source list (usually at the end) that the
    supervisor and final report depend on. A naive slice would drop those URLs —
    and when several rounds of notes are concatenated, only the last block would
    survive even if we tried to preserve "the" trailing section.

    ``sources`` are the structured ``{"title", "url"}`` records captured directly
    from the web-search results and used as the authoritative citation list. The
    body is truncated on a paragraph/line/sentence boundary and a single
    consolidated, sequentially numbered Sources footer is appended, so no URL is
    silently lost. When there are no sources, the body is simply truncated on a
    boundary (there are no citations to preserve).
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    entries = sources_to_entries(sources)
    if not entries:
        marker = _TRUNCATION_MARKER.rstrip() + "\n"
        return _truncate_on_boundary(text, max(0, max_chars - len(marker))) + marker

    footer = _build_sources_footer(entries, max_chars)
    body_budget = max_chars - len(footer) - len(_TRUNCATION_MARKER)
    if body_budget <= 0:
        # No room for narrative; the sources are the highest-priority content.
        return footer

    body = _truncate_on_boundary(text, body_budget)
    return body + _TRUNCATION_MARKER + footer

def get_today_str() -> str:
    """Get today's date as a string."""
    return str(pd.Timestamp.now())[:10]


def get_buffer_string(messages: List[Dict[str, Any]]) -> str:
    """Convert messages list to a string representation."""
    result = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            result.append(f"{role}: {content}")
    return "\n".join(result)


def is_token_limit_exceeded(error: Exception) -> bool:
    """Check if error is due to token limit exceeded."""
    error_str = str(error).lower()
    token_errors = [
        "token",
        "context length",
        "maximum context length",
        "exceeds maximum",
        "too many tokens"
    ]
    return any(term in error_str for term in token_errors)