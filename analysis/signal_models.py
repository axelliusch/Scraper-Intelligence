from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SIGNAL_TYPES = ("isolated", "emerging", "sustained", "accelerating", "declining")
DEDUP_REASONS = ("exact_url", "duplicate_post_id", "exact_text", "near_duplicate_text", "shared_entity", "isolated")
ENGAGEMENT_KEYS = ("likes", "upvotes", "comments", "shares", "views", "reposts", "reactions", "saves", "stars", "forks", "points", "issues")
ENGAGEMENT_WEIGHTS = {k: 1.0 for k in ENGAGEMENT_KEYS}
ENGAGEMENT_WEIGHTS.update({"comments": 3.0, "shares": 3.0, "views": .0001, "forks": 1.5})


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def days_between(start: str, end: str) -> int:
    return max(0, int((parse_utc(end) - parse_utc(start)).total_seconds() // 86400))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float: return max(low, min(high, value))
def median_abs(values: list[float]) -> float:
    values = sorted(values); n = len(values)
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


def engagement_total(item: Any) -> int:
    return sum(int((getattr(item, "engagement", {}) or {}).get(k) or 0) for k in ENGAGEMENT_KEYS if isinstance((getattr(item, "engagement", {}) or {}).get(k), (int, float)))


def engagement_score(item: Any) -> float:
    values = getattr(item, "engagement", {}) or {}
    return round(sum(float(values.get(k) or 0) * w for k, w in ENGAGEMENT_WEIGHTS.items() if isinstance(values.get(k), (int, float))), 4)


@dataclass
class EvidenceCluster:
    cluster_id: str
    evidence_ids: list[str]
    canonical_title: str
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    source_count: int = 0
    platform_count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    deduplication_reason: str = "isolated"
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass
class SignalItem:
    signal_id: str
    cluster_id: str
    signal_type: str
    strength: float
    confidence: float
    source_diversity: float
    evidence_count: int
    engagement_total: int
    first_seen: str
    last_seen: str
    recency_score: float
    explanation: str
    evidence_ids: list[str] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class ClusterValidationError(ValueError): pass
class SignalValidationError(ValueError): pass


def validate_cluster(value: EvidenceCluster) -> None:
    if not value.cluster_id or not value.evidence_ids or not value.canonical_title or not value.first_seen or not value.last_seen:
        raise ClusterValidationError("invalid evidence cluster")
    if value.source_count < 1 or value.platform_count < 1 or value.deduplication_reason not in DEDUP_REASONS:
        raise ClusterValidationError("invalid cluster metadata")


def validate_signal(value: SignalItem) -> None:
    if value.signal_type not in SIGNAL_TYPES or not value.signal_id or not value.cluster_id or not value.evidence_ids:
        raise SignalValidationError("invalid signal identity")
    if value.evidence_count != len(value.evidence_ids) or not 0 <= value.strength <= 1 or not 0 <= value.confidence <= 1:
        raise SignalValidationError("invalid signal scores")
