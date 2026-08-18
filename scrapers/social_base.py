from __future__ import annotations

import abc
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, TextIO

logger = logging.getLogger("st_trinity.social")

# Schema-compliant platform identifiers (data/social/SCHEMA.md §2/§5).
PLATFORMS = frozenset(
    {
        "reddit",
        "x",
        "youtube",
        "tiktok",
        "instagram",
        "hackernews",
        "bluesky",
        "polymarket",
        "github",
        "threads",
        "pinterest",
        "linkedin",
        "web",
        "corpus",
        "telegram",
    }
)

# Schema-compliant entity types (data/social/SCHEMA.md §2).
ENTITY_TYPES = frozenset({"person", "competitor", "property", "group", "brand", "topic"})

# Known collection engines (schema §3).
SOURCES = frozenset(
    {"last30days", "instagram", "x", "youtube", "rss", "telegram"}
)

# Media types allowed inside the schema's `media` array (schema §3).
MEDIA_TYPES = frozenset({"image", "video", "audio", "link"})

# Engagement counters defined by the schema (schema §3).
# `points`/`stars`/`forks`/`issues` cover Hacker News & GitHub; `saves` covers
# TikTok/Instagram saves. Unknown counters are null, never fabricated.
ENGAGEMENT_KEYS = (
    "likes",
    "upvotes",
    "comments",
    "shares",
    "views",
    "reposts",
    "reactions",
    "saves",
    "stars",
    "forks",
    "points",
    "issues",
)

_AUTHOR_KEYS = ("id", "name", "url", "verified")
_MEDIA_KEYS = ("type", "url", "mime", "width", "height", "duration", "title")
_LOCATION_KEYS = ("place", "latitude", "longitude", "country", "city")


def utcnow() -> str:
    """Current UTC time as an ISO 8601 string (schema `timestamp` format)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    """Generate a schema-compliant run ID: run_YYYYMMDD_<shortid>."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"run_{stamp}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Domain model (schema mirror, data/social/SCHEMA.md §2/§3)
# ---------------------------------------------------------------------------

@dataclass
class Author:
    """Required object inside every record (schema: `author`)."""

    name: str = ""
    id: str | None = None
    url: str | None = None
    verified: bool | None = None


@dataclass
class MediaItem:
    """Single entry in the `media` array (schema §3)."""

    type: str = "link"
    url: str | None = None
    mime: str | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    title: str | None = None


@dataclass
class SocialRecord:
    """One normalized JSONL record, 1:1 with data/social/SCHEMA.md."""

    source: str
    platform: str
    entity: str
    entity_type: str
    post_id: str | None
    author: Author
    timestamp: str
    text: str
    url: str | None
    engagement: dict[str, Any] = field(default_factory=dict)
    media: list[MediaItem] = field(default_factory=list)
    location: dict[str, Any] | None = None
    collected_at: str = field(default_factory=utcnow)
    run_id: str = ""
    # Optional rich fields (schema §3 optional). Platform-specific source
    # methods may return different subsets; values are never invented.
    query: str | None = None
    title: str | None = None
    author_handle: str | None = None
    language: str | None = None
    media_type: str | None = None
    source_status: str | None = None
    raw_record_reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a schema-compliant JSON object.

        Required fields are always present. Rich optional fields are emitted
        only when set, so the record stays schema-valid and deterministic.
        """
        engagement = dict(self.engagement)
        for key in ENGAGEMENT_KEYS:
            engagement.setdefault(key, None)
        media = [asdict(m) for m in self.media]
        result: dict[str, Any] = {
            "source": self.source,
            "platform": self.platform,
            "entity": self.entity,
            "entity_type": self.entity_type,
            "post_id": self.post_id,
            "author": asdict(self.author),
            "timestamp": self.timestamp,
            "text": self.text,
            "url": self.url,
            "engagement": engagement,
            "media": media,
            "collected_at": self.collected_at,
            "run_id": self.run_id,
        }
        result["location"] = self.location
        value: Any
        for key in (
            "query",
            "title",
            "author_handle",
            "language",
            "media_type",
            "source_status",
            "raw_record_reference",
        ):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result

    def to_json(self) -> str:
        """Serialize to a single JSONL line (UTF-8, no trailing newline)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CollectorError(Exception):
    """Base class for all collector failures."""


class TargetValidationError(CollectorError):
    """The supplied target is missing, malformed, unsupported, or unauthorized."""


class AuthenticationUnavailableError(CollectorError):
    """Authentication or authorized access is not available; fail safely."""


