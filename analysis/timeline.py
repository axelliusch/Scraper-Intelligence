from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable

from analysis.signal_models import parse_utc
from analysis.timeline_models import EntityTrend, IntelligenceTimeline, TimelineDay, TimelineSummary, TopicTrend, validate_timeline


def _topic_status(name: str, events: list[Any], start: str, end: str) -> tuple[str, str]:
    values = sorted(e.event_date for e in events if name in e.topics)
    if not values: return "one-off", f"No observations for {name} in this window."
    unique = sorted(set(values)); span = (parse_utc(unique[-1] + "T00:00:00Z") - parse_utc(unique[0] + "T00:00:00Z")).days
    if len(unique) == 1: return ("new" if unique[0] == start else "one-off", f"{name} was observed on {unique[0]}.")
    if len(unique) >= 3:
        gaps = [(parse_utc(unique[i + 1] + "T00:00:00Z") - parse_utc(unique[i] + "T00:00:00Z")).days for i in range(len(unique) - 1)]
        if gaps[-1] < gaps[0]: return "accelerating", f"Observation intervals shortened across {len(unique)} dates."
        if gaps[-1] > gaps[0]: return "declining", f"Observation intervals lengthened across {len(unique)} dates."
    if span >= 7: return "persistent", f"{name} appeared across {span} days."
    return "recurring", f"{name} appeared on {len(unique)} dates."


def build_timeline(events: Iterable[Any], signals: Iterable[Any], *, start_date: str | None = None, end_date: str | None = None, items: dict[str, Any] | None = None, source_coverage: str = "") -> IntelligenceTimeline:
    events = [e for e in events if not start_date or e.event_date >= start_date if not end_date or e.event_date <= end_date]
    if not events: return IntelligenceTimeline(start_date or "", end_date or "", summary=TimelineSummary(source_coverage=source_coverage))
    start, end = start_date or min(e.event_date for e in events), end_date or max(e.event_date for e in events); by_day: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        if start <= event.event_date <= end: by_day[event.event_date].append(event)
    days = [TimelineDay(day, [e.to_dict() for e in sorted(values, key=lambda x: (-len(x.evidence_ids), x.event_id))]) for day, values in sorted(by_day.items())]
    topics = []
    for name in sorted({topic for e in events for topic in e.topics}):
        related = [e for e in events if name in e.topics]; status, explanation = _topic_status(name, related, start, end); topics.append(TopicTrend(name, min(e.event_date for e in related), max(e.event_date for e in related), len(related), sum(len(e.evidence_ids) for e in related), status, explanation))
    entity_values: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        for name in event.entities: entity_values[name].append(event)
    entities = [EntityTrend(name, "", len(values), min(e.event_date for e in values), max(e.event_date for e in values)) for name, values in sorted(entity_values.items(), key=lambda x: (-len(x[1]), x[0]))]
    summary = TimelineSummary([f"{e.event_date} - {e.canonical_title} ({e.importance})" for e in sorted(events, key=lambda x: (-len(x.evidence_ids), x.event_id))[:5]], [t.name for t in topics if t.status in ("new", "accelerating")], [t.name for t in topics if t.status == "persistent"], [t.name for t in topics if t.status == "declining"], [t.name for t in topics if t.status == "recurring"], [t.name for t in topics if t.status == "disappearing"], [e.name for e in entities[:5]], [t.name for t in sorted(topics, key=lambda x: (-x.evidence_count, x.name))[:5]], [f"{e.event_date}: {e.canonical_title}" for e in sorted(events, key=lambda x: x.event_date)[-3:]], source_coverage)
    value = IntelligenceTimeline(start, end, days, topics, entities, summary); validate_timeline(value); return value


def timeline_to_markdown(timeline: IntelligenceTimeline) -> str:
    lines = [f"# 30-Day Intelligence Timeline - {timeline.start_date} to {timeline.end_date}", "", "## Observed Events", ""]
    for day in timeline.days:
        lines.append(f"### {day.date}")
        lines.extend(f"- {event.get('canonical_title', '')} ({event.get('importance', '')})" for event in day.events)
    lines += ["", "## Topics", ""] + [f"- **{topic.name}** - {topic.status}: {topic.explanation}" for topic in timeline.topics] + ["", "## Source Coverage", "", timeline.summary.source_coverage or "No source coverage statement recorded.", ""]
    return "\n".join(lines)


def timeline_json_file(timeline: IntelligenceTimeline, path: str) -> None:
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(timeline.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
