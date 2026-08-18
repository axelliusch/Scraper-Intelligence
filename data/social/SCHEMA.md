# data/social/SCHEMA.md — Normalized JSONL Record Contract

## Schema Philosophy

- **Schema-first**: one normalized record contract governs all data flow.
- **Deterministic**: same input → identical output; no fields invented or altered.
- **Provenance-preserving**: every claim traces back to original evidence/URLs;
  raw output is never edited.
- **Offline-safe**: full analysis runs on already-collected data; no network required.
- **No credentials**: only public, authorized content is recorded; never stores
  API keys, cookies, tokens, or private data.

---

## §2 Platform Table (12 entries)

| Platform Key | Type | Notes |
|---|---|---|
| `reddit` | social-media / forum | |
| `hackernews` | forum | |
| `github` | forum | `points`/`stars`/`forks`/`issues` engagement |
| `youtube` | social-media | `views` engagement; requires `yt-dlp` CLI for full |
| `x` | social-media | requires `SCRAPECREATORS_API_KEY` or similar |
| `tiktok` | social-media | requires `SCRAPECREATORS_API_KEY` |
| `instagram` | social-media | requires `SCRAPECREATORS_API_KEY` |
| `linkedin` | social-media | requires `SCRAPECREATORS_API_KEY` |
| `threads` | social-media | requires `SCRAPECREATORS_API_KEY` |
| `pinterest` | social-media | requires `SCRAPECREATORS_API_KEY` |
| `web` | web / general | catch-all; engine `grounding` source |
| `telegram` | messenger | public channels only; keyless |

---

## §3 Record Contract (JSONL)

Every record is a JSON object on a single line (`JSONL`). The contract
defines **required** fields (always present) and **optional** fields (emitted
only when set; otherwise absent — never `null`, never invented).

### Required Fields (schema §7/§8)

| Field | Type | Description |
|---|---|---|
| `source` | `str` | Collector engine name (`last30days`, `rss`, `telegram`). |
| `platform` | `str` | Schema platform key (from the 12-platform table). |
| `entity` | `str` | The research entity/topic being investigated (e.g. a company name,
  model name, policy term, or user‑defined topic). |
| `entity_type` | `str` | One of: `person`, `competitor`, `property`, `group`, `brand`, `topic`. |
| `post_id` | `str \| null` | Platform‑specific identifier (post ID, tweet ID, issue number, etc.). |
| `author` | `object` | Must contain at minimum `name` (`str`). May contain `id`,
  `url`, `verified` (`bool \| null`). |
| `timestamp` | `str` | ISO 8601 UTC with `Z` suffix; normalized to UTC at ingestion. |
| `text` | `str` | Verbatim source text; never edited or dressed up. |
| `url` | `str \| null` | Direct link to the original source post/page. |
| `engagement` | `dict` | Engagement counters; keys from the schema set:
  `likes`, `upvotes`, `comments`, `shares`, `views`, `reposts`,
  `reactions`, `saves`, `stars`, `forks`, `points`, `issues`. Unknown
  counters are `null`, never fabricated. Default `{}` when unknown. |
| `collected_at` | `str` | ISO 8601 UTC `Z`; when the record was ingested into the pipeline. |
| `run_id` | `str` | Identifier for this pipeline run. Same input → identical `run_id`. |

### Optional Rich Fields (schema §3/§8)

| Field | Type | Description |
|---|---|---|
| `query` | `str \| null` | The research query that produced this record. `null` when not |
| | | applicable (e.g. RSS feed items). |
| `title` | `str \| null` | Title of the source post/article; preserved verbatim. |
| `author_handle` | `str \| null` | Handle/username of the author; drop emails (schema forbids storing |
| | | emails under `author`). |
| `language` | `str \| null` | Language code (e.g. `"en"`), when detectable. |
| `media_type` | `str \| null` | Primary media type: `image`, `video`, `audio`, `link`, or `null`. |
| `source_status` | `str \| null` | Engine‑observed state for this record's source (e.g. `"ok"`,
  `"no-results"`, `"partial"`). |
| `raw_record_reference` | `str \| null` | Points back into the immutable raw output file for full audit lineage. |
| | | Format: `<raw_filename>#<source>@<index>` (e.g.
  `acme-funding-raw.json#instagram@0`). |

### `author` Sub‑object

| Sub‑field | Type | Description |
|---|---|---|
| `name` | `str` | **Required**. Display name of the author. Emails are **forbidden** — |
| | | strip them before storage (see `safe_author_name()`). |
| `id` | `str \| null` | Platform‑specific author ID. |
| `url` | `str \| null` | Profile or link URL. |
| `verified` | `bool \| null` | Whether the platform verifies this identity. |

