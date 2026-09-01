"""Standalone ScrapeCreators -> normalized JSONL bridge.

Pulls posts from the ScrapeCreators REST API for one entity and writes them
into data/social/normalized/<entity>.jsonl in the project's schema, so the
existing run_pipeline.py can analyze them with no changes to project code.

API key resolution (first match wins):
  1. --key/--save-key argument
  2. environment variable SCRAPECREATORS_API_KEY
  3. file data/.scrapecreators_key (one line, no quotes)

Usage examples:
  python scrapecreators_bridge.py --platform reddit-search --entity property-market --entity-type topic --query "property market" --max 25
  python scrapecreators_bridge.py --platform instagram --entity my-brand --entity-type brand --handle adrianhorning
  python scrapecreators_bridge.py --platform x --entity austen --entity-type person --handle austen
  python scrapecreators_bridge.py --platform tiktok --entity weddings --entity-type topic --query "wedding trends 2026"
  python scrapecreators_bridge.py --platform youtube --entity finance --entity-type topic --query "interest rates"

Then run the pipeline as usual:
  python run_pipeline.py <entity> --as-of <date>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://api.scrapecreators.com"
KEY_HEADER = "x-api-key"
TIMEOUT = 60

PROJECT_ROOT = Path(__file__).resolve().parent
NORMALIZED_DIR = PROJECT_ROOT / "data" / "social" / "normalized"
DEFAULT_KEY_FILE = PROJECT_ROOT / "data" / ".scrapecreators_key"

ENTITY_TYPES = {"person", "competitor", "property", "group", "brand", "topic"}
ENGAGEMENT_KEYS = (
    "likes", "upvotes", "comments", "shares", "views", "reposts",
    "reactions", "saves", "stars", "forks", "points", "issues",
)

_TWITTER_DATE_RE = re.compile(
    r"^\w{3} \w{3} \d{2} \d{2}:\d{2}:\d{2} \+\d{4} \d{4}$"
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"run_{stamp}_{secrets.token_hex(4)}"


def _normalize_ts(value: Any) -> str | None:
    """Normalize unix, ISO 8601, or Twitter-format timestamps to ISO 8601."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if _TWITTER_DATE_RE.match(text):
        try:
            return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _engagement(**values: Any) -> dict[str, Any]:
    result = {key: None for key in ENGAGEMENT_KEYS}
    for key, value in values.items():
        if key in result and value is not None:
            try:
                result[key] = int(value)
            except (TypeError, ValueError):
                result[key] = None
    return result


def _media_item(*, type_: str, url: str | None = None, duration: int | None = None,
                mime: str | None = None) -> dict[str, Any]:
    return {
        "type": type_, "url": url, "mime": mime,
        "width": None, "height": None, "duration": duration, "title": None,
    }


def _load_api_key(args: argparse.Namespace) -> str:
    if getattr(args, "key", None):
        return args.key
    env = os.environ.get("SCRAPECREATORS_API_KEY", "").strip()
    if env:
        return env
    candidates: list[tuple[float, str]] = []
    for path in [
        args.key_file,
        args.key_file.parent.parent / ".config" / "last30days" / ".env",
        Path.home() / ".config" / "last30days" / ".env",
    ]:
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
    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]
    raise SystemExit(
        "ERROR: no API key found. Pass --key, set SCRAPECREATORS_API_KEY, or "
        f"create {DEFAULT_KEY_FILE} with your key on one line."
    )


