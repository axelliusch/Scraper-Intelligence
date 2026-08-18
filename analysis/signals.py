from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from analysis.extraction_models import deterministic_id
from analysis.signal_models import SignalItem, clamp, days_between, engagement_score, engagement_total, median_abs, parse_utc, validate_signal

STRENGTH_WEIGHTS = {"recency": .35, "diversity": .25, "evidence": .20, "engagement": .10, "persistence": .10}


def now_utc() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def source_diversity(members: list[Any]) -> float: return clamp((len({x.platform for x in members}) + .5 * (len({x.source for x in members}) - 1)) / 3)
def recency_score(last_seen: str, *, as_of: str | None = None) -> float: return round(clamp(math.exp(-max(0, (parse_utc(as_of or now_utc()) - parse_utc(last_seen)).total_seconds() / 86400) / 30)), 3)


def signal_type_for(timestamps: list[str]) -> str:
    ordered = sorted(parse_utc(t) for t in timestamps)
    if len(ordered) == 1: return "isolated"
    span = (ordered[-1] - ordered[0]).total_seconds() / 86400
    if len(ordered) < 3: return "sustained" if span >= 7 else "emerging"
    gaps = [(ordered[i + 1] - ordered[i]).total_seconds() / 86400 for i in range(len(ordered) - 1)]; split = len(gaps) // 2
    first, second = median_abs(gaps[:split]), median_abs(gaps[split:])
    if second + 1 <= first: return "accelerating"
    if second >= first + 1: return "declining"
    return "sustained" if span >= 7 else "emerging"


def strength(*, recency: float, diversity: float, evidence_count: int, engagement: float, span_days: int) -> float:
    parts = {"recency": recency, "diversity": diversity, "evidence": clamp(math.log1p(evidence_count) / math.log1p(8)), "engagement": clamp(math.log1p(max(0, engagement)) / math.log1p(1000)), "persistence": clamp(span_days / 30)}
    return round(sum(STRENGTH_WEIGHTS[k] * parts[k] for k in STRENGTH_WEIGHTS), 3)


def confidence(*, platform_count: int, source_count: int, interval_count: int) -> float: return round(clamp(min(.95, .30 + .25 * max(0, platform_count - 1) + .10 * max(0, source_count - 1) + .10 * min(3, interval_count))), 3)


def explanation_for(members: list[Any], signal_type: str, evidence_count: int, engagement: int, first_seen: str, last_seen: str, recency: float, confidence: float) -> str:
    platforms = sorted({x.platform for x in members}); sources = sorted({x.source for x in members}); span = days_between(first_seen, last_seen)
    return f"{signal_type.capitalize()} signal from {evidence_count} evidence item(s) across {len(platforms)} platform(s) ({', '.join(platforms)}), observed {first_seen[:10]} to {last_seen[:10]}, engagement {engagement}, recency {recency:.2f}, confidence {confidence:.2f}."


def score_signals(clusters: Iterable[Any], *, items: Mapping[str, Any] | None = None, as_of: str | None = None) -> list[SignalItem]:
    result = []
    for cluster in clusters:
        members = [items[eid] for eid in cluster.evidence_ids if items and eid in items] or [cluster]
        timestamps = sorted(x.timestamp for x in members); first, last = timestamps[0], timestamps[-1]
        platforms = len({x.platform for x in members}); sources = len({x.source for x in members}); intervals = len({x[:10] for x in timestamps}) - 1
        div = source_diversity(members); rec = recency_score(last, as_of=as_of); eng = sum(engagement_total(x) for x in members); weighted = sum(engagement_score(x) for x in members); conf = confidence(platform_count=platforms, source_count=sources, interval_count=intervals); kind = signal_type_for(timestamps); value = SignalItem(deterministic_id("sig", cluster.cluster_id), cluster.cluster_id, kind, strength(recency=rec, diversity=div, evidence_count=len(cluster.evidence_ids), engagement=weighted, span_days=days_between(first, last)), conf, div, len(cluster.evidence_ids), eng, first, last, rec, explanation_for(members, kind, len(cluster.evidence_ids), eng, first, last, rec, conf), sorted(cluster.evidence_ids)); validate_signal(value); result.append(value)
    return sorted(result, key=lambda x: (-x.strength, x.cluster_id))


def signals_jsonl(signals: Iterable[SignalItem], path: str) -> int:
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True); values = list(signals)
    with open(path, "w", encoding="utf-8") as handle:
        for value in values: handle.write(value.to_json() + "\n")
    return len(values)
