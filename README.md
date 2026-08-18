# Scraper Intelligence

Daily social-media intelligence briefings. Every day it collects fresh posts
from a set of social platforms, analyzes them into evidence-backed events,
signals and trends, and renders one Markdown briefing per topic.

Everything runs locally with no LLM at runtime. Collection uses the
`last30days` research engine (vendored in `.opencode/skills/last30days`).

## What you get each day

`Briefings/<Display>/<Display> - DD Mon YYYY.md` per topic, with:

- Executive Summary
- By platform (top posts by engagement)
- Important events
- Signals
- Source coverage

## Platforms

Configured in `collect_today.py` (`LAST30DAYS_SOURCES`): Reddit, Hacker News,
YouTube, TikTok, Instagram, LinkedIn, Threads, Pinterest, Polymarket.

Per the engine's "Bring Your Own Key" model:

| Platform | Requirement |
| --- | --- |
| Reddit, Hacker News, Polymarket | free, no key |
| YouTube | `yt-dlp` (free CLI, auto-installed by `setup.bat`) |
| TikTok, Instagram, LinkedIn, Threads, Pinterest | `SCRAPECREATORS_API_KEY` |
| X / Twitter | `XAI_API_KEY` / `XQUIK_API_KEY` or browser login (not enabled by default) |

## Quick start (new machine)

Requirements: Python 3.13 (free, from python.org), internet.

1. Copy the whole folder.
2. Run `setup.bat` once — detects Python, builds the project-local engine
   config from `data\.scrapecreators_key` (if present), installs `yt-dlp`.
3. Test manually:
   - `daily_run.bat` — collects then renders briefings (takes a few minutes)
   - `python collect_today.py --dry-run` — plan only, no network
4. (Optional) Schedule it: double-click `install_task.bat` as Administrator to
   register the daily 7:30AM task.

## Collection window

The corpus is wiped per topic and re-filtered to the **last 36 hours** before
the briefing is rendered, so each briefing covers only recent content.

## Files

| Path | Purpose |
| --- | --- |
| `collect_today.py` | Daily collector wrapper (engine invocation + 36h filter) |
| `daily_briefing.py` | Runs the pipeline and renders the Markdown briefing |
| `daily_run.bat` | One-click daily flow: collect → render → log |
| `setup.bat` | One-time setup (Python detect, config, yt-dlp) |
| `install_task.bat` | Registers the daily 7:30AM scheduled task |
| `.config/last30days/.env` | Project-local engine config (ScrapeCreators key) — not committed |
| `.opencode/skills/last30days/` | Vendored last30days research engine |
| `scrapers/` | Adapters + schema enforcement for the project pipeline |
| `run_pipeline.py` | Offline analysis pipeline (evidence → events → briefings) |
| `Briefings/` | Rendered daily briefings |
| `logs/daily_run_DD-MM-YYYY.log` | Per-day run log |
| `obsidian/`, `dashboard/`, `reports/` | Optional pipeline outputs (briefings do not need them) |

## Data

Normalized records live in `data/social/normalized/<entity>.jsonl` (schema in
`data/social/SCHEMA.md`). Topics are defined in `collect_today.py` (`TOPICS`):
add or remove one line per topic.

## Design principles

- **No LLM at runtime** — analysis is deterministic, keyword/pattern-driven.
- **Evidence-first** — every event is backed by the exact source URLs.
- **Conservative** — raw text is preserved verbatim; nothing is invented.
- **Portable** — the folder is self-contained; only Python 3.13 is needed on a
  new machine.
