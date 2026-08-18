from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

EVIDENCE_KINDS = ("raw_observation", "derived_signal", "analyst_conclusion")


@dataclass
class ReliabilityMeta:
    tier: str
    score: float
    basis: str
    method: str


@dataclass
class StrengthMeta:
    score: float
    confidence: float
    method: str
    rationale: str


@dataclass
class RecencyMeta:
    published_at: str
    collected_at: str
    age_days: int
    tier: str


@dataclass
class Provenance:
    source: str
    platform: str
    run_id: str
    post_id: str | None
    url: str | None
    author: dict[str, Any]
    collected_at: str
    source_text: str
    source_record: dict[str, Any] = field(default_factory=dict)
    lineage: list[str] = field(default_factory=list)


@dataclass
class EvidenceItem:
    evidence_id: str
    run_id: str
    source: str
    platform: str
    entity: str
    entity_type: str
    post_id: str | None
    author: dict[str, Any]
    timestamp: str
    text: str
    url: str | None
    engagement: dict[str, Any]
    collected_at: str
    kind: str
    reliability: ReliabilityMeta
    strength: StrengthMeta
    recency: RecencyMeta
    provenance: Provenance
    claim: str | None = None
    cleaned_text: str = ""
    title: str | None = None

    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class EvidenceError(ValueError): pass
class EvidenceValidationError(EvidenceError): pass
class EvidenceIdCollisionError(EvidenceError): pass


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceValidationError(f"{label} is not ISO 8601: {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def validate_evidence(item: EvidenceItem) -> None:
    if item.kind not in EVIDENCE_KINDS or not item.evidence_id or not item.run_id:
        raise EvidenceValidationError("invalid evidence identity or kind")
    if not item.source or not item.platform or not item.entity or not item.entity_type:
        raise EvidenceValidationError("evidence missing identity fields")
    if not item.author.get("name") or not item.provenance.source_record and item.kind == "raw_observation":
        raise EvidenceValidationError("evidence missing author or source record")
    _timestamp(item.timestamp, "timestamp"); _timestamp(item.collected_at, "collected_at")
    if not isinstance(item.provenance, Provenance) or not isinstance(item.engagement, dict):
        raise EvidenceValidationError("invalid evidence provenance")
    if item.kind == "raw_observation":
        if item.claim or item.text != item.provenance.source_text or item.provenance.lineage:
            raise EvidenceValidationError("raw observation was altered or given a claim")
    elif not item.claim or item.kind == "analyst_conclusion" and not item.provenance.lineage:
        raise EvidenceValidationError("derived evidence requires claim and lineage")


def evidence_from_dict(data: dict[str, Any]) -> EvidenceItem:
    value = dict(data)
    for key, cls in (("reliability", ReliabilityMeta), ("strength", StrengthMeta), ("recency", RecencyMeta), ("provenance", Provenance)):
        if isinstance(value.get(key), dict): value[key] = cls(**value[key])
    item = EvidenceItem(**value)
    validate_evidence(item)
    return item

from_dict = evidence_from_dict
