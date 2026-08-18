from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Mapping

from analysis.event_models import EVENT_TYPES, EventItem, importance_for_score, validate_event
from analysis.extraction_models import contains_term, deterministic_id, evidence_searchable
from analysis.signal_models import clamp, days_between, engagement_score, engagement_total

EVENT_TYPE_RULES = (
    ("funding", ("funding", "investment", "valuation", "raises")), ("acquisition", ("acquisition", "acquires", "acquired")),
    ("partnership", ("partnership", "collaboration", "partners")), ("product_launch", ("launch", "unveils", "introduces")),
    ("model_release", ("model", "benchmark", "leaderboard")), ("research_publication", ("paper", "research", "study", "arxiv")),
    ("regulatory_development", ("regulation", "regulator", "policy", "government", "ban")), ("market_development", ("market", "prices", "sales", "demand")),
    ("controversy", ("controversy", "backlash", "criticism", "risk")), ("major_update", ("update", "updated", "release")),
    ("major_discussion", ("discussion", "debate", "opinion", "thread")),
)


def classify_event_type(members: list[Any]) -> str:
    counts: Counter[str] = Counter()
    for member in members:
        surface = evidence_searchable(member); found = "other"
        for name, terms in EVENT_TYPE_RULES:
            if any(contains_term(surface, term) for term in terms): found = name; break
        counts[found] += 1
    return max(counts, key=lambda name: (counts[name], -([x[0] for x in EVENT_TYPE_RULES] + ["other"]).index(name))) if counts else "other"


def extract_events(clusters: Iterable[Any], signals: Iterable[Any], *, items: Mapping[str, Any] | None = None, as_of: str | None = None) -> list[EventItem]:
    signals_by_cluster = {x.cluster_id: x for x in signals}; result = []
    for cluster in clusters:
        members = [items[eid] for eid in cluster.evidence_ids if items and eid in items]
        if not members: continue
        members.sort(key=lambda x: (x.timestamp, x.evidence_id)); first, last = members[0].timestamp, members[-1].timestamp; signal = signals_by_cluster.get(cluster.cluster_id); conf = signal.confidence if signal else .30
        recency = 1.0 if not as_of else max(0.0, 1.0 - max(0, days_between(last, as_of + "T00:00:00Z")) / 30)
        diversity = clamp((cluster.platform_count + .5 * (cluster.source_count - 1)) / 3); coverage = clamp(math.log1p(len(members)) / math.log1p(8)); persistence = clamp(days_between(first, last) / 30); engagement = clamp(math.log1p(sum(engagement_score(x) for x in members)) / math.log1p(1000)); score = round(.25 * diversity + .25 * coverage + .15 * persistence + .20 * conf + .10 * recency + .05 * engagement, 3); title = next((x.title or x.cleaned_text or x.text for x in members), cluster.canonical_title).strip()[:160]
        value = EventItem(deterministic_id("evt", cluster.cluster_id), title or cluster.canonical_title, classify_event_type(members), first[:10], first, last, sorted(cluster.entities), sorted(cluster.topics), sorted(cluster.evidence_ids), cluster.source_count, cluster.platform_count, sorted({x.platform for x in members}), conf, importance_for_score(score), f"{title or cluster.canonical_title}. Reported earliest on {first[:10]} and observed through {last[:10]} from {len(members)} evidence item(s).", f"Reported earliest on {first[:10]}; this is the evidence report date, not an inferred occurrence date.", sorted({x.url for x in members if x.url}), cluster.cluster_id, signal.signal_id if signal else ""); validate_event(value); result.append(value)
    return sorted(result, key=lambda x: (x.event_date, x.event_id))


def events_jsonl(events: Iterable[EventItem], path: str) -> int:
    from pathlib import Path
    values = list(events); Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for value in values: handle.write(value.to_json() + "\n")
    return len(values)


def load_events(path: str) -> list[EventItem]:
    import json
    with open(path, encoding="utf-8-sig") as handle: return [EventItem(**json.loads(line)) for line in handle if line.strip()]
