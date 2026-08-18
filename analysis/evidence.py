from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from analysis.cleaning import clean_text
from analysis.evidence_model import EvidenceIdCollisionError, EvidenceItem, EvidenceValidationError, Provenance, RecencyMeta, ReliabilityMeta, StrengthMeta, validate_evidence

PLATFORM_RELIABILITY = {"github": .85, "polymarket": .80, "hackernews": .70, "youtube": .65, "x": .60, "reddit": .55, "bluesky": .55, "telegram": .55, "web": .40}


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def reliability_for(platform: str, *, verified: bool | None = False) -> ReliabilityMeta:
    score = PLATFORM_RELIABILITY.get(platform, .50) + (.10 if verified else 0)
    score = min(.95, score)
    tier = "high" if score >= .75 else "medium" if score >= .55 else "low"
    return ReliabilityMeta(tier=tier, score=round(score, 3), basis=f"platform={platform}; verified={bool(verified)}", method="platform_base_reliability_v1")


def recency_for(timestamp: str, collected_at: str, *, now: datetime | None = None) -> RecencyMeta:
    age = max(0, int((now or _parse(collected_at) - _parse(timestamp)).total_seconds() // 86400))
    return RecencyMeta(timestamp, collected_at, age, "fresh" if age < 7 else "recent" if age < 30 else "aging")


def _id(record: dict[str, Any], run_id: str) -> str:
    raw = "|".join((run_id, str(record.get("source", "")), str(record.get("platform", "")), str(record.get("post_id") or ""), str(record.get("url") or ""), str(record.get("timestamp", ""))))
    return "ev_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def record_to_evidence(record: dict[str, Any], *, run_id: str | None = None) -> EvidenceItem:
    if not isinstance(record, dict): raise EvidenceValidationError("record must be an object")
    rid = str(run_id or record.get("run_id") or "")
    required = ("source", "platform", "entity", "entity_type", "author", "timestamp", "text", "engagement", "collected_at")
    missing = [key for key in required if key not in record or record[key] is None]
    if missing or not (record.get("author") or {}).get("name"): raise EvidenceValidationError(f"record missing required fields: {missing}")
    text = str(record.get("text") or "")
    provenance = Provenance(str(record["source"]), str(record["platform"]), rid, record.get("post_id"), record.get("url"), copy.deepcopy(record["author"]), str(record["collected_at"]), text, copy.deepcopy(record))
    item = EvidenceItem(_id(record, rid), rid, str(record["source"]), str(record["platform"]), str(record["entity"]), str(record["entity_type"]), record.get("post_id"), copy.deepcopy(record["author"]), str(record["timestamp"]), text, record.get("url"), dict(record.get("engagement") or {}), str(record["collected_at"]), "raw_observation", reliability_for(str(record["platform"]), verified=record["author"].get("verified")), StrengthMeta(1.0, 0.0, "verbatim_raw_observation_v1", "Presence of a preserved source quote; no truth judgment."), recency_for(str(record["timestamp"]), str(record["collected_at"])), provenance, "", clean_text(text), record.get("title"))
    validate_evidence(item)
    return item


def build_evidence(records: Iterable[dict[str, Any]], *, run_id: str | None = None, require_single_run: bool = True) -> list[EvidenceItem]:
    items = [record_to_evidence(r, run_id=run_id) for r in records]
    ids = {i.run_id for i in items}
    if require_single_run and len(ids) > 1: raise EvidenceValidationError(f"mixed run_ids in batch: {sorted(ids)}")
    return items


def dedupe(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    seen: dict[str, EvidenceItem] = {}
    for item in items: seen.setdefault(item.evidence_id, item)
    return list(seen.values())


def check_no_collisions(items: Iterable[EvidenceItem]) -> None:
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        prior = seen.get(item.evidence_id)
        if prior is not None and prior != item.provenance.source_record: raise EvidenceIdCollisionError(item.evidence_id)
        seen[item.evidence_id] = item.provenance.source_record


def load_records(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_evidence(items: Iterable[EvidenceItem], path: str | Path) -> int:
    output = Path(path); output.parent.mkdir(parents=True, exist_ok=True); count = 0
    with output.open("w", encoding="utf-8") as handle:
        for item in items:
            validate_evidence(item); handle.write(item.to_json() + "\n"); count += 1
    return count


def load_evidence(path: str | Path) -> list[EvidenceItem]:
    with Path(path).open(encoding="utf-8-sig") as handle:
        return [__import__("analysis.evidence_model", fromlist=["evidence_from_dict"]).evidence_from_dict(json.loads(line)) for line in handle if line.strip()]


def make_signal(base: EvidenceItem, *, claim: str, method: str, rationale: str, score: float, confidence: float, lineage: list[str] | None = None) -> EvidenceItem:
    lineage = lineage or [base.evidence_id]
    provenance = copy.deepcopy(base.provenance); provenance.lineage = lineage
    value = copy.deepcopy(base); value.evidence_id = "sig_" + hashlib.sha1((method + "|" + claim).encode()).hexdigest()[:16]; value.kind = "derived_signal"; value.claim = claim; value.provenance = provenance; value.strength = StrengthMeta(score, confidence, method, rationale)
    validate_evidence(value); return value


def make_conclusion(*, claim: str, based_on: list[EvidenceItem], author: str, confidence: float, rationale: str = "", run_id: str | None = None, entity: str = "", entity_type: str = "topic", collected_at: str | None = None) -> EvidenceItem:
    if not based_on: raise EvidenceValidationError("conclusion requires evidence")
    base = based_on[0]; rid = run_id or base.run_id; collected = collected_at or base.collected_at
    provenance = Provenance("analyst", "intelligence", rid, base.post_id, base.url, {"name": author}, collected, "", {}, [i.evidence_id for i in based_on])
    value = EvidenceItem("con_" + hashlib.sha1((author + "|" + claim).encode()).hexdigest()[:16], rid, "analyst", "intelligence", entity or base.entity, entity_type or base.entity_type, base.post_id, {"name": author}, collected, "", base.url, {}, collected, "analyst_conclusion", base.reliability, StrengthMeta(confidence, confidence, "analyst_judgment_v1", rationale), RecencyMeta(collected, collected, 0, "fresh"), provenance, claim, "")
    validate_evidence(value); return value
