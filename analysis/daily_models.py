from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass
class DigestEvent:
    event_id: str; title: str; datetime: str; category: str
    entities: list[str] = field(default_factory=list); topics: list[str] = field(default_factory=list)
    importance: str = "informational"; confidence: float = 0.0; explanation: str = ""
    evidence_ids: list[str] = field(default_factory=list); platforms: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list); snippet: str = ""

@dataclass
class DigestTopic:
    name: str; evidence_count: int = 0; first_seen: str = ""; notes: str = ""
@dataclass
class DigestEntity:
    name: str; entity_type: str = ""; event_count: int = 0
@dataclass
class DigestSignal:
    signal_id: str; signal_type: str; strength: float = 0.0; confidence: float = 0.0; title: str = ""
@dataclass
class DigestSource:
    platform: str; count: int = 0; urls: list[str] = field(default_factory=list)
@dataclass
class DailyDigest:
    date: str; executive_summary: str = ""; important_events: list[DigestEvent] = field(default_factory=list)
    other_events: list[DigestEvent] = field(default_factory=list); emerging_topics: list[DigestTopic] = field(default_factory=list)
    important_entities: list[DigestEntity] = field(default_factory=list); signals: list[DigestSignal] = field(default_factory=list)
    why_it_matters: str = ""; sources: list[DigestSource] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
class DailyDigestError(ValueError): pass
def validate_digest(value: DailyDigest) -> None:
    if not value.date or not value.executive_summary: raise DailyDigestError("invalid daily digest")
