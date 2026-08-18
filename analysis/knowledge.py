from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable, Mapping
from analysis.knowledge_models import KnowledgeItem, validate_knowledge


def classify_events(events: Iterable[Any], *, topic_status: Mapping[str, str] | None = None) -> list[KnowledgeItem]:
    topic_status = topic_status or {}; output = []
    for event in sorted(events, key=lambda x: (x.event_date, x.event_id)):
        corroborated = event.platform_count >= 2 or event.source_count >= 2 or len(event.evidence_ids) >= 3; recurring = any(topic_status.get(t) in ("persistent", "accelerating", "recurring") for t in event.topics)
        if event.importance in ("critical", "high") and corroborated: decision, action = "KEEP", "Promote as corroborated event knowledge."
        elif event.importance in ("critical", "high", "medium") or recurring: decision, action = "REVIEW", "Human review is required before promotion."
        else: decision, action = "DISCARD", "Low-value or weakly supported observation; raw evidence remains retained."
        value = KnowledgeItem("kn_" + event.event_id.split("_", 1)[-1], event.canonical_title, "event", event.summary, list(event.entities), list(event.topics), [event.event_id], list(event.evidence_ids), event.importance, event.confidence, event.event_date, list(event.source_urls), action, decision); validate_knowledge(value); output.append(value)
    return output


def classify_topics(events: Iterable[Any], timeline_topics: Iterable[Any] | None = None) -> list[KnowledgeItem]:
    events = list(events); output = []
    for topic in sorted(list(timeline_topics or []), key=lambda x: (x.first_seen, x.name)):
        related = [e for e in events if topic.name in e.topics]; evidence = sorted({eid for e in related for eid in e.evidence_ids})
        if not related: continue
        decision = "KEEP" if topic.status in ("persistent", "accelerating", "recurring") else "REVIEW"; value = KnowledgeItem("knt_" + topic.name.lower().replace(" ", "-")[:40], topic.name, "trend", topic.explanation, topics=[topic.name], event_ids=[e.event_id for e in related], evidence_ids=evidence, importance="high" if decision == "KEEP" else "medium", confidence=.60 if decision == "KEEP" else .50, created_date=topic.first_seen, recommended_action="Retain as recurring topic." if decision == "KEEP" else "Keep for human review.", decision=decision); validate_knowledge(value); output.append(value)
    return output


def classify_entities(events: Iterable[Any], *, entity_types: Mapping[str, str] | None = None) -> list[KnowledgeItem]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        for entity in event.entities: groups[entity].append(event)
    output = []
    for name, related in sorted(groups.items()):
        evidence = sorted({eid for e in related for eid in e.evidence_ids}); decision = "KEEP" if len(related) >= 3 else "REVIEW"; value = KnowledgeItem("kne_" + name.lower().replace(" ", "-")[:40], name, "entity", f"{name} appears in {len(related)} event(s) in this observation window.", entities=[name], event_ids=[e.event_id for e in related], evidence_ids=evidence, importance="high" if decision == "KEEP" else "medium", confidence=.70 if decision == "KEEP" else .50, created_date=min(e.event_date for e in related), recommended_action="Promote recurring entity." if decision == "KEEP" else "Review entity context.", decision=decision); validate_knowledge(value); output.append(value)
    return output


def knowledge_jsonl(items: Iterable[KnowledgeItem], path: str) -> int:
    from pathlib import Path
    values = list(items); Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for value in values: handle.write(value.to_json() + "\n")
    return len(values)


def load_knowledge(path: str) -> list[KnowledgeItem]:
    with open(path, encoding="utf-8-sig") as handle: return [KnowledgeItem(**json.loads(line)) for line in handle if line.strip()]
