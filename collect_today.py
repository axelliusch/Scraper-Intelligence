"""Daily topic collector wrapper (no project-code changes).

Collects one fresh corpus per topic, spanning only the last 36 hours,
through the last30days engine (Bring Your Own Key setup per the skill README):

  - reddit, hackernews, polymarket: free, no key
  - youtube: yt-dlp (free CLI)
  - tiktok, instagram, linkedin, threads, pinterest: SCRAPECREATORS_API_KEY
    (consumed by the engine from the project-local .config/last30days/.env)

X is excluded: per BYOK it needs XAI_API_KEY / XQUIK_API_KEY or a browser
login, not the ScrapeCreators key.

Every step appends to data/social/normalized/<entity>.jsonl; the corpus is
wiped per topic first so there is no 30-day accumulation, then re-filtered to
the last 36h so stale records never enter the daily briefing.

Usage:
  python collect_today.py                 # all topics in TOPICS
  python collect_today.py --topics Property
  python collect_today.py --dry-run
  python collect_today.py --keep-hours 36
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADAPTER = ROOT / "scrapers" / "last30days_adapter.py"
RUN_COLLECTOR = ROOT / "scrapers" / "run_collector.py"
NORMALIZED_DIR = ROOT / "data" / "social" / "normalized"
KEY_FILE = ROOT / "data" / ".scrapecreators_key"

LAST30DAYS_ENGINE = ROOT / ".opencode" / "skills" / "last30days" / "scripts" / "last30days.py"

# Project-local engine config (portable: no dependence on the user's home
# profile). Pointed at via LAST30DAYS_CONFIG_DIR so the whole project runs
# with just this folder.
CONFIG_DIR = ROOT / ".config" / "last30days"

# Per BYOK (skill README "Bring Your Own Keys"): Reddit + HN + Polymarket are
# free, YouTube uses yt-dlp, TikTok/Instagram/LinkedIn/Threads/Pinterest use
# the SCRAPECREATORS_API_KEY, and X uses the browser cookie (FROM_BROWSER in
# the engine config; requires a Firefox profile logged into x.com).
LAST30DAYS_SOURCES = "reddit,hackernews,youtube,tiktok,instagram,linkedin,threads,pinterest,polymarket,x"

# Add or remove a topic here (one line per topic); the Briefings/<display>/
# folder is created automatically by daily_briefing.py.
#
# `location` is appended to the engine query so every platform in the run is
# scoped to that country (the whole pipeline's geographic filter). Telegram has
# no topic search; it collects from the public channel(s) listed under
# `telegram_channels` (verified Australian channels only, t.me/s/<channel>).
TOPICS: list[dict] = [
    {
        "entity": "property-market",
        "display": "Property",
        "entity_type": "topic",
        "query": "property market",
        "location": "Australia",
        "telegram_channels": ["AUProperty"],
        "linkedin_companies": [
            "https://www.linkedin.com/company/oliver-hume",
            "https://www.linkedin.com/company/colliers",
            "https://www.linkedin.com/company/laverresidentialprojects",
            "https://www.linkedin.com/company/mmj-real-estate",
            "https://www.linkedin.com/company/slaite-project-marketing",
            "https://www.linkedin.com/company/360-property-group",
            "https://www.linkedin.com/company/1group-property-advisory",
        ],
    },
    {
        "entity": "wedding",
        "display": "Wedding",
        "entity_type": "topic",
        "query": "wedding planning",
        "location": "World",
        "linkedin_companies": [
            "https://www.linkedin.com/company/jkandco",
            "https://www.linkedin.com/company/a-lavish-affair",
            "https://www.linkedin.com/company/bowcreative",
            "https://www.linkedin.com/company/mills-franks",
            "https://www.linkedin.com/company/lux-it",
            "https://www.linkedin.com/company/mcmillanmgmt",
        ],
    },
    {
        "entity": "finance",
        "display": "Finance",
        "entity_type": "topic",
        "query": "personal finance",
        "location": "Australia",
        "telegram_channels": ["ASXAnalysis"],
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], *, dry_run: bool, env: dict[str, str] | None = None) -> int:
    print("  $ " + " ".join(str(x) for x in cmd))
    if dry_run:
        return 0
    try:
        proc = subprocess.run(
            [str(x) for x in cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            env={**os.environ, **(env or {})},
        )
    except subprocess.TimeoutExpired:
        print("    [TIMEOUT]", file=sys.stderr)
        return 1
    for line in (proc.stdout or "").splitlines():
        print("    " + line)
    if proc.returncode != 0:
        for line in (proc.stderr or "").splitlines():
            print("    " + line, file=sys.stderr)
    return proc.returncode


# Every place a SCRAPECREATORS_API_KEY can live, newest edit wins so a key
# pasted into any of them is picked up automatically on the next run.
_API_KEY_SOURCES = [
    KEY_FILE,
    CONFIG_DIR / ".env",
    Path.home() / ".config" / "last30days" / ".env",
]


def _load_api_key() -> str:
    env = os.environ.get("SCRAPECREATORS_API_KEY", "").strip()
    if env:
        return env
    candidates: list[tuple[float, str]] = []
    for path in _API_KEY_SOURCES:
        if not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key = line.split("=", 1)[1].strip() if line.startswith("SCRAPECREATORS_API_KEY=") else line
            if key:
                candidates.append((mtime, key))
                break
    if not candidates:
        return ""
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def _entity_path(entity: str) -> Path:
    return NORMALIZED_DIR / f"{entity}.jsonl"


def _collect_last30days(topic: dict, *, dry_run: bool) -> int:
    query = str(topic["query"]).strip()
    location = str(topic.get("location") or "").strip()
    if location:
        query = f"{query} {location}"
    cmd = [
        sys.executable,
        str(ADAPTER),
        "-e", topic["entity"],
        "-t", topic["entity_type"],
        "-q", query,
        "--engine", str(LAST30DAYS_ENGINE),
        "--allow-all",
        "--search", LAST30DAYS_SOURCES,
    ]
    linkedin_companies = topic.get("linkedin_companies") or []
    if linkedin_companies:
        cmd += ["--linkedin-companies", ",".join(linkedin_companies)]
    key = _load_api_key()
    env = {"SCRAPECREATORS_API_KEY": key, "LAST30DAYS_CONFIG_DIR": str(CONFIG_DIR)} if key else None
    return _run(cmd, dry_run=dry_run, env=env)


def _telegram_records(entity: str) -> int:
    """Count telegram-platform records currently written for an entity."""
    path = _entity_path(entity)
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(record.get("platform") or "") == "telegram":
            count += 1
    return count


def _collect_telegram(topic: dict, *, dry_run: bool) -> dict:
    """Collect from the topic's verified Australian Telegram channels.

    Runs before the last30days adapter so its records land first in the
    entity corpus (the adapter appends and counts them in the coverage report).
    A channel failure is non-fatal: the topic still collects from the engine.
    """
    channels = [str(c).strip() for c in (topic.get("telegram_channels") or []) if str(c).strip()]
    result = {
        "entity": topic["entity"],
        "channels": len(channels),
        "outcome": "no-channel",
        "records": 0,
        "errors": [],
    }
    if not channels:
        return result
    for channel in channels:
        cmd = [
            sys.executable,
            str(RUN_COLLECTOR),
            "--source", "telegram",
            "-e", topic["entity"],
            "-t", topic["entity_type"],
            "--channel", channel,
            "--location", str(topic.get("location") or ""),
            "--allow-all",
        ]
        rc = _run(cmd, dry_run=dry_run)
        if rc != 0:
            result["errors"].append(channel)
    result["outcome"] = "error" if result["errors"] else "ok"
    if not dry_run:
        result["records"] = _telegram_records(topic["entity"])
    return result


def _record_telegram_coverage(entity: str, result: dict, *, dry_run: bool) -> None:
    """Patch the coverage entry (written by the adapter) with Telegram's outcome."""
    if dry_run or result["outcome"] == "no-channel":
        return
    sys.path.insert(0, str(ROOT / "scrapers"))
    try:
        from coverage import update_coverage_entry
    except ImportError:
        return
    if result["outcome"] == "error":
        update_coverage_entry(
            entity,
            platform="telegram",
            engine_state="error",
            status="ERROR",
            records=result["records"],
            error=f"Telegram collection failed for channel(s): {', '.join(result['errors'])}",
        )
        return
    has_records = result["records"] > 0
    update_coverage_entry(
        entity,
        platform="telegram",
        engine_state="ok" if has_records else "no-results",
        status="AVAILABLE" if has_records else "NO_RESULTS",
        records=result["records"],
    )