### `engagement` Sub‑object

Every engagement counter key is stored under its canonical name. When a
specific engine provides a counter under a different key, it is mapped via
the adapter's `_map_engagement()` logic. Unknown counters are **not** added;
they remain `null` (absent from the dict is also acceptable, but the canonical
keys are always present for compatibility).

| Key | Engine source typical values |
|---|---|
| `likes` | Generic / Facebook‑style |
| `upvotes` | Hacker News, Reddit (`score` maps here) |
| `comments` | Generic |
| `shares` | Generic / Twitter retweets |
| `views` | YouTube, web pages |
| `reposts` | Twitter (`retweet_count`), Mastodon |
| `reactions` | Facebook, generic |
| `saves` | TikTok, Instagram (save/bookmark) |
| `stars` | GitHub (`stargazers_count`) |
| `forks` | GitHub |
| `points` | Hacker News (`points`) |
| `issues` | GitHub (`open_issues_count`) |

### `media` Array

Each entry is an object representing one media element found in the source.

| Sub‑field | Type | Description |
|---|---|---|
| `type` | `str` | One of: `image`, `video`, `audio`, `link` (schema `MEDIA_TYPES`). |
| `url` | `str \| null` | Direct URL to the media file or linked page. |
| `mime` | `str \| null` | MIME type (e.g. `image/jpeg`, `video/mp4`, `audio/mpeg`). |
| `width` | `int \| null` | Pixel width (images only). |
| `height` | `int \| null` | Pixel height (images only). |
| `duration` | `int \| null` | Duration in seconds (video/audio only). |
| `title` | `str \| null` | Title or caption (when available). |

### Location (optional, rarely used)

| Field | Type | Description |
|---|---|---|
| `location` | `dict \| null` | `{place, latitude, longitude, country, city}` when the source |
| | | explicitly provides geolocation. Default `null`. |

---

## §4 Normalization Invariants

1. **Timestamps** are always ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`). Date-only
   values (`YYYY-MM-DD`) are normalized to midnight UTC (`YYYY-MM-DDTH00:00:00Z`).
2. **Text** is never altered — verbatim from the source. If the source text
   is empty, the field is `""` (never `null`).
3. **Missing values** are omitted from the JSON object entirely (they are
   not `null` and not `""` — they simply aren't present). This is the
   "never invent" rule.
4. **`run_id`** and **`collected_at`** are preserved verbatim from the run
   context. They are **not** regenerated or "smart‑normalized".
5. **`raw_record_reference`** points to the immutable raw output file:
   `<file>#<source>@<index>` where `index` is the 0‑based position of the
   result in the engine's output.
6. **Entity names** use the user-supplied entity key as-is (e.g.
   `property-market`, `wedding-trends`, `finance`). The system never
   modifies or normalizes entity names.

---

## §5 Example Record (JSONL line)

```json
{"source":"last30days","platform":"reddit","entity":"ai-agent-market","entity_type":"topic","post_id":"t3_abc123","author":{"name":"uTechReviewer"},"timestamp":"2026-08-15T14:32:10Z","text":"The new AI agent framework looks promising for automating research tasks.","url":"https://reddit.com/r/artificialintelligence/comments/abc123/","engagement":{"likes":42,"comments":15,"upvotes":50},"collected_at":"2026-08-17T09:12:45Z","run_id":"run_20260817_abc123"}
```

```json
{"source":"rss","platform":"web","entity":"property-market","entity_type":"topic","post_id":"https://example.test/news/rent-growth-july","author":{"name":"Market Desk"},"timestamp":"2026-08-14T00:00:00Z","text":"Rent growth in the greater metropolitan area slowed to 12% year‑over‑year in July.","title":"July rent growth slows","url":"https://example.test/news/rent-growth-july","engagement:{},\"collected_at":"2026-08-17T09:12:45Z","run_id":"run_20260817_abc123"}
```

```json
{"source":"telegram","platform":"telegram","entity":"sydney-property","entity_type":"topic","post_id":"341","author":{"name":"ST Trinity Property Channel","id":"sttrinityintel","url":"https://t.me/sttrinityintel"},"timestamp":"2026-08-15T06:20:00Z","text":"Northern stretch of the coastline seeing increased development interest.","url":"https://t.me/sttrinityintel/341","media":[],"collected_at":"2026-08-17T09:12:45Z","run_id":"run_20260817_abc123"}
```