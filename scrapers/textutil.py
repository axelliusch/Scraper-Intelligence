from __future__ import annotations

import html.parser
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from social_base import utcnow


class TextExtractor(html.parser.HTMLParser):
    """Collect visible text, turning block elements into paragraph breaks."""

    _BLOCK_TAGS = frozenset(
        {
            "p", "div", "br", "li", "tr", "section", "article", "blockquote",
            "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")
        if tag.startswith("img"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data.replace("\xa0", " "))

    def text(self) -> str:
        joined = "".join(self._parts)
        joined = re.sub(r"[ \t]+", " ", joined)  # collapse horizontal whitespace
        joined = re.sub(r" *\n *", "\n", joined)  # trim spaces around line breaks
        joined = re.sub(r"\n{3,}", "\n\n", joined)  # collapse blank runs
        return joined.strip()


def html_to_text(markup: str | None) -> str:
    """Strip HTML markup to plain text (paragraph breaks preserved)."""
    if not markup:
        return ""
    extractor = TextExtractor()
    extractor.feed(markup)
    extractor.close()
    return extractor.text()


def normalize_ts(value: str | None) -> str:
    """Normalize RFC 2822 / ISO 8601 timestamps to UTC 'Z' strings.

    Unparseable values fall back to collection time, mirroring the reference
    last30days adapter (never drops the required `timestamp` field).
    """
    raw = (value or "").strip()
    if not raw:
        return utcnow()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):  # date-only -> UTC midnight
        return f"{raw}T00:00:00Z"
    try:  # ISO 8601 (Atom / JSON Feed), accepts trailing 'Z' on Python 3.11+
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass
    try:  # RFC 2822 (RSS pubDate, e.g. "Mon, 15 Aug 2026 12:00:00 GMT")
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        return utcnow()


def safe_author_name(value: str, fallback_title: str) -> str:
    """Extract a display name; drop emails (schema §3 forbids storing emails)."""
    name = re.sub(r"[\w.+-]+@[\w.-]+\.[\w.]+", "", (value or "")).strip(" <>\t()")
    name = re.sub(r"\s+", " ", name).strip()
    if name:
        return name
    if fallback_title.strip():
        return fallback_title.strip()
    return "web feed"