from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

EVENT_TYPES = ("product_launch", "product_release", "model_release", "company_announcement", "funding", "acquisition", "partnership", "major_update", "technology_release", "research_publication", "major_discussion", "community_reaction", "controversy", "regulatory_development", "market_development", "other")
IMPORTANCE_LEVELS = ("critical", "high", "medium", "low", "informational")


def importance_for_score(score: float) -> str:
    if score >= .70: return "critical"
    if score >= .45: return "high"
    if score >= .32: return "medium"
    if score >= .20: return "low"
    return "informational"


@dataclass
class EventItem:
    event_id: str
    canonical_title: str
    event_type: str
    event_date: str
    first_seen: str
    last_seen: str
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    source_count: int = 0
    platform_count: int = 0
    platforms: list[str] = field(default_factory=list)
    confidence: float = 0.0
    importance: str = "informational"
    summary: str = ""
    significance: str = ""
    source_urls: list[str] = field(default_factory=list)
    cluster_id: str = ""
    signal_id: str = ""
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class EventValidationError(ValueError): pass


def validate_event(value: EventItem) -> None:
    if not value.event_id or not value.canonical_title or value.event_type not in EVENT_TYPES or not value.event_date or not value.evidence_ids or not value.summary:
        raise EventValidationError("invalid event")
    if value.importance not in IMPORTANCE_LEVELS or not 0 <= value.confidence <= 1 or value.source_count < 1 or value.platform_count < 1:
        raise EventValidationError("invalid event metadata")