def _request(path: str, params: dict[str, str], key: str) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={KEY_HEADER: key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 401:
            raise SystemExit(f"ERROR: ScrapeCreators rejected the API key (HTTP 401). {detail}")
        if exc.code == 402:
            raise SystemExit(f"ERROR: no credits remaining (HTTP 402). {detail}")
        raise SystemExit(f"ERROR: ScrapeCreators returned HTTP {exc.code}. {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"ERROR: could not reach ScrapeCreators: {exc.reason}")
    except TimeoutError:
        raise SystemExit("ERROR: ScrapeCreators request timed out.")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise SystemExit(f"ERROR: non-JSON response from ScrapeCreators: {body[:300]}")


# ---------------------------------------------------------------------------
# Per-platform endpoint + field mapping
# ---------------------------------------------------------------------------

_PLATFORMS: dict[str, dict[str, Any]] = {
    "reddit-search": {
        "path": "/v1/reddit/search",
        "target": "query",
        "payload": "posts",
        "eng": {"query": None, "sort": None, "timeframe": None},
    },
    "reddit-subreddit": {
        "path": "/v1/reddit/subreddit",
        "target": "subreddit",
        "payload": "posts",
        "eng": {"timeframe": None},
    },
    "instagram": {
        "path": "/v2/instagram/user/posts",
        "target": "handle",
        "payload": "items",
        "eng": {},
    },
    "x": {
        "path": "/v1/twitter/user-tweets",
        "target": "handle",
        "payload": "tweets",
        "eng": {},
    },
    "tiktok": {
        "path": "/v1/tiktok/search/keyword",
        "target": "query",
        "payload": "search_item_list",
        "eng": {"region": None},
    },
    "youtube": {
        "path": "/v1/youtube/search",
        "target": "query",
        "payload": "videos",
        "eng": {"region": None},
    },
}


def _build_record(platform: str, post: dict[str, Any], args: argparse.Namespace,
                  run_id: str) -> dict[str, Any]:
    base = {
        "source": "scrapecreators",
        "entity": args.entity,
        "entity_type": args.entity_type,
        "engagement": {},
        "media": [],
        "location": None,
        "collected_at": _now(),
        "run_id": run_id,
    }
    if platform == "reddit-search" or platform == "reddit-subreddit":
        base["platform"] = "reddit"
        base["post_id"] = post.get("id")
        base["author"] = {"name": str(post.get("author") or "unknown"),
                          "id": post.get("author_fullname"), "url": None, "verified": None}
        base["timestamp"] = _normalize_ts(post.get("created_utc") or post.get("created"))
        base["text"] = str(post.get("title") or "")
        base["url"] = post.get("url")
        base["title"] = str(post.get("title") or "").strip() or None
        base["engagement"] = _engagement(upvotes=post.get("ups"), comments=post.get("num_comments"))
        return base
    if platform == "instagram":
        base["platform"] = "instagram"
        base["post_id"] = post.get("id")
        user = post.get("user") or post.get("owner") or {}
        base["author"] = {"name": str(user.get("username") or user.get("full_name") or "unknown"),
                          "id": user.get("id"), "url": None,
                          "verified": user.get("is_verified")}
        base["timestamp"] = _normalize_ts(post.get("taken_at"))
        caption = post.get("caption") or {}
        base["text"] = str(caption.get("text") or "")
        base["url"] = post.get("url")
        base["author_handle"] = str(user.get("username") or "") or None
        base["engagement"] = _engagement(
            likes=post.get("like_count"), comments=post.get("comment_count"),
            views=post.get("play_count") or post.get("ig_play_count"))
        candidates = (post.get("image_versions2") or {}).get("candidates") or []
        thumb = post.get("display_uri") or (candidates[-1].get("url") if candidates else None)
        mtype = "image" if post.get("media_type") in (1, 8) else "video"
        if thumb:
            base["media"].append(_media_item(type_=mtype, url=thumb,
                                             duration=post.get("video_duration")))
        return base
    if platform == "x":
        base["platform"] = "x"
        legacy = post.get("legacy") or {}
        base["post_id"] = post.get("rest_id")
        base["author"] = {"name": args.handle or "unknown", "id": legacy.get("user_id_str"),
                          "url": None, "verified": None}
        base["timestamp"] = _normalize_ts(legacy.get("created_at"))
        base["text"] = str(legacy.get("full_text") or "")
        base["url"] = post.get("url")
        base["author_handle"] = args.handle or None
        views = (post.get("views") or {}).get("count") if isinstance(post.get("views"), dict) else None
        base["engagement"] = _engagement(
            likes=legacy.get("favorite_count"), comments=legacy.get("reply_count"),
            reposts=legacy.get("retweet_count"), saves=legacy.get("bookmark_count"),
            views=views)
        return base
    if platform == "tiktok":
        base["platform"] = "tiktok"
        author = post.get("author") or {}
        stats = post.get("statistics") or {}
        base["post_id"] = post.get("aweme_id")
        base["author"] = {"name": str(author.get("nickname") or author.get("unique_id") or "unknown"),
                          "id": author.get("uid"), "url": None,
                          "verified": author.get("is_star")}
        base["timestamp"] = _normalize_ts(post.get("create_time_utc") or post.get("create_time"))
        base["text"] = str(post.get("desc") or "")
        base["url"] = post.get("url")
        base["author_handle"] = author.get("unique_id") or None
        base["engagement"] = _engagement(
            views=stats.get("play_count"), likes=stats.get("digg_count"),
            comments=stats.get("comment_count"), shares=stats.get("share_count"),
            saves=stats.get("collect_count"))
        video = post.get("video") or {}
        play = (video.get("play_addr") or {}).get("url_list") or []
        cover = (video.get("cover") or {}).get("url_list") or []
        base["media"].append(_media_item(type_="video",
                                         url=(play[0] if play else (cover[0] if cover else None)),
                                         duration=video.get("duration"), mime="video/mp4"))
        return base
    if platform == "youtube":
        base["platform"] = "youtube"
        channel = post.get("channel") or {}
        base["post_id"] = post.get("id")
        base["author"] = {"name": str(channel.get("title") or "unknown"),
                          "id": channel.get("id"), "url": None, "verified": None}
        base["timestamp"] = _normalize_ts(post.get("publishedTime"))
        base["text"] = str(post.get("title") or "")
        base["url"] = post.get("url")
        base["title"] = str(post.get("title") or "").strip() or None
        base["author_handle"] = channel.get("handle") or None
        base["engagement"] = _engagement(views=post.get("viewCountInt"))
        if post.get("thumbnail"):
            base["media"].append(_media_item(type_="image", url=post.get("thumbnail")))
        return base
    raise SystemExit(f"ERROR: unsupported platform {platform!r}")


def _validate_record(record: dict[str, Any]) -> None:
    required = ("source", "platform", "entity", "entity_type", "post_id",
                "author", "timestamp", "text", "engagement", "collected_at")
    missing = [key for key in required if not record.get(key)]
    if missing:
        raise SystemExit(f"ERROR: record missing required fields {missing}: {json.dumps(record)[:300]}")
    if not record["author"].get("name"):
        raise SystemExit(f"ERROR: record missing author.name: {json.dumps(record)[:300]}")
    if record["platform"] not in ("reddit", "instagram", "x", "tiktok", "youtube"):
        raise SystemExit(f"ERROR: unknown platform {record['platform']!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ScrapeCreators -> normalized JSONL bridge")
    parser.add_argument("--platform", required=True, choices=sorted(_PLATFORMS))
    parser.add_argument("--entity", "-e", required=True)
    parser.add_argument("--entity-type", "-t", required=True, choices=sorted(ENTITY_TYPES))
    parser.add_argument("--query", "-q")
    parser.add_argument("--handle")
    parser.add_argument("--subreddit")
    parser.add_argument("--region", default="")
    parser.add_argument("--timeframe", default="", choices=["", "hour", "day", "week", "month", "year", "all"])
    parser.add_argument("--sort", default="", choices=["", "relevance", "top", "new"])
    parser.add_argument("--max", type=int, default=25)
    parser.add_argument("--key", default="")
    parser.add_argument("--save-key", default="", help="store the key in the key file, then run")
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)

    if args.save_key:
        args.key_file.parent.mkdir(parents=True, exist_ok=True)
        args.key_file.write_text(args.save_key.strip() + "\n", encoding="utf-8")
        print(f"Saved API key to {args.key_file}")

    key = _load_api_key(args)
    spec = _PLATFORMS[args.platform]

    target = getattr(args, spec["target"])
    if not target:
        raise SystemExit(f"ERROR: --{spec['target']} is required for platform {args.platform!r}")
    if args.platform.startswith("reddit") and not args.query and args.platform == "reddit-search":
        raise SystemExit("ERROR: --query is required for reddit-search")
    if args.platform == "reddit-search":
        target = args.query

    params: dict[str, str] = {spec["target"]: str(target)}
    for param, default in spec["eng"].items():
        value = getattr(args, param, "") or ""
        if value:
            params[param] = value

    print(f"Calling {spec['path']}?{urllib.parse.urlencode(params)}")
    payload = _request(spec["path"], params, key)
    if payload.get("success") is False:
        raise SystemExit(f"ERROR: ScrapeCreators reported failure: {json.dumps(payload)[:400]}")
    posts = payload.get(spec["payload"]) or []
    if not isinstance(posts, list):
        raise SystemExit(f"ERROR: unexpected payload shape for {args.platform!r}: {json.dumps(payload)[:300]}")
    if args.platform == "tiktok":
        posts = [p.get("aweme_info") or p for p in posts if isinstance(p, dict)]
    if args.max and len(posts) > args.max:
        posts = posts[: args.max]

    run_id = _new_run_id()
    records = [_build_record(args.platform, post, args, run_id) for post in posts]
    for record in records:
        _validate_record(record)

    if args.dry_run:
        print(f"DRY RUN OK: {len(records)} record(s) ready")
        if records:
            print(json.dumps(records[0], ensure_ascii=False))
        return 0

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = NORMALIZED_DIR / f"{args.entity}.jsonl"
    if args.reset and out_path.exists():
        out_path.unlink()
    with out_path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    print(f"OK: wrote {len(records)} record(s) to {out_path}")
    print(f"Next: python run_pipeline.py {args.entity} --as-of <date>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())