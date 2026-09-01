# Scraper Intelligence — Detailed Project Brief

**Version:** 1.1
**Date:** 2026-09-01
**Author:** Project maintainer (hand-off brief)
**Audience:** The next person taking over this project, or anyone who needs to
duplicate, install, or operate it on their own machine.

This document explains everything about the project: what it is, how it works,
every file and configuration, how to duplicate it for the next user, how to
install it on a fresh computer, and how to connect its output to Obsidian.md.

---

## Table of contents

1. [What the project is](#1-what-the-project-is)
2. [High-level workflow](#2-high-level-workflow)
3. [Architecture and file map](#3-architecture-and-file-map)
4. [Platforms, keys, and credentials](#4-platforms-keys-and-credentials)
5. [Topics and geographic scoping](#5-topics-and-geographic-scoping)
6. [Collection health reporting](#6-collection-health-reporting)
7. [The 36-hour window](#7-the-36-hour-window)
8. [ScrapeCreators API key — full resolution rules](#8-scrapecreators-api-key--full-resolution-rules)
9. [The daily outputs](#9-the-daily-outputs)
10. [Duplicating / sending to the next user](#10-duplicating--sending-to-the-next-user)
11. [Fresh install on a new Windows computer](#11-fresh-install-on-a-new-windows-computer)
12. [Scheduling daily runs](#12-scheduling-daily-runs)
13. [Connecting to Obsidian.md](#13-connecting-to-obsidianmd)
14. [Troubleshooting guide](#14-troubleshooting-guide)
15. [Data schema (records contract)](#15-data-schema-records-contract)
16. [Frequently asked questions](#16-frequently-asked-questions)

---

## 1. What the project is

**Scraper Intelligence** is a portable, fully local **daily social-media
intelligence** system. Every day it:

1. **Collects** fresh posts about a set of topics from a range of social
   platforms (Reddit, Hacker News, YouTube, TikTok, Instagram, LinkedIn,
   Threads, Pinterest, Polymarket, X/Twitter, and public Telegram channels).
2. **Analyzes** the collected data into evidence-backed events, signals, and
   trends — deterministically, with no LLM at runtime.
3. **Renders** one Markdown briefing per topic containing an executive
   summary, top posts by platform, important events, signals, source coverage,
   and a "collection health" table that explains why each platform produced
   what it did (or nothing).

Everything runs **locally** and the project is **self-contained**: the entire
system lives in one folder, and a new machine needs only Python 3.13 and an
internet connection.

### Current topics (as configured)

| Display name | Entity key | Search query | Geographic scope | Telegram channel |
|---|---|---|---|---|
| Property | `property-market` | `property market` | **Australia** | `AUProperty` |
| Wedding | `wedding` | `wedding planning` | **World** | *(none)* |
| Finance | `finance` | `personal finance` | **Australia** | `ASXAnalysis` |

---

## 2. High-level workflow

```
                       ┌────────────────────────────────────────────┐
                       │              collect_today.py              │
                       │  for each topic in TOPICS:                 │
                       │    1. Telegram collector (run_collector.py │
                       │       --source telegram --channel <ch>)    │
                       │    2. last30days engine via adapter        │
                       │       (reddit,hn,youtube,tiktok,instagram, │
                       │        linkedin,threads,pinterest,polymarket,x)│
                       │    3. write normalized JSONL records       │
                       │    4. record per-platform coverage         │
                       │    5. apply 36h filter                     │
                       └───────────────────┬────────────────────────┘
                                           │ data/social/normalized/<entity>.jsonl
                                           ▼
                       ┌────────────────────────────────────────────┐
                       │              daily_briefing.py             │
                       │  for each topic:                           │
                       │    1. run_pipeline.py --skip-collection    │
                       │       --no-report (briefings only)         │
                       │       (evidence → events → signals → digests)│
                       │    2. load records + per-entity digest     │
                       │    3. render Markdown briefing             │
                       └───────────────────┬────────────────────────┘
                                           │ Briefings/<Display>/<Display> - DD Mon YYYY.md
                                           ▼
                              (daily run: Briefings only;
                               full run writes reports/ +
                               obsidian/ + dashboard/)
```

The two entry points are separate so you can **collect** without rendering and
**render** without re-collecting (e.g. `daily_briefing.py --as-of <date>`).

---

## 3. Architecture and file map

### Root files

| Path | Purpose |
|---|---|
| `collect_today.py` | Daily collector. Defines `TOPICS`, builds the engine query (`<query> <location>`), runs Telegram + engine collection, records coverage, applies the 36h filter. |
| `daily_briefing.py` | Runs the pipeline per topic and renders the Markdown briefings. Also holds its own `TOPICS` list and the collection-health renderer. |
| `run_pipeline.py` | Offline analysis pipeline: normalized records → evidence → clusters → signals → events → digests → knowledge. Exports Obsidian vault + DOCX/MD reports + dashboard. With `--no-report` (used by `daily_briefing.py`) it skips vault/reports/dashboard and only updates `Briefings/` (see `run_pipeline.py:61`). |
| `scrapecreators_bridge.py` | Standalone bridge to the ScrapeCreators REST API (used for direct API testing / one-off pulls). |
| `setup.bat` | One-time setup: detects Python, builds `.config\last30days\.env`, installs `yt-dlp`, verifies the engine. |
| `daily_run.bat` | One-click daily flow: `setup.bat` → `collect_today.py` → `daily_briefing.py`, logging to `logs\`. |
| `install_task.bat` | Registers a daily 7:30 AM Windows scheduled task that runs `daily_run.bat`. |
| `README.md` | Short project summary. |
| `PROJECT_BRIEF.md` | This document. |

### Directories

| Path | Purpose |
|---|---|
| `scrapers/` | Adapters + schema enforcement for the project pipeline. |
| `scrapers/last30days_adapter.py` | Invokes the vendored engine with the right flags and normalizes output to the project's JSONL schema. |
| `scrapers/run_collector.py` | CLI used for Telegram collection (`--source telegram --channel <ch> --location <label>`). |
| `scrapers/telegram_adapter.py` | Keyless public-channel fetcher via `t.me/s/<channel>`; tags records with a `location` object. |
| `scrapers/coverage.py` | `update_coverage_entry()` — patches per-platform state into `logs/coverage.jsonl`. |
| `scrapers/platforms.py` | Platform definitions (which platforms need `SCRAPECREATORS_API_KEY`). |
| `.opencode/skills/last30days/` | Vendored "last30days" research engine (SKILL.md + `scripts/last30days.py` + `scripts/lib/`). |
| `.config/last30days/` | Project-local engine config. `.env` holds `SCRAPECREATORS_API_KEY`, `SETUP_COMPLETE`, `FROM_BROWSER`. **Never committed.** |
| `data/social/normalized/` | Per-entity JSONL records (`<entity>.jsonl`). Schema in `data/social/SCHEMA.md`. |
| `data/social/raw/` | Raw engine output. |
| `data/daily/` | Per-entity digests: `data/daily/<entity>-<date>.json`. |
| `data/evidence/`, `data/clusters/`, `data/signals/`, `data/events/`, `data/knowledge/`, `data/timeline/`, `data/research/` | Intermediate pipeline artifacts. |
| `Briefings/<Display>/` | Rendered daily briefings (`<Display> - DD Mon YYYY.md`). **Only folder updated by daily `daily_run.bat` / `daily_briefing.py`** (`run_pipeline.py:61` skips vault/reports when `--no-report`). |
| `logs/` | `coverage.jsonl` (per-run platform coverage) + `daily_run_DD-MM-YYYY.log`. |
| `obsidian/` | Per-run Obsidian vault (`obsidian/YYYY-MM-DD/run_<id>/`). Written only on full pipeline runs (without `--no-report`) or when Drive mirror is enabled. Ignored if you don't use Obsidian. |
| `reports/` | DOCX + MD reports per full run. Written only without `--no-report`. |
| `dashboard/` | HTML dashboard. Written only without `--no-report`. Ignored if not needed. |

---

## 4. Platforms, keys, and credentials

Per the engine's "Bring Your Own Key" model:

| Platform | Requirement | Cost |
|---|---|---|
| Reddit, Hacker News, Polymarket | none | free |
| YouTube | `yt-dlp` CLI (installed by `setup.bat`) | free |
| TikTok, Instagram, LinkedIn, Threads, Pinterest | `SCRAPECREATORS_API_KEY` | paid credits |
| X / Twitter | Firefox browser cookies (`FROM_BROWSER=firefox`) | free |
| Telegram | none (keyless public channels) | free |

- **X/Twitter** reads cookies from a local Firefox profile that must have been
  logged into x.com at least once (with "remember me"). The engine does not
  need Firefox running at collection time, only the cookies on disk.
- **Telegram** uses the public `t.me/s/<channel>` HTML page — no API key, no
  account, no login. Only public channels are collected.
- **Web** is not in the configured source list and no web-search key
  (`BRAVE_API_KEY` / `SERPER_API_KEY`) is set; it therefore never contributes
  records (the briefings explain this honestly).

---

## 5. Topics and geographic scoping

### Where topics are defined

Topics are defined in **two places**, and both must stay in sync:

1. `collect_today.py` — `TOPICS` (line ~60): includes `query`, `location`,
   `telegram_channels`, and `linkedin_companies`.
2. `daily_briefing.py` — `TOPICS` (line ~35): includes `query`, `location`
   (used for the `Geographic scope:` header).

### How location works

- `location` is appended to the engine query at collection time
  (`query = f"{query} {location}"`), so every platform in the run is scoped to
  that geography. Example: `property market Australia`.
- The same `location` is printed as `Geographic scope: <location>` in the
  briefing header.
- Property and Finance are scoped to **Australia**; Wedding is scoped to
  **World** (gather wedding trends around the world).

### How to add / change a topic

1. Edit `TOPICS` in `collect_today.py` (entity key, display name, query,
   location, telegram channel, optional linkedin companies).
2. Edit `TOPICS` in `daily_briefing.py` (entity key, display, query, location).
3. Run `python collect_today.py` then `python daily_briefing.py`.
   A `Briefings/<Display>/` folder is created automatically.

### Telegram channels (verified)

- **Property:** `AUProperty` — "Australia Property Market", ~59 subscribers,
  live content. Verified by fetching `t.me/s/AUProperty`.
- **Finance:** `ASXAnalysis` — "Australian Stock Analysis", ~126 subscribers,
  live content. Verified by fetching `t.me/s/ASXAnalysis`.
- **Wedding:** none. A thorough search found **no public, on-topic Australian
  wedding channel**; the briefing honestly explains this in the health table.

> To add/verify a channel, fetch `https://t.me/s/<handle>` in a browser: the
> page shows the channel's recent posts. Rejected candidates: `TheWeddingChannel`
> (dead, 2015-16 music downloads), `australian_stock_exchange` (2018-only
> content), `Australian_Property_Market` (empty).

---

## 6. Collection health reporting

Every collection run records, for each configured platform, one row into
`logs/coverage.jsonl` via `scrapers/coverage.py`:

- `platform`, `entity`
- `status` (`AVAILABLE`, `PARTIAL`, `NO_RESULTS`, `MISSING_CREDENTIALS`,
  `NOT_INSTALLED`, `AUTH_FAILED`, `RATE_LIMITED`, `UNREACHABLE`, `ERROR`, ...)
- `engine_state` (`ok`, `no-results`, `error`, ...)
- `records` (raw count before the 36h filter)
- `error` (engine error detail, if any)

`daily_briefing.py` turns this into the **Collection health** section of each
briefing: for every platform that contributed no content to the briefing it
prints *Why* + *What to do*. Priority of the explanation:

1. Platform not in the configured source list → "Not searched this run".
2. Engine searched and found items, but none within the last 36h window →
   "Searched and found N item(s), but none fall within the last 36h window."
3. Engine observed it but returned nothing → status/error-based explanation.

Known causes are auto-detected from error text:

| Error text | Suggested fix |
|---|---|
| `402` / "payment required" / "out of credits" | Top up credits at app.scrapecreators.com |
| `401` | API key invalid/expired — check `.env` |
| "no cookies" / "no browser" | Log into the platform once in Firefox |

---

## 7. The 36-hour window

- The corpus is **wiped per topic and re-filtered** to the last **36 hours**
  before the briefing is rendered, so each briefing covers only recent content.
- This is the intended design (36h keep-window), not a bug. Older items age out
  of the window between runs.
- `coverage.jsonl` `records` = raw count **before** the filter; the briefing
  health table uses that to explain "searched and found N, but none in window".
- The engine itself observes a 30-day window during collection; the project
  narrows it to 36h at briefing time.

---

## 8. ScrapeCreators API key — full resolution rules

The key can live in several places. `_load_api_key()` in `collect_today.py`
(and the equivalent in `scrapecreators_bridge.py`) scans all of them and uses
**whichever file was edited most recently** — so pasting a new key into any
known location is picked up automatically on the next run:

Resolution order:

1. Environment variable `SCRAPECREATORS_API_KEY` (always wins if set).
2. Among the following files, the one with the **newest file-modified time**:
   - `data/.scrapecreators_key` (legacy; raw key on one line)
   - `.config/last30days/.env` (project-local; `SCRAPECREATORS_API_KEY=...`)
   - `C:\Users\<you>\.config\last30days\.env` (global engine config)

The resolved key is passed to the engine as an environment variable, which the
engine treats as highest priority.

### Key hygiene rules

- One key per line, **no quotes**, **no trailing spaces**.
- Prefer the `SCRAPECREATORS_API_KEY=` prefixed form inside `.env` files; the
  legacy `data/.scrapecreators_key` file is raw (no prefix).
- Lines starting with `#` are treated as comments and skipped.
- `.config/`, `*.env`, `*.key`, and `data/.scrapecreators_key` are gitignored —
  keys are never committed.

### Interpreting HTTP errors from ScrapeCreators

| Code | Meaning | Action |
|---|---|---|
| **402** | Account has **0 credits** | Top up at app.scrapecreators.com. A new key does not fix this if the account is empty. |
| **401** | Key invalid/expired | Check the key is correct and current. |
| **404** | Not found (e.g. bad handle) | Usually a wrong handle, not a key problem. |

> Known history: the pipeline once sent a stale key while the user's new key
> sat in the global `~/.config/last30days/.env`. This was fixed by making the
> key loader scan every location and prefer the most recently edited one.

---

## 9. The daily outputs

### Briefings (`Briefings/<Display>/<Display> - DD Mon YYYY.md`) — daily output

Each briefing contains:

- **Title + generation time + observation window** (last 36h ending <day>).
- **Geographic scope** line (e.g. `Australia` / `World`).
- **Executive Summary** — from the pipeline digest.
- **By platform** — top posts by engagement, per platform that contributed.
- **Important events** — title, category, importance, confidence, snippet.
- **Signals** — signal type, strength, explanation.
- **Source coverage** — contributing platforms with counts, plus the honest
  disclaimer that unlisted platforms were not observed and must not be
  described as searched.
- **Collection health** — the Why/What-to-do table for silent platforms.

### Digests (`data/daily/<entity>-<date>.json`)

Per-entity digests keyed by event date. `daily_briefing.py::_load_digest`
scans `{entity}-*.json` and picks the latest date ≤ the briefing day, so a
multi-day window can reference the correct digest even if it is older than the
briefing day. (This fixed a bug where a shared per-date digest file caused one
topic's briefing to show another topic's content.)

### Other outputs (full runs only)

- **Reports** (`reports/Scraper_Intelligence_Report_<date>_run_<id>.docx` / `.md`) — written only when `run_pipeline.py` runs **without** `--no-report`.
- **Obsidian vault** (`obsidian/YYYY-MM-DD/run_<id>/`) — same condition; see §13. Daily `daily_briefing.py --no-report` skips it so `Briefings/` is the only folder that changes.
- **Dashboard** (`dashboard/index.html`) — same condition; ignored if not needed.
- To force reports + vault for a past date: `python run_pipeline.py <entity> --as-of YYYY-MM-DD --window-days 2 --skip-collection` (no `--no-report`).

> `output/` and `dashboard/` can be ignored — Briefings + reports are the deliverables.

---

## 10. Duplicating / sending to the next user

### Option A — git (recommended)

The repo is already set up so that secrets and generated artifacts are
gitignored. Uncommitted work should be committed first, then shared:

```
git add -A
git commit -m "handoff snapshot"
git push            # to a private remote
```

The next user clones and follows §11.

> Current handoff note: uncommitted changes exist in `collect_today.py`,
> `daily_briefing.py`, `run_pipeline.py`, `scrapecreators_bridge.py`,
> `scrapers/coverage.py`, `scrapers/run_collector.py`,
> `scrapers/telegram_adapter.py` — commit before sharing.

### Option B — zip the folder

1. Copy the whole folder.
2. **Remove the regenerated and secret parts** (they will be regenerated or are
   private):

   - `.config/` (contains `.env` with API keys)
   - `data/.scrapecreators_key`
   - `data/social/normalized/*.jsonl`, `data/social/raw/`
   - `data/daily/`, `data/evidence/`, `data/clusters/`, `data/signals/`,
     `data/events/`, `data/timeline/`, `data/knowledge/`, `data/research/`
   - `logs/`, `Briefings/`, `reports/`, `dashboard/`, `obsidian/`
   - `__pycache__/`, `*.pyc`

3. Keep everything else, especially:
   - all `.py` files, `scrapers/`
   - `.opencode/skills/last30days/` (the vendored engine)
   - `data/social/SCHEMA.md`
   - `setup.bat`, `daily_run.bat`, `install_task.bat`, `README.md`, `PROJECT_BRIEF.md`

4. Zip and send. The recipient follows §11.

> For the machine's own convenience, keep the `.env` and key files on the
> machine, but never send them.

---

## 11. Fresh install on a new Windows computer

### Prerequisites

- **Windows** (the batch files are Windows-specific).
- **Python 3.13** from https://www.python.org/downloads/ — during install,
  tick **"Add python.exe to PATH"**.

### Steps

1. **Install Python 3.13** (see above).
2. **Copy the project folder** anywhere, e.g.
   `C:\Users\<you>\Downloads\Scraper Intelligence`.
3. **Add the ScrapeCreators key** (if the new user has one). Either:
   - create `data\.scrapecreators_key` containing the key on one line, or
   - create `.config\last30days\.env` containing
     `SCRAPECREATORS_API_KEY=<key>`.
   The pipeline auto-detects whichever is newest.
4. **Run `setup.bat`** (double-click). It:
   - detects Python,
   - builds `.config\last30days\.env` from `data\.scrapecreators_key` if present
     (and writes `SETUP_COMPLETE=true`),
   - installs `yt-dlp` (needed for YouTube),
   - verifies the vendored engine exists at
     `.opencode\skills\last30days\scripts\last30days.py`.
5. **Optional — X/Twitter cookies:** install Firefox, log into x.com once with
   "remember me", close it, and ensure `.config\last30days\.env` contains
   `FROM_BROWSER=firefox`. Without this, X is silent (the briefing explains why).
6. **Test manually:**
   - `daily_run.bat` — full collect + render (a few minutes).
   - `python collect_today.py --dry-run` — plan only, no network.
7. **Schedule it (optional):** right-click `install_task.bat` → **Run as
   administrator**. Registers a daily 7:30 AM task that runs `daily_run.bat`.

### Verification

After a successful run:

- `logs\daily_run_<DD-MM-YYYY>.log` exists with "Done." at the end.
- `Briefings\<Display>\<Display> - <DD Mon YYYY>.md` files exist and contain a
  health table with no unexplained errors.
- ScrapeCreators platforms list an `AVAILABLE`/`PARTIAL` status (not
  `MISSING_CREDENTIALS` or `ERROR` 402).

---

## 12. Scheduling daily runs

`install_task.bat` registers a Windows scheduled task named
`ScraperIntelligence_DailyBriefing`:

- Runs **daily at 7:30 AM**.
- Executes `daily_run.bat` in the project folder.
- `StartWhenAvailable` is set, with a 4-hour execution-time limit (collections
  can be slow).

> **If the task appears not to run in background:** check `schtasks /query /tn ScraperIntelligence_DailyBriefing /v` — `Logon Mode: Interactive only` means it only runs while you are logged in. Fix with `schtasks /Change /tn ScraperIntelligence_DailyBriefing /RU <user> /RL HIGHEST` (enter password) or keep the machine logged in. `Last Result: -1073741510` means `daily_run.bat` / Python path was wrong — verify `C:\Users\axell\Downloads\Scraper Intelligence\daily_run.bat` and Python 3.13.

Manual operations:

```
python collect_today.py                           # all topics
python collect_today.py --topics Property,Wedding # subset
python daily_briefing.py                          # render all
python daily_briefing.py --topics Finance         # subset
python daily_briefing.py --as-of 2026-08-17       # backdate
```

---

## 13. Connecting to Obsidian.md

### What the pipeline can produce

Running `run_pipeline.py` **without** `--no-report` exports a **linked Obsidian
vault** per run:

```
python run_pipeline.py <entity> --as-of 2026-08-18 --window-days 2 --skip-collection
```

Daily `daily_briefing.py` uses `--no-report`, so it currently **does not** touch `obsidian/` — only `Briefings/` changes.

**Google Drive mirror (Option B, already wired in `run_pipeline.py:9`):** when Google Drive is installed (`~/My Drive` or `~/Google Drive` exists), every vault export is also mirrored to `My Drive/Scraper Intelligence - Obsidian/YYYY-MM-DD/run_<id>/`. Daily runs can also mirror by setting `MIRROR_ON_DAILY = True` in `run_pipeline.py:14` (currently `False` — daily runs only update `Briefings/`). Until Drive is installed `_drive_obsidian_base()` returns `None` and nothing breaks.

Output locations:

| Folder | Content |
|---|---|
| `Daily/` | One note per observed date: executive summary + events |
| `Events/` | One note per event: date, importance, confidence, topics, entities, evidence URLs |
| `Topics/`, `Trends/` | One note per topic/trend with related events |
| `Entities/` | One note per entity with related events |
| `Sources/` | All evidence URLs grouped by platform |
| `Research/` | Research index linking events and topics |
| `MOCs/` | Maps of content (indexes): `Index.md` + per-folder MOCs |

Notes use **wikilinks** (`[[...]]`) by default, so Obsidian can render a graph.

### Steps to use it in Obsidian

1. Install Obsidian (free) from https://obsidian.md.
2. **Open folder as vault** → pick the project folder (or just `obsidian`).
   Obsidian creates its own `.obsidian` config on first open and does not touch
   project files.
3. Navigate to `obsidian\<date>\run_<id>\` and open `MOCs\Index.md`.
4. Enable **Graph view** (left sidebar) to explore the linked events, topics,
   and entities.
5. Each run creates a new `run_<id>` folder, so old runs are preserved. Old run
   folders can be deleted anytime — briefings do not depend on them.

---

## 14. Troubleshooting guide

| Symptom | Cause | Fix |
|---|---|---|
| ScrapeCreators platforms show `ERROR` with **HTTP 402** | Account has 0 credits | Top up at app.scrapecreators.com |
| ScrapeCreators platforms show `MISSING_CREDENTIALS` | No key found by the loader | Add the key to `.config\last30days\.env` or `data\.scrapecreators_key` |
| ScrapeCreators platforms show `ERROR` with **401** | Key invalid/expired | Replace the key in the `.env` / key file (newest file wins) |
| X always empty, health says cookies missing/expired | No Firefox cookies | Log into x.com once in Firefox with "remember me"; keep `FROM_BROWSER=firefox` |
| YouTube silent | `yt-dlp` missing | Run `setup.bat` (installs it) |
| Briefing shows another topic's content | Stale shared digest file | Regenerate with `python daily_briefing.py` (per-entity digests are used) |
| Telegram channel empty | No channel configured (Wedding) | Add a verified channel to `telegram_channels` in `collect_today.py` |
| "Not searched this run" for web | `web` not in sources, no web key | Not a bug; web is intentionally not configured |
| Scheduled task not firing | Task not registered | Re-run `install_task.bat` as Administrator |
| `python` not recognized | Python not on PATH | Reinstall Python 3.13 ticking "Add to PATH", or run the full path `C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe` |

---

## 15. Data schema (records contract)

Normalized records live in `data/social/normalized/<entity>.jsonl` (one JSON
object per line). Full contract: `data/social/SCHEMA.md`. Highlights:

**Required fields:** `source` (collector engine name), `platform` (schema key),
`entity`, `entity_type` (`person|competitor|property|group|brand|topic`),
`post_id`, `author` (must have `name`), `timestamp` (ISO 8601 UTC `Z`),
`text` (verbatim, never edited), `url`, `engagement` (dict of counters),
`collected_at`, `run_id`.

**Engagement counters:** `likes`, `upvotes`, `comments`, `shares`, `views`,
`reposts`, `reactions`, `saves`, `stars`, `forks`, `points`, `issues`.

**Optional rich fields:** `query`, `title`, `author_handle`, `language`,
`media_type`, `source_status`, `raw_record_reference`
(`<raw_filename>#<source>@<index>`), `location` (`{place, latitude, longitude,
country, city}`).

**Invariants:**

1. Timestamps are always ISO 8601 UTC; date-only values normalize to midnight UTC.
2. Text is never altered — verbatim from source.
3. Missing values are omitted entirely (never `null`, never invented).
4. `run_id` and `collected_at` are preserved verbatim from run context.
5. Entity names are used as supplied (e.g. `property-market`, `wedding`, `finance`).
6. Telegram records are tagged with `location={"country": "Australia"}` (or the
   configured label) and always have an `author` with `name` and `url`.

---

*End of brief. For the short summary see `README.md`.*