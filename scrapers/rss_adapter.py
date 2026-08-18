from __future__ import annotations

import html.parser
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from social_base import (
    Author,
    AuditLog,
    CollectionError,
    MediaItem,
    SocialCollector,
    SocialRecord,
    TargetValidator,
    TargetValidationError,
    utcnow,
)
from textutil import html_to_text, normalize_ts, safe_author_name

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "social" / "raw" / "rss"
DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "social" / "normalized"
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "social-audit.jsonl"

HTTP_TIMEOUT_SECONDS = 60

#: Example feed URL -> bundled offline fixture (used when target["mock"] is set).
MOCK_FEED_FIXTURES: dict[str, str] = {
    "https://example.test/feed.xml": "rss-sample.xml",
    "https://example.test/atom.xml": "atom-sample.xml",
    "https://example.test/feed.json": "jsonfeed-sample.json",
}

_SCHEME_RE = re.compile(r"^https?://")


# ---------------------------------------------------------------------------
# Feed normalization (RSS 2.0 / Atom / JSON Feed -> flat entry dicts)
# ---------------------------------------------------------------------------


@dataclass
class _FeedMeta:
    title: str = ""


@dataclass
class _FeedEntry:
    id: str | None = None
    title: str = ""
    url: str | None = None
    published: str | None = None
    updated: str | None = None
    author: str = ""
    text: str = ""
    media: list[MediaItem] = field(default_factory=list)


def _local(tag: str) -> str:
    """Namespaced tag name -> local name."""
    return tag.rsplit("}", 1)[-1]


