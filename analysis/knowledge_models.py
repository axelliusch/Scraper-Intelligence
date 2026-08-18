from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from typing import Any

KNOWLEDGE_DECISIONS = ("KEEP", "REVIEW", "DISCARD")
KNOWLEDGE_TYPES = ("event", "concept", "entity", "technology", "trend", "research", "observation")
@dataclass
class KnowledgeItem:
    knowledge_id: str; title: str; type: str; summary: str
    entities: list[str] = field(default_factory=list); topics: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list); evidence_ids: list[str] = field(default_factory=list)
    importance: str = "informational"; confidence: float = 0.0; created_date: str = ""
    source_urls: list[str] = field(default_factory=list); recommended_action: str = ""; decision: str = "REVIEW"
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
class KnowledgeError(ValueError): pass
def validate_knowledge(value: KnowledgeItem) -> None:
    if not value.knowledge_id or not value.title or value.type not in KNOWLEDGE_TYPES or value.decision not in KNOWLEDGE_DECISIONS or not value.evidence_ids:
        raise KnowledgeError("invalid knowledge item")
