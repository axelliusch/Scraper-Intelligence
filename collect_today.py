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
NORMALIZED_DIR = ROOT / "data" / "social" / "normalized"
KEY_FILE = ROOT / "data" / ".scrapecreators_key"

LAST30DAYS_ENGINE = ROOT / ".opencode" / "skills" / "last30days" / "scripts" / "last30days.py"

# Project-local engine config (portable: no dependence on the user's home
# profile). Pointed at via LAST30DAYS_CONFIG_DIR so the whole project runs
# with just this folder.
CONFIG_DIR = ROOT / ".config" / "last30days"

# Per BYOK (skill README "Bring Your Own Keys"): Reddit + HN + Polymarket are
# free, YouTube uses yt-dlp, and TikTok/Instagram/LinkedIn/Threads/Pinterest
# use the SCRAPECREATORS_API_KEY. X is excluded (needs XAI/XQUIK key or browser
# login, which we don't have).
LAST30DAYS_SOURCES = "reddit,hackernews,youtube,tiktok,instagram,linkedin,threads,pinterest,polymarket"

# Add or remove a topic here (one line per topic); the Briefings/<display>/
# folder is created automatically by daily_briefing.py.
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


def _load_api_key() -> str:
    env = os.environ.get("SCRAPECREATORS_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        raw = KEY_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return raw.splitlines()[0].strip()
    cfg = CONFIG_DIR / ".env"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("SCRAPECREATORS_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _entity_path(entity: str) -> Path:
    return NORMALIZED_DIR / f"{entity}.jsonl"


def _collect_last30days(topic: dict, *, dry_run: bool) -> int:
    cmd = [
        sys.executable,
        str(ADAPTER),
        "-e", topic["entity"],
        "-t", topic["entity_type"],
        "-q", topic["query"],
        "--engine", str(LAST30DAYS_ENGINE),
        "--allow-all",
        "--search", LAST30DAYS_SOURCES,
    ]
    key = _load_api_key()
    env = {"SCRAPECREATORS_API_KEY": key, "LAST30DAYS_CONFIG_DIR": str(CONFIG_DIR)} if key else None
    return _run(cmd, dry_run=dry_run, env=env)


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
    failed = _collect_last30days(topic, dry_run=dry_run)
    kept, dropped = _filter_last_hours(topic["entity"], keep_hours, dry_run=dry_run)
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