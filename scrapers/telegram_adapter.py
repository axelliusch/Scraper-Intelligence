from __future__ import annotations

import html.parser
import re
import urllib.error
import urllib.request
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
from textutil import html_to_text, normalize_ts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "social" / "raw" / "telegram"
DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "social" / "normalized"
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "social-audit.jsonl"
DEFAULT_FIXTURE = "telegram-public.html"

HTTP_TIMEOUT_SECONDS = 60

_CHANNEL_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_POST_ID_RE = re.compile(r'data-post="[^"/]+/(\d+)"')
_TEXT_RE = re.compile(
    r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S
)
_DATETIME_RE = re.compile(r'<time datetime="([^"]+)"')
_PHOTO_RE = re.compile(
    r'tgme_widget_message_photo_wrap[^>]*style="[^"]*background-image:url\(\'([^\']+)\''
)
_LINK_TITLE_RE = re.compile(
    r'tgme_widget_message_link_preview_title"[^>]*href="([^"]+)"'
)
_CHANNEL_INFO_RE = re.compile(r"tgme_channel_info")
_TITLE_RE = re.compile(r'tgme_channel_info_header_title"[^>]*>(.*?)</div>', re.S)
_USERNAME_RE = re.compile(r'tgme_channel_info_header_username"[^>]*>(.*?)</div>', re.S)


@dataclass
class _Message:
    post_id: str | None = None
    url: str | None = None
    published: str | None = None
    text: str = ""
    author: str = ""
    media: list[MediaItem] = field(default_factory=list)


