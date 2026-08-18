from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable, Mapping
from analysis.daily_models import DailyDigest, DigestEntity, DigestEvent, DigestSignal, DigestSource, DigestTopic, validate_digest


def _snippet(items: list[Any], limit: int = 400) -> str:
    values = []
    for item in items:
        text = " ".join((getattr(item, "cleaned_text", "") or getattr(item, "text", "")).split())
        if text and text not in values: values.append(text)
    value = " ".join(values); return value[:limit].rstrip() + ("..." if len(value) > limit else "")


def build_daily_digests(events: Iterable[Any], signals: Iterable[Any], *, items: Mapping[str, Any] | None = None, title_for: Mapping[str, Any] | None = None) -> list[DailyDigest]:
    events = list(events); signals = list(signals); items = items or {}; by_day: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        days = {items[eid].timestamp[:10] for eid in event.evidence_ids if eid in items} or {event.event_date}
        for day in days: by_day[day].append(event)
    topic_first = {topic: min(e.event_date for e in events if topic in e.topics) for topic in {t for e in events for t in e.topics}}
    output = []
    for day in sorted(by_day):
        day_events = sorted(by_day[day], key=lambda x: ({"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}.get(x.importance, 5), x.event_id)); important = [e for e in day_events if e.importance in ("critical", "high", "medium")]; other = [e for e in day_events if e not in important]
        def convert(event):
            members = [items[eid] for eid in event.evidence_ids if eid in items and items[eid].timestamp[:10] == day]
            return DigestEvent(event.event_id, event.canonical_title, event.first_seen, event.event_type, list(event.entities), list(event.topics), event.importance, event.confidence, event.summary, sorted(x.evidence_id for x in members), sorted({x.platform for x in members}), sorted({x.url for x in members if x.url}), _snippet(members))
        topics = [DigestTopic(t, sum(len(e.evidence_ids) for e in day_events if t in e.topics), day, "First appearance in the observed window.") for t in sorted(topic_first) if topic_first[t] == day]
        ent_counts: dict[str, int] = defaultdict(int)
        for event in day_events:
            for ent in event.entities: ent_counts[ent] += 1
        sources: dict[str, set[str]] = defaultdict(set)
        for event in day_events:
            for eid in event.evidence_ids:
                item = items.get(eid)
                if item and item.timestamp[:10] == day and item.url: sources[item.platform].add(item.url)
        active = [DigestSignal(s.signal_id, s.signal_type, s.strength, s.confidence, (title_for or {}).get(s.cluster_id, "")) for s in signals if s.first_seen[:10] <= day <= s.last_seen[:10]]
        summary = f"No significant developments were reported on {day}." if not important else f"{len(important)} important development(s) were reported on {day}. Most significant: {important[0].canonical_title}."
        digest = DailyDigest(day, summary, [convert(e) for e in important], [convert(e) for e in other], topics, [DigestEntity(name, "", count) for name, count in sorted(ent_counts.items(), key=lambda x: (-x[1], x[0]))], sorted(active, key=lambda x: (-x.strength, x.signal_id)), "OBSERVED: the digest contains only evidence dated on this day. INTERPRETATION: independent corroboration is limited unless multiple platforms are listed.", [DigestSource(platform, len(urls), sorted(urls)) for platform, urls in sorted(sources.items())]); validate_digest(digest); output.append(digest)
    return output


def digest_to_markdown(digest: DailyDigest) -> str:
    lines = [f"# Daily Intelligence - {digest.date}", "", "## Executive Summary", "", digest.executive_summary, ""]
    for heading, events in (("Important Events", digest.important_events), ("Other Notable Events", digest.other_events)):
        if events:
            lines += [f"## {heading}", ""]
            for event in events:
                lines.append(f"- **{event.title}** - {event.category} - importance {event.importance} - confidence {event.confidence:.2f}")
                if event.snippet: lines.append(f"  - {event.snippet}")
            lines.append("")
    if digest.emerging_topics: lines += ["## Emerging Topics", ""] + [f"- {x.name} ({x.evidence_count} evidence item(s))" for x in digest.emerging_topics] + [""]
    if digest.why_it_matters: lines += ["## Why It Matters", "", digest.why_it_matters, ""]
    return "\n".join(lines).rstrip() + "\n"


def digest_json_file(digest: DailyDigest, path: str) -> None:
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(digest.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