def _filter_last_hours(entity: str, hours: int, *, dry_run: bool) -> tuple[int, int]:
    path = _entity_path(entity)
    if dry_run:
        return 0, 0
    if not path.exists():
        return 0, 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept: list[str] = []
    dropped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            dropped += 1
            continue
        ts = str(record.get("timestamp") or "")
        if not ts:
            dropped += 1
            continue
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            dropped += 1
            continue
        if parsed.astimezone(timezone.utc) >= cutoff:
            kept.append(line)
        else:
            dropped += 1
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return len(kept), dropped


def _platform_counts(entity: str) -> dict[str, int]:
    path = _entity_path(entity)
    counts: dict[str, int] = {}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        platform = str(record.get("platform") or "unknown")
        counts[platform] = counts.get(platform, 0) + 1
    return counts


def collect_topic(topic: dict, *, dry_run: bool, keep_hours: int) -> dict:
    print(f"\n=== {topic['display']} ({topic['entity']}) ===")
    path = _entity_path(topic["entity"])
    if not dry_run:
        NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
    telegram = _collect_telegram(topic, dry_run=dry_run)
    failed = _collect_last30days(topic, dry_run=dry_run)
    _record_telegram_coverage(topic["entity"], telegram, dry_run=dry_run)
    kept, dropped = _filter_last_hours(topic["entity"], keep_hours, dry_run=dry_run)
    print(f"  telegram: {telegram['outcome']} ({telegram['records']} record(s), {telegram['channels']} channel(s))")
    print(f"  after {keep_hours}h filter: kept {kept}, dropped {dropped}")
    print(f"  platforms: {_platform_counts(topic['entity']) or 'none'}")
    return {"entity": topic["entity"], "failed_steps": failed, "kept": kept}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Daily 36h topic collector wrapper")
    parser.add_argument("--topics", default="", help="comma-separated display names; default all")
    parser.add_argument("--keep-hours", type=int, default=36)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    topics = TOPICS
    if args.topics:
        names = {t.strip().lower() for t in args.topics.split(",") if t.strip()}
        topics = [t for t in TOPICS if t["display"].lower() in names]

    results = []
    for topic in topics:
        results.append(collect_topic(topic, dry_run=args.dry_run, keep_hours=args.keep_hours))

    for result in results:
        print(f"{result['entity']}: failed_steps={result['failed_steps']} kept={result['kept']}")
    return 0 if all(r["failed_steps"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())