def _find_local(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _findall_local(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in parent if _local(child.tag) == name]


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _entry_text(title: str, body: str) -> str:
    parts = [p for p in (title.strip(), body.strip()) if p]
    return "\n\n".join(parts)


def _mime_type(mime: str | None) -> str:
    prefix = (mime or "").split("/", 1)[0].lower()
    if prefix in ("image", "video", "audio"):
        return prefix
    return "link"


def _parse_rss(root: ET.Element, meta: _FeedMeta) -> list[_FeedEntry]:
    channel = _find_local(root, "channel")
    if channel is None:
        return []
    if not meta.title:
        meta.title = _text(_find_local(channel, "title"))
    entries: list[_FeedEntry] = []
    for item in _findall_local(channel, "item"):
        link = _text(_find_local(item, "link"))
        author = (
            _text(_find_local(item, "creator")) or _text(_find_local(item, "author"))
        )
        content_encoded = _text(_find_local(item, "encoded"))
        description = _text(_find_local(item, "description"))
        body = html_to_text(content_encoded or description)
        title = _text(_find_local(item, "title"))
        media: list[MediaItem] = []
        for enc in _findall_local(item, "enclosure"):
            url = enc.get("url")
            mime = enc.get("type")
            if url:
                media.append(MediaItem(type=_mime_type(mime), url=str(url), mime=mime))
        for content in _findall_local(item, "content"):
            url = content.get("url") or content.get("href")
            mime = content.get("type")
            if url:
                media.append(MediaItem(type=_mime_type(mime), url=str(url), mime=mime))
        entries.append(
            _FeedEntry(
                id=_text(_find_local(item, "guid")) or None,
                title=title,
                url=link or None,
                published=_text(_find_local(item, "pubDate")) or None,
                author=author,
                text=_entry_text(title, body),
                media=media,
            )
        )
    return entries


def _parse_atom(root: ET.Element, meta: _FeedMeta) -> list[_FeedEntry]:
    if not meta.title:
        meta.title = _text(_find_local(root, "title"))
    entries: list[_FeedEntry] = []
    for entry in _findall_local(root, "entry"):
        link = ""
        media: list[MediaItem] = []
        for node in _findall_local(entry, "link"):
            rel = node.get("rel")
            href = node.get("href")
            if href is None:
                continue
            if rel == "enclosure":
                mime = node.get("type")
                media.append(MediaItem(type=_mime_type(mime), url=str(href), mime=mime))
            elif rel in (None, "alternate", "self") and not link:
                link = href
        author_el = _find_local(entry, "author")
        author = ""
        if author_el is not None:
            author = _text(_find_local(author_el, "name"))
        title = _text(_find_local(entry, "title"))
        body = html_to_text(
            _text(_find_local(entry, "content")) or _text(_find_local(entry, "summary"))
        )
        entries.append(
            _FeedEntry(
                id=_text(_find_local(entry, "id")) or None,
                title=title,
                url=link or None,
                published=_text(_find_local(entry, "published")) or None,
                updated=_text(_find_local(entry, "updated")) or None,
                author=author,
                text=_entry_text(title, body),
                media=media,
            )
        )
    return entries


def _parse_json_feed(blob: dict[str, Any], meta: _FeedMeta) -> list[_FeedEntry]:
    if not meta.title:
        meta.title = str(blob.get("title") or "").strip()
    entries: list[_FeedEntry] = []
    for item in blob.get("items") or []:
        media: list[MediaItem] = []
        for att in item.get("attachments") or []:
            url = att.get("url")
            mime = att.get("mime_type")
            if url:
                media.append(
                    MediaItem(
                        type=_mime_type(mime),
                        url=str(url),
                        mime=mime,
                        duration=att.get("duration_in_seconds"),
                        title=att.get("title"),
                    )
                )
        author = ""
        authors = item.get("authors") or []
        if authors and isinstance(authors[0], dict):
            author = str(authors[0].get("name") or "")
        title = str(item.get("title") or "")
        body = str(item.get("content_text") or item.get("summary") or "")
        if not body and item.get("content_html"):
            body = html_to_text(str(item["content_html"]))
        entries.append(
            _FeedEntry(
                id=str(item.get("id") or "").strip() or None,
                title=title,
                url=str(item.get("url") or "").strip() or None,
                published=item.get("date_published"),
                updated=item.get("date_modified"),
                author=author,
                text=_entry_text(title, body),
                media=media,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Feed dispatch
# ---------------------------------------------------------------------------


def parse_feed(body: str) -> tuple[str, list[_FeedEntry]]:
    """Parse RSS 2.0 / Atom / JSON Feed body into (feed_title, entries)."""
    meta = _FeedMeta()
    stripped = body.lstrip()
    if stripped.startswith("{"):
        try:
            blob = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise CollectionError(f"JSON Feed is not valid JSON: {exc}") from exc
        if not isinstance(blob, dict):
            raise CollectionError("JSON Feed root is not an object")
        return meta.title, _parse_json_feed(blob, meta)
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError as exc:
        raise CollectionError(f"feed is not valid XML: {exc}") from exc
    local = _local(root.tag)
    if local == "rss":
        return meta.title, _parse_rss(root, meta)
    if local == "feed":
        return meta.title, _parse_atom(root, meta)
    raise CollectionError(f"unrecognized feed root element: {root.tag!r}")


# ---------------------------------------------------------------------------
# Timestamp / author helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class RssAdapter(SocialCollector):
    """Collector around public RSS/Atom/JSON-Feed subscriptions."""

    source = "rss"
    platform = "web"  # RSS items are web content; `source` keeps provenance

    def __init__(
        self,
        *,
        fixture_dir: str | Path = DEFAULT_FIXTURE_DIR,
        raw_dir: str | Path = DEFAULT_RAW_DIR,
        normalized_dir: str | Path = DEFAULT_NORMALIZED_DIR,
        validator: TargetValidator | None = None,
        audit_log: AuditLog | None = None,
        logger_=None,
        timeout: int = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.fixture_dir = Path(fixture_dir)
        self.raw_dir = Path(raw_dir)
        self.normalized_dir = Path(normalized_dir)
        self.timeout = timeout
        self.last_source_status: dict[str, str] | None = None
        self.last_window_days: int | None = None
        super().__init__(validator=validator, audit_log=audit_log, logger_=logger_)

    # -- 2. target validation ----------------------------------------------

    def validate_target(self, target: dict[str, Any]) -> None:
        """Require an allowlisted entity and at least one http(s) feed URL."""
        entity = self._target_entity(target)
        entity_type = self._target_entity_type(target)
        feeds = self._resolve_feeds(target)
        if not feeds:
            raise TargetValidationError(
                "target requires at least one feed URL ('url' or 'feeds')"
            )
        for url in feeds:
            if not _SCHEME_RE.match(url):
                raise TargetValidationError(f"feed URL must be http(s): {url!r}")

        if self.validator is not None and len(self.validator) > 0:
            self.validator.require("web", entity, entity_type)
        else:
            raise TargetValidationError("no allowlist configured; refusing collection")

    @staticmethod
    def _resolve_feeds(target: dict[str, Any]) -> list[str]:
        if target.get("feeds"):
            return [str(f).strip() for f in target["feeds"] if str(f).strip()]
        if target.get("url"):
            return [str(target["url"]).strip()]
        if target.get("feed_url"):
            return [str(target["feed_url"]).strip()]
        return []

    # -- 3. collection -----------------------------------------------------

    def collect(self, target: dict[str, Any], run_id: str) -> list[SocialRecord]:
        """Fetch and parse every feed URL; return schema-compliant records."""
        entity = str(target["entity"])
        entity_type = str(target["entity_type"])
        mock = bool(target.get("mock", False))
        feeds = self._resolve_feeds(target)
        records: list[SocialRecord] = []
        wrote_raw = 0
        for url in feeds:
            body, fmt = self._fetch(url, mock=mock)
            if not mock:
                wrote_raw += self._write_raw(body, fmt, url, entity, run_id)
            feed_title, entries = parse_feed(body)
            for entry in entries:
                records.append(
                    self._to_record(entry, feed_title, entity, entity_type, url, run_id)
                )
        self.last_source_status = {"web": "ok" if records else "no-results"}
        self.log.info(
            "rss: parsed %d entries from %d feed(s); wrote %d raw dumps",
            len(records),
            len(feeds),
            wrote_raw,
        )
        return records

    # -- fetch -------------------------------------------------------------

    def _fetch(self, url: str, *, mock: bool) -> tuple[str, str]:
        if mock:
            fixture_name = MOCK_FEED_FIXTURES.get(url)
            if not fixture_name:
                raise CollectionError(
                    f"mock mode: no fixture mapped for feed URL {url!r}; "
                    f"known: {', '.join(sorted(MOCK_FEED_FIXTURES))}"
                )
            path = self.fixture_dir / fixture_name
            if not path.exists():
                raise CollectionError(f"mock mode: fixture not found: {path}")
            body = path.read_text(encoding="utf-8")
            return body, "json" if fixture_name.endswith(".json") else "xml"
        if not _SCHEME_RE.match(url):
            raise CollectionError(f"refusing non-http(s) feed URL: {url!r}")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ST-Trinity-Intelligence/1.0 (rss-collector; public-feeds-only)"
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = str(resp.headers.get("Content-Type") or "")
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise CollectionError(f"feed {url!r} returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise CollectionError(f"feed {url!r} unreachable: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise CollectionError(f"feed {url!r} failed: {exc}") from exc
        if "json" in content_type.lower():
            return body, "json"
        return body, "xml"

    def _write_raw(self, body: str, fmt: str, url: str, entity: str, run_id: str) -> int:
        out_dir = self.raw_dir / entity
        out_dir.mkdir(parents=True, exist_ok=True)
        host = re.sub(r"[^a-z0-9.]+", "-", url.split("//", 1)[-1].split("/", 1)[0]).strip("-")
        stamp = (run_id or utcnow())[-8:]
        ext = "json" if fmt == "json" else "xml"
        path = out_dir / f"{host or 'feed'}-{stamp}.{ext}"
        path.write_text(body, encoding="utf-8")
        return 1

    # -- normalization to schema -------------------------------------------

    def _to_record(
        self,
        entry: _FeedEntry,
        feed_title: str,
        entity: str,
        entity_type: str,
        feed_url: str,
        run_id: str,
    ) -> SocialRecord:
        return SocialRecord(
            source=self.source,
            platform=self.platform,
            entity=entity,
            entity_type=entity_type,
            post_id=entry.id or entry.url,
            author=Author(name=safe_author_name(entry.author, feed_title), id=None, url=None),
            timestamp=normalize_ts(entry.published or entry.updated),
            title=entry.title or None,
            text=entry.text,
            url=entry.url or feed_url,
            engagement={},
            media=entry.media,
            location=None,
            collected_at=utcnow(),
            run_id=run_id,
        )

    # -- schema enforcement ------------------------------------------------

    def _write_records(self, records: list[SocialRecord], run_id: str) -> int:
        if not records:
            return 0
        entity = getattr(records[0], "entity", "") or "unknown"
        out_dir = self.normalized_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", entity.lower()).strip("-") or "unknown"
        out_path = out_dir / f"{slug}.jsonl"
        count = 0
        with out_path.open("a", encoding="utf-8") as handle:
            for record in records:
                self._validate_record(record, run_id)
                handle.write(record.to_json())
                handle.write("\n")
                count += 1
        return count