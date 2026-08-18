from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

LINK_STYLES = ("wikilink", "mdlink", "both")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "item"


def _platform_of_url(url: str) -> str:
    value = (url or "").lower()
    for key in ("reddit", "github", "youtube", "telegram", "x.com", "twitter", "instagram", "linkedin"):
        if key in value: return "x" if key in ("x.com", "twitter") else key
    return "web"


def _link(name: str, folder: str, style: str) -> str:
    slug = _slug(name); target = f"../{folder}/{slug}.md"
    wiki = f"[[{slug}|{name}]]"; md = f"[{name}]({target})"
    if style == "mdlink": return md
    if style == "both": return f"{wiki} {md}"
    return wiki


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(body, encoding="utf-8-sig")


def export_obsidian_vault(root: str | Path, *, digests: Iterable[Any], events: Iterable[Any], topics: Iterable[Any], entities: Iterable[Any], trends: Iterable[Any], knowledge: Iterable[Any], link_style: str = "wikilink") -> dict[str, int]:
    if link_style not in LINK_STYLES: raise ValueError(f"unknown link style: {link_style}")
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    counts = {name: 0 for name in ("Daily", "Events", "Topics", "Entities", "Trends", "Sources")}
    events = list(events); topics = list(topics); entities = list(entities); digests = list(digests)
    index_links = []
    for digest in digests:
        lines = ["---", "type: daily", f"date: {digest.date}", "---", "", "# Daily Intelligence", "", digest.executive_summary, ""]
        for event in digest.important_events + digest.other_events:
            lines += [f"## {event.title}", "", event.snippet or event.explanation, "", "Sources:", *[f"- {url}" for url in event.source_urls], ""]
        _write(root / "Daily" / f"{digest.date}.md", "\n".join(lines)); counts["Daily"] += 1
    for event in events:
        lines = ["---", "type: event", f"date: {event.event_date}", f"importance: {event.importance}", f"confidence: {event.confidence}", "---", "", f"# {event.canonical_title}", "", event.summary, "", "## Topics", "", " ".join(_link(x, "Topics", link_style) for x in event.topics), "", "## Entities", "", " ".join(_link(x, "Entities", link_style) for x in event.entities), "", "## Evidence URLs", "", *[f"- {url}" for url in event.source_urls]]
        _write(root / "Events" / f"{_slug(event.canonical_title)}.md", "\n".join(lines)); counts["Events"] += 1
    for topic in topics:
        related = [e for e in events if topic.name in e.topics]
        body = ["---", "type: topic", f"status: {topic.status}", f"date: {topic.first_seen}", "---", "", f"# {topic.name}", "", topic.explanation, "", "## Related Events", "", *[f"- {_link(e.canonical_title, 'Events', link_style)}" for e in related]]
        _write(root / "Topics" / f"{_slug(topic.name)}.md", "\n".join(body)); _write(root / "Trends" / f"{_slug(topic.name)}.md", "\n".join(body)); counts["Topics"] += 1; counts["Trends"] += 1
    for entity in entities:
        related = [e for e in events if entity.name in e.entities]
        body = ["---", "type: entity", f"date: {entity.first_seen}", "---", "", f"# {entity.name}", "", *[f"- {_link(e.canonical_title, 'Events', link_style)}" for e in related]]
        _write(root / "Entities" / f"{_slug(entity.name)}.md", "\n".join(body)); counts["Entities"] += 1
    urls = sorted({url for e in events for url in e.source_urls})
    by_platform: dict[str, list[str]] = {}
    for url in urls: by_platform.setdefault(_platform_of_url(url), []).append(url)
    source_body = ["# Sources", "", *[f"## {platform}\n" + "\n".join(f"- {url}" for url in values) for platform, values in sorted(by_platform.items())]]
    _write(root / "Sources" / "Index.md", "\n".join(source_body)); counts["Sources"] += 1
    research = ["# Research Index", "", "## Events", "", *[f"- {_link(e.canonical_title, 'Events', link_style)}" for e in events], "", "## Topics", "", *[f"- {_link(t.name, 'Topics', link_style)}" for t in topics]]
    _write(root / "Research" / "Index.md", "\n".join(research))
    for folder, values in (("Events", events), ("Topics", topics), ("Entities", entities), ("Trends", topics), ("Daily", digests)):
        _write(root / "MOCs" / f"{folder.lower()}-moc.md", f"# {folder}\n\n" + "\n".join(f"- {getattr(x, 'date', getattr(x, 'canonical_title', getattr(x, 'name', '')))}" for x in values))
    _write(root / "MOCs" / "Index.md", "# Intelligence Index\n\n" + "\n".join(f"- {_link(folder, folder, link_style)}" for folder in ("Events", "Topics", "Entities", "Trends", "Daily")))
    return counts
