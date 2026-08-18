from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass
class TimelineDay:
    date: str; events: list[dict[str, Any]] = field(default_factory=list)
@dataclass
class TopicTrend:
    name: str; first_seen: str; last_seen: str; event_count: int = 0; evidence_count: int = 0; status: str = "one-off"; explanation: str = ""
@dataclass
class EntityTrend:
    name: str; entity_type: str = ""; event_count: int = 0; first_seen: str = ""; last_seen: str = ""
@dataclass
class TimelineSummary:
    biggest_developments: list[str] = field(default_factory=list); emerging_developments: list[str] = field(default_factory=list)
    persistent_developments: list[str] = field(default_factory=list); declining_developments: list[str] = field(default_factory=list)
    recurring_developments: list[str] = field(default_factory=list); disappearing_developments: list[str] = field(default_factory=list)
    important_entities: list[str] = field(default_factory=list); important_topics: list[str] = field(default_factory=list)
    major_changes: list[str] = field(default_factory=list); source_coverage: str = ""
@dataclass
class IntelligenceTimeline:
    start_date: str; end_date: str; days: list[TimelineDay] = field(default_factory=list)
    topics: list[TopicTrend] = field(default_factory=list); entities: list[EntityTrend] = field(default_factory=list)
    summary: TimelineSummary = field(default_factory=TimelineSummary)
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
class TimelineError(ValueError): pass
def validate_timeline(value: IntelligenceTimeline) -> None:
    if value.start_date and value.end_date and value.start_date > value.end_date: raise TimelineError("timeline window inverted")
