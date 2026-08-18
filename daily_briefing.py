"""Daily 36h topic briefing renderer (no project-code changes).

For each topic in TOPICS it runs the pipeline against the fresh 36h corpus
collected by collect_today.py, then renders a Markdown briefing into:

    Briefings/<Display>/<Display> - <DD Mon YYYY>.md

The file is divided by social platform. Content is observational only: it is
built from the normalized records and the pipeline's digest output; nothing is
invented.

Usage:
  python daily_briefing.py                 # all topics, as-of today
  python daily_briefing.py --topics Finance
  python daily_briefing.py --as-of 2026-08-17
  python daily_briefing.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PIPELINE = ROOT / "run_pipeline.py"
NORMALIZED_DIR = ROOT / "data" / "social" / "normalized"
DAILY_DIR = ROOT / "data" / "daily"
REPORTS_DIR = ROOT / "Briefings"

TOPICS: list[dict] = [
    {
        "entity": "property-market",
        "display": "Property",
        "entity_type": "topic",
        "query": "property market",
    },
    {
        "entity": "wedding",
        "display": "Wedding",
        "entity_type": "topic",
        "query": "wedding planning",
    },
    {
        "entity": "finance",
        "display": "Finance",
        "entity_type": "topic",
        "query": "personal finance",
    },
]

ENGAGEMENT_KEYS = (
    "likes", "upvotes", "comments", "shares", "views", "reposts",
    "reactions", "saves", "stars", "forks", "points", "issues",
)

PLATFORM_LABELS: dict[str, str] = {
    "reddit": "Reddit",
    "hackernews": "Hacker News",
    "x": "X (Twitter)",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "threads": "Threads",
    "pinterest": "Pinterest",
    "polymarket": "Polymarket",
    "web": "Web",
    "telegram": "Telegram",
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _format_day(value: str) -> str:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return value[:10]


def _entity_path(entity: str) -> Path:
    return NORMALIZED_DIR / f"{entity}.jsonl"


def _engagement_total(record: dict[str, Any]) -> int:
    eng = record.get("engagement") or {}
    total = 0
    if isinstance(eng, dict):
        for key in ENGAGEMENT_KEYS:
            try:
                total += int(eng.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return total


def _engagement_label(record: dict[str, Any]) -> str:
    eng = record.get("engagement") or {}
    if not isinstance(eng, dict):
        return ""
    parts = []
    for key in ENGAGEMENT_KEYS:
        value = eng.get(key)
        if value in (None, ""):
            continue
        try:
            parts.append(f"{int(value)} {key}")
        except (TypeError, ValueError):
            continue
    return " | ".join(parts) if parts else ""


def _load_records(entity: str, as_of: str) -> list[dict[str, Any]]:
    path = _entity_path(entity)
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    end = as_of[:10]
    try:
        from datetime import timedelta
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d")
    except ValueError:
        start = end
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = str(record.get("timestamp") or "")
        if not start <= ts[:10] <= end:
            continue
        records.append(record)
    return records


def _by_platform(records: list[dict[str, Any]], max_per: int = 10) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        platform = str(record.get("platform") or "unknown")
        grouped.setdefault(platform, []).append(record)
    if not grouped:
        return "No records collected for this window.\n"
    lines: list[str] = []
    for platform in sorted(grouped, key=lambda p: -len(grouped[p])):
        label = PLATFORM_LABELS.get(platform, platform)
        items = sorted(grouped[platform], key=_engagement_total, reverse=True)[:max_per]
        lines.append(f"### {label} ({len(grouped[platform])})")
        for record in items:
            title = str(record.get("title") or "").strip()
            text = str(record.get("text") or "").strip()
            snippet = title or (text[:200] + ("..." if len(text) > 200 else "") if text else "(no text)")
            author = (record.get("author") or {}).get("name") or "unknown"
            url = str(record.get("url") or "").strip()
            engagement = _engagement_label(record)
            line = f"- **{snippet}**"
            if url:
                line += f" - [{url}]({url})"
            line += f" - by {author}"
            if engagement:
                line += f" - {engagement}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def _load_digest(as_of: str) -> dict[str, Any] | None:
    path = DAILY_DIR / f"{as_of[:10]}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _events_section(digest: dict[str, Any] | None) -> str:
    if not digest:
        return "_No digest produced for this window._\n"
    events = digest.get("important_events") or []
    if not events:
        return "_No important events flagged for this window._\n"
    lines = []
    for event in events:
        lines.append(
            f"- **{event.get('title')}** - {event.get('category')} - "
            f"importance {event.get('importance')} - confidence {event.get('confidence')}"
        )
        if event.get("snippet"):
            lines.append(f"  - {event['snippet']}")
    lines.append("")
    return "\n".join(lines)


def _signals_section(digest: dict[str, Any] | None) -> str:
    if not digest:
        return "_No signals for this window._\n"
    signals = digest.get("signals") or []
    if not signals:
        return "_No signals flagged for this window._\n"
    lines = []
    for signal in signals:
        title = signal.get("title") or str(signal.get("explanation") or "")
        lines.append(f"- **{signal.get('signal_type')}** ({signal.get('strength')}) - {title}")
    lines.append("")
    return "\n".join(lines)


def _coverage_section(records: list[dict[str, Any]], digest: dict[str, Any] | None) -> str:
    counts: dict[str, int] = {}
    for record in records:
        platform = str(record.get("platform") or "unknown")
        counts[platform] = counts.get(platform, 0) + 1
    lines = []
    if counts:
        lines.append(
            "Contributing platforms: "
            + ", ".join(
                f"{PLATFORM_LABELS.get(name, name)} ({count})"
                for name, count in sorted(counts.items())
            )
            + "."
        )
    else:
        lines.append("No platforms contributed records this window.")
    if digest:
        sources = digest.get("sources") or []
        if sources:
            lines.append(
                "Digest sources: "
                + ", ".join(
                    f"{PLATFORM_LABELS.get(s.get('platform'), s.get('platform'))} ({s.get('count')})"
                    for s in sources
                )
                + "."
            )
    lines.append(
        "Platforms not listed were not observed in this window; they must not be described as searched."
    )
    return "\n".join(lines)


def _render(topic: dict[str, Any], as_of: str, *, dry_run: bool) -> dict[str, Any]:
    entity = topic["entity"]
    display = topic["display"]
    day_label = _format_day(as_of)

    cmd = [
        sys.executable,
        str(PIPELINE),
        entity,
        "--as-of", as_of,
        "--window-days", "2",
        "--skip-collection",
        "--no-report",
    ]
    print(f"\n=== {display} ({entity}) ===")
    print("  $ " + " ".join(str(x) for x in cmd))
    if dry_run:
        return {"entity": entity, "output": None}

    proc = subprocess.run(
        [str(x) for x in cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    summary = ""
    for line in (proc.stdout or "").splitlines():
        print("    " + line)
    if proc.returncode != 0:
        for line in (proc.stderr or "").splitlines():
            print("    " + line, file=sys.stderr)
        raise RuntimeError(f"pipeline failed for {entity} (exit {proc.returncode})")
    tail = (proc.stdout or "").strip().splitlines()
    if tail:
        try:
            summary = json.loads(tail[-1])
        except (json.JSONDecodeError, IndexError):
            summary = {}

    records = _load_records(entity, as_of)
    digest = _load_digest(as_of)

    lines = [
        f"# {display} - {day_label}",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | "
        f"Observation window: last 36h ending {day_label}",
        "",
        "## Executive Summary",
        "",
    ]
    if digest and digest.get("executive_summary"):
        lines.append(digest["executive_summary"])
        lines.append("")
    else:
        lines.append("_No digest produced for this window._")
        lines.append("")

    lines += ["## By platform", "", _by_platform(records)]
    lines += ["## Important events", "", _events_section(digest)]
    lines += ["## Signals", "", _signals_section(digest)]
    lines += ["## Source coverage", "", _coverage_section(records, digest), ""]

    body = "\n".join(lines).rstrip() + "\n"

    out_dir = REPORTS_DIR / display
    out_path = out_dir / f"{display} - {day_label}.md"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
    print(f"  wrote: {out_path} ({len(records)} records)")
    return {"entity": entity, "output": str(out_path), "records": len(records)}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Daily 36h topic briefing renderer")
    parser.add_argument("--topics", default="", help="comma-separated display names; default all")
    parser.add_argument("--as-of", default="", help="YYYY-MM-DD; default today")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    as_of = args.as_of or _today()
    topics = TOPICS
    if args.topics:
        names = {t.strip().lower() for t in args.topics.split(",") if t.strip()}
        topics = [t for t in TOPICS if t["display"].lower() in names]

    results = []
    for topic in topics:
        try:
            results.append(_render(topic, as_of, dry_run=args.dry_run))
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            results.append({"entity": topic["entity"], "output": None})

    for result in results:
        status = result["output"] or ("DRY-RUN OK" if args.dry_run else "FAILED")
        print(f"{result['entity']}: {status}")
    return 0 if (args.dry_run or all(r["output"] for r in results)) else 1


if __name__ == "__main__":
    raise SystemExit(main())