class _BlockParser(html.parser.HTMLParser):
    """Capture balanced top-level ``tgme_widget_message`` div blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._depth = 0
        self._capturing = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div" and not self._capturing:
            classes = dict(attrs).get("class", "").split()
            if "tgme_widget_message" in classes and (
                "tgme_widget_message_service" not in classes
            ) and "data-post" in dict(attrs):
                self._capturing = True
                self._depth = 1
                self._buf = [self.get_starttag_text()]
                return
        self._append_start(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._capturing:
            self._buf.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if not self._capturing:
            return
        if tag == "div":
            self._depth -= 1
            self._buf.append("</div>")
            if self._depth <= 0:
                self.blocks.append("".join(self._buf))
                self._capturing = False
                self._buf = []
                self._depth = 0
        else:
            self._buf.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._buf.append(data)

    def _append_start(self, tag: str) -> None:
        if not self._capturing:
            return
        if tag == "div":
            self._depth += 1
        self._buf.append(self.get_starttag_text())


def _extract_message_blocks(page_html: str) -> list[str]:
    parser = _BlockParser()
    parser.feed(page_html)
    parser.close()
    return parser.blocks


def _parse_block(block: str, channel: str) -> _Message | None:
    post_match = _POST_ID_RE.search(block)
    if not post_match:
        return None
    post_id = post_match.group(1)
    text = html_to_text(_first_group(_TEXT_RE, block))
    media: list[MediaItem] = []
    photo_match = _PHOTO_RE.search(block)
    if photo_match:
        media.append(MediaItem(type="image", url=_absolute(photo_match.group(1)), mime="image/jpeg"))
    link_match = _LINK_TITLE_RE.search(block)
    if link_match:
        media.append(MediaItem(type="link", url=link_match.group(1)))
    if not text and not media:  # empty notification / unsupported payload
        return None
    return _Message(
        post_id=post_id,
        url=f"https://t.me/{channel}/{post_id}",
        published=_first_group(_DATETIME_RE, block),
        text=text,
        media=media,
    )


def _parse_channel_info(page_html: str) -> tuple[str, str]:
    """Return (channel_title, channel_username) for a public channel page."""
    title = html_to_text(_first_group(_TITLE_RE, page_html))
    username = html_to_text(_first_group(_USERNAME_RE, page_html)).lstrip("@")
    return title, username


def _first_group(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(1) if m else ""


def _absolute(value: str) -> str:
    """Resolve protocol-relative CDN URLs (e.g. ``//cdn……``) to https."""
    value = value.strip()
    if value.startswith("//"):
        return f"https:{value}"
    return value


def resolve_channel(target: dict[str, Any]) -> str:
    """Extract a public channel username from a target.

    Accepts ``channel`` (with or without ``@``), ``url``/``channel_url``
    (e.g. ``https://t.me/s/username``). Returns "" when absent/invalid.
    """
    raw = (
        str(target.get("channel") or target.get("url") or target.get("channel_url") or "").strip()
    )
    if not raw:
        return ""
    value = re.sub(r"^(https?://)?(www\.)?t\.me/", "", raw).strip("/")
    if value.startswith("s/"):
        value = value[2:]
    value = value.split("?")[0].split("/")[0].lstrip("@")
    return value if _CHANNEL_RE.match(value) else ""


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class TelegramAdapter(SocialCollector):
    """Collector around Telegram's public channel web preview (t.me/s/...)."""

    source = "telegram"
    platform = "telegram"

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
        """Require an allowlisted entity and a valid public channel username."""
        entity = self._target_entity(target)
        entity_type = self._target_entity_type(target)
        channel = resolve_channel(target)
        if not channel:
            raise TargetValidationError(
                "target requires a public Telegram channel ('channel' or 'url')"
            )
        target["_channel"] = channel  # validated canonical form for collect()

        if self.validator is not None and len(self.validator) > 0:
            self.validator.require("telegram", entity, entity_type)
        else:
            raise TargetValidationError("no allowlist configured; refusing collection")

    # -- 3. collection -----------------------------------------------------

    def collect(self, target: dict[str, Any], run_id: str) -> list[SocialRecord]:
        """Fetch the public channel preview and return schema-compliant records.

        The channel must be explicitly supplied; public channels only.
        """
        entity = str(target["entity"])
        entity_type = str(target["entity_type"])
        channel = str(target.get("_channel") or resolve_channel(target))
        if not channel:
            raise TargetValidationError("target requires a public Telegram channel")
        mock = bool(target.get("mock", False))

        page_html = self._fetch_page(channel, mock=mock)
        if not mock:
            self._write_raw(page_html, channel, entity, run_id)

        if _CHANNEL_INFO_RE.search(page_html) is None:
            raise CollectionError(
                f"channel {channel!r} is not a public channel (no public preview page)"
            )

        title, username = _parse_channel_info(page_html)
        author_name = title or username or channel
        records: list[SocialRecord] = []
        for block in _extract_message_blocks(page_html):
            message = _parse_block(block, channel)
            if message is None:
                continue
            records.append(
                SocialRecord(
                    source=self.source,
                    platform=self.platform,
                    entity=entity,
                    entity_type=entity_type,
                    post_id=message.post_id,
                    author=Author(name=author_name, id=username or channel, url=f"https://t.me/{channel}"),
                    timestamp=normalize_ts(message.published),
                    text=message.text,
                    url=message.url,
                    engagement={},
                    media=message.media,
                    location=None,
                    collected_at=utcnow(),
                    run_id=run_id,
                )
            )
        self.last_source_status = {"telegram": "ok" if records else "no-results"}
        self.log.info(
            "telegram: parsed %d message(s) from public channel %r",
            len(records),
            channel,
        )
        return records

    # -- fetch -------------------------------------------------------------

    def _fetch_page(self, channel: str, *, mock: bool) -> str:
        if mock:
            path = self.fixture_dir / DEFAULT_FIXTURE
            if not path.exists():
                raise CollectionError(f"mock mode: fixture not found: {path}")
            return path.read_text(encoding="utf-8")
        url = f"https://t.me/s/{channel}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ST-Trinity-Intelligence/1.0 (telegram-collector; public-channels-only)"
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise CollectionError(
                    f"channel {channel!r} not found (HTTP 404)"
                ) from exc
            raise CollectionError(
                f"channel {channel!r} returned HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise CollectionError(
                f"channel {channel!r} unreachable: {exc.reason}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise CollectionError(f"channel {channel!r} failed: {exc}") from exc

    def _write_raw(self, page_html: str, channel: str, entity: str, run_id: str) -> int:
        out_dir = self.raw_dir / entity
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = (run_id or utcnow())[-8:]
        path = out_dir / f"{channel}-{stamp}.html"
        path.write_text(page_html, encoding="utf-8")
        return 1

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