class CollectionError(CollectorError):
    """The collection step failed (network, parse, or platform error)."""


class SchemaError(CollectorError):
    """A collector tried to emit a non-schema-compliant record."""


# ---------------------------------------------------------------------------
# Target allowlist
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllowedTarget:
    """An explicitly authorized target keyed by (platform, entity, entity_type)."""

    platform: str
    entity: str
    entity_type: str


class TargetValidator:
    """Validates that an explicit target is authorized and non-private.

    Collectors MUST reject anything not present here. Only public/authorized
    targets belong in the allowlist.
    """

    def __init__(self, allowlisted: set[AllowedTarget] | None = None) -> None:
        self._allowed: set[tuple[str, str, str]] = {
            (t.platform, t.entity, t.entity_type) for t in (allowlisted or set())
        }

    def add(self, platform: str, entity: str, entity_type: str) -> None:
        if platform not in PLATFORMS:
            raise TargetValidationError(f"unknown platform: {platform!r}")
        if entity_type not in ENTITY_TYPES:
            raise TargetValidationError(f"unknown entity_type: {entity_type!r}")
        self._allowed.add((platform, entity, entity_type))

    def is_allowed(self, platform: str, entity: str, entity_type: str) -> bool:
        return (platform, entity, entity_type) in self._allowed

    def require(self, platform: str, entity: str, entity_type: str) -> None:
        if not self.is_allowed(platform, entity, entity_type):
            raise TargetValidationError(
                f"target not authorized: platform={platform!r} "
                f"entity={entity!r} entity_type={entity_type!r}"
            )

    def __len__(self) -> int:
        return len(self._allowed)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditLog:
    """Append-only JSONL audit trail for collection runs.

    Records: timestamp, source, target, run_id, status, and a short message.
    Never contains credentials, cookies, or content payloads.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        source: str,
        platform: str,
        entity: str,
        entity_type: str,
        run_id: str,
        status: str,
        message: str = "",
    ) -> None:
        entry = {
            "timestamp": utcnow(),
            "source": source,
            "platform": platform,
            "entity": entity,
            "entity_type": entity_type,
            "run_id": run_id,
            "status": status,
            "message": message,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


# ---------------------------------------------------------------------------
# Collector interface
# ---------------------------------------------------------------------------


class SocialCollector(abc.ABC):
    """Platform-neutral interface every social collector implements.

    Concrete collectors supply `source`, `platform`, `validate_target`,
    and `collect`. The base class provides target gating, run orchestration,
    audit logging, schema-aware output, and safe error handling.
    """

    #: Engine name (schema `source`, e.g. "last30days", "rss", "telegram").
    source: str = ""

    #: Primary platform (schema `platform`, e.g. "reddit", "x", "telegram").
    platform: str = ""

    def __init__(
        self,
        *,
        validator: TargetValidator | None = None,
        audit_log: AuditLog | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        if not self.source:
            raise TypeError(f"{type(self).__name__} must define `source`")
        if not self.platform:
            raise TypeError(f"{type(self).__name__} must define `platform`")
        if self.platform not in PLATFORMS:
            raise ValueError(f"{self.__class__.__name__}: unknown platform {self.platform!r}")
        if self.source not in SOURCES:
            raise ValueError(f"{self.__class__.__name__}: unknown source {self.source!r}")

        self.validator = validator or TargetValidator()
        self.audit_log = audit_log
        self.log = logger_ or logging.getLogger(f"st_trinity.{self.source}")

    # -- 1. source/platform identification --------------------------------

    @property
    def ident(self) -> dict[str, str]:
        """Schema identification: source + platform."""
        return {"source": self.source, "platform": self.platform}

    # -- 2. target validation ----------------------------------------------

    @abc.abstractmethod
    def validate_target(self, target: dict[str, Any]) -> None:
        """Validate an explicitly supplied target.

        MUST check the allowlist and reject private/unauthorized targets by
        raising TargetValidationError. Implementations must not guess handles,
        profiles, or endpoints beyond the supplied target.
        """

    # -- 3. collection -----------------------------------------------------

    @abc.abstractmethod
    def collect(self, target: dict[str, Any], run_id: str) -> list[SocialRecord]:
        """Collect public data for an already-validated target.

        Called only after `validate_target` passes. Returns schema-compliant
        records. Implementations must not bypass auth/access controls and must
        fail safely (raise AuthenticationUnavailableError) when access is not
        available.
        """

    # -- 5. error handling / 4+6. orchestration -----------------------------

    def run(self, target: dict[str, Any]) -> list[SocialRecord]:
        """Full, safe run for one explicitly supplied target.

        Orchestrates: target validation -> new run_id -> collect -> audit.
        Any auth/access absence raises instead of degrading silently.
        """
        entity = self._target_entity(target)
        entity_type = self._target_entity_type(target)
        run_id = new_run_id()

        try:
            self.validate_target(target)
            status_start = "ok"
        except TargetValidationError as exc:
            self._audit(target, run_id, "rejected", str(exc))
            raise

        self._audit(target, run_id, status_start, "target validated; collection started")

        records: list[SocialRecord] = []
        try:
            records = self.collect(target, run_id)
        except AuthenticationUnavailableError as exc:
            self._audit(target, run_id, "auth_unavailable", str(exc))
            raise
        except CollectorError as exc:
            self._audit(target, run_id, "failed", str(exc))
            raise
        except Exception as exc:  # defensive: never leak unexpected faults silently
            self.log.exception("unexpected collection failure")
            self._audit(target, run_id, "failed", f"unexpected error: {exc!r}")
            raise CollectionError(str(exc)) from exc

        written = self._write_records(records, run_id)
        self._audit(
            target,
            run_id,
            "completed",
            f"collected {len(records)} records; wrote {written}",
        )
        return records

    # -- 4. normalized output ----------------------------------------------

    def _write_records(self, records: list[SocialRecord], run_id: str) -> int:
        """Write schema-compliant JSONL into data/social/normalized/<entity>.jsonl."""
        if not records:
            return 0
        entity = getattr(records[0], "entity", "") or "unknown"
        out_dir = Path("data") / "social" / "normalized"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{entity}.jsonl"
        count = 0
        with out_path.open("a", encoding="utf-8") as handle:
            for record in records:
                self._validate_record(record, run_id)
                handle.write(record.to_json())
                handle.write("\n")
                count += 1
        return count

    def _validate_record(self, record: SocialRecord, run_id: str) -> None:
        """Enforce the schema contract before writing (schema §7)."""
        if not record.source or not record.platform:
            raise SchemaError("record missing source/platform")
        if not record.entity or not record.entity_type:
            raise SchemaError("record missing entity/entity_type")
        if not record.author or not record.author.name:
            raise SchemaError("record missing author.name")
        if not record.timestamp:
            raise SchemaError("record missing timestamp")
        if not record.run_id:
            record.run_id = run_id
        if record.platform != self.platform:
            raise SchemaError(
                f"record platform {record.platform!r} != collector platform {self.platform!r}"
            )
        if record.source != self.source:
            raise SchemaError(
                f"record source {record.source!r} != collector source {self.source!r}"
            )

    # -- helpers -----------------------------------------------------------

    def _target_entity(self, target: dict[str, Any]) -> str:
        entity = target.get("entity")
        if not entity:
            raise TargetValidationError("target requires 'entity'")
        return str(entity)

    def _target_entity_type(self, target: dict[str, Any]) -> str:
        entity_type = target.get("entity_type")
        if entity_type not in ENTITY_TYPES:
            raise TargetValidationError(
                f"target requires valid 'entity_type'; got {entity_type!r}"
            )
        return entity_type

    def _audit(
        self,
        target: dict[str, Any],
        run_id: str,
        status: str,
        message: str,
    ) -> None:
        if self.audit_log is not None:
            try:
                self.audit_log.write(
                    source=self.source,
                    platform=self.platform,
                    entity=self._safe_target_entity(target),
                    entity_type=self._safe_target_entity_type(target),
                    run_id=run_id,
                    status=status,
                    message=message,
                )
            except Exception:
                self.log.warning("audit logging failed", exc_info=True)

    def _safe_target_entity(self, target: dict[str, Any]) -> str:
        try:
            return str(target.get("entity", ""))
        except Exception:
            return ""

    def _safe_target_entity_type(self, target: dict[str, Any]) -> str:
        try:
            return str(target.get("entity_type", ""))
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Convenience: wire a concrete collector to real outputs
# ---------------------------------------------------------------------------


def make_collector(
    collector: SocialCollector,
    *,
    allowlist: list[tuple[str, str, str]] | None = None,
    audit_path: str | Path = "logs/social-audit.jsonl",
) -> SocialCollector:
    """Attach a TargetValidator + AuditLog to a collector instance.

    allowlist entries are (platform, entity, entity_type) tuples.
    """
    validator = TargetValidator()
    if allowlist:
        for platform, entity, entity_type in allowlist:
            validator.add(platform, entity, entity_type)
    collector.validator = validator
    collector.audit_log = AuditLog(audit_path)
    return collector