from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from social_base import (
    AuditLog,
    CollectionError,
    SchemaError,
    SocialCollector,
    SocialRecord,
    Author,
    TargetValidator,
    TargetValidationError,
    utcnow,
)
from platforms import ENGINE_TO_PLATFORM, spec_for

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENGINE = PROJECT_ROOT / ".opencode" / "skills" / "last30days" / "scripts" / "last30days.py"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "research" / "raw"
DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "social" / "normalized"
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "last30days.jsonl"

ENGINE_TIMEOUT_SECONDS = 900

# Engine source name -> schema platform value (schema §5). Extends the
# capability map from platforms.py with the engine's generic/aggregate sources.
_SOURCE_TO_PLATFORM = dict(ENGINE_TO_PLATFORM)
_SOURCE_TO_PLATFORM.update(
    {
        "hn": "hackernews",
        "polymarket": "polymarket",
        "grounding": "web",
        "digg": "web",
        "arxiv": "web",
        "techmeme": "web",
        "amazon": "web",
        "trustpilot": "web",
        "stocktwits": "web",
        "xiaohongshu": "web",
        "perplexity": "web",
        "jobs": "web",
        "corpus": "corpus",
    }
)

# Non-"web" generic sources that should keep their own platform identity.
_GENERIC_PLATFORMS = frozenset({"web", "corpus", "polymarket"})


class Last30daysAdapter(SocialCollector):
    """Collector adapter around the vendored last30days research engine.

    Multi-platform by design: `source` is fixed to "last30days"; the schema
    `platform` is derived per result from the engine's source field.
    """

    source = "last30days"
    platform = "web"  # catch-all gate platform; per-record platform is derived

    def __init__(
        self,
        *,
        engine: str | Path = DEFAULT_ENGINE,
        raw_dir: str | Path = DEFAULT_RAW_DIR,
        normalized_dir: str | Path = DEFAULT_NORMALIZED_DIR,
        validator: TargetValidator | None = None,
        audit_log: AuditLog | None = None,
        timeout: int = ENGINE_TIMEOUT_SECONDS,
        logger_=None,
    ) -> None:
        self.engine = Path(engine)
        self.raw_dir = Path(raw_dir)
        self.normalized_dir = Path(normalized_dir)
        self.timeout = timeout
        #: Last engine run's observed outcomes: source name -> state ("ok",
        #: "no-results", "partial", ...). None until a collect() completes.
        self.last_source_status: dict[str, str] | None = None
        #: Last engine run's observation window in days (None if unspecified).
        self.last_window_days: int | None = None
        #: Last engine run's generated_at timestamp.
        self.last_generated_at: str | None = None
        super().__init__(validator=validator, audit_log=audit_log, logger_=logger_)

    # -- 2. target validation ----------------------------------------------

    def validate_target(self, target: dict[str, Any]) -> None:
        """Require an allowlisted entity; reject anything else.

        Targets carry: entity, entity_type, and an optional research query.
        The gate key is (platform="web", entity, entity_type) — the engine is
        multi-source so the entity is what is authorized, not a single site.
        """
        entity = self._target_entity(target)
        entity_type = self._target_entity_type(target)
        if not target.get("query"):
            raise TargetValidationError("target requires a research 'query'")

        if self.validator is not None and len(self.validator) > 0:
            self.validator.require("web", entity, entity_type)
        else:
            raise TargetValidationError("no allowlist configured; refusing research")

    # -- 3. collection -----------------------------------------------------

    def collect(self, target: dict[str, Any], run_id: str) -> list[SocialRecord]:
        """Invoke the engine (--emit=json --json-profile=agent, offline-safe)."""
        query = str(target["query"])
        raw_path = self._raw_output_path(query)
        search = self._search_tokens(target)
        cmd = self._build_command(
            query,
            raw_path,
            mock=bool(target.get("mock", False)),
            search=search,
        )

        # The rebuilt project has no vendored network engine. Mock mode is
        # therefore implemented locally and remains useful on a clean clone.
        if bool(target.get("mock")) and not self.engine.exists():
            profile = self._mock_profile(query, search)
            raw_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
            self.last_source_status = self._observed_status(profile)
            self.last_window_days = self._as_int(profile.get("window_days"))
            self.last_generated_at = str(profile.get("generated_at") or "")
            return self._to_records(profile, target, run_id, raw_path)

        self.log.info("invoking engine: %s", " ".join(map(str, cmd)))
        try:
            proc = subprocess.run(
                [str(x) for x in cmd],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise CollectionError(f"engine interpreter not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise CollectionError(
                f"engine timed out after {self.timeout}s"
            ) from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
            raise CollectionError(
                f"engine exited {proc.returncode}: {detail}"
            )

        profile = self._parse_json(raw_path, proc.stdout, query)
        self.last_source_status = self._observed_status(profile)
        self.last_window_days = self._as_int(profile.get("window_days"))
        self.last_generated_at = str(profile.get("generated_at") or "")
        return self._to_records(profile, target, run_id, raw_path)

    @staticmethod
    def _mock_profile(query: str, search: str | None) -> dict[str, Any]:
        """Small deterministic fixture used when no external engine is present."""
        sources = [x for x in (search or "reddit,hackernews,web").split(",") if x]
        results = []
        for index, source in enumerate(sources[:3]):
            results.append({
                "source": source,
                "candidate_id": f"mock-{index + 1}",
                "published_at": f"2026-08-{15 - index:02d}T12:00:00Z",
                "title": f"Public discussion of {query}",
                "summary": f"Public source observation about {query}; this is an offline fixture, not a live result.",
                "url": f"https://example.test/{source}/{index + 1}",
                "author": {"name": f"{source} public source", "handle": f"mock_{source}"},
                "engagement": {"comments": index + 1},
            })
        return {
            "query": query,
            "generated_at": "2026-08-17T00:00:00Z",
            "window_days": 30,
            "source_status": {source: {"state": "ok", "items_returned": 1} for source in sources[:3]},
            "results": results,
        }

    @staticmethod
    def _search_tokens(target: dict[str, Any]) -> str | None:
        """Resolve the engine --search token list from a target.

        The target may carry either engine source names (``search``, e.g.
        "reddit,x") or schema platforms (``platforms``, e.g. "reddit,x").
        ``platforms`` are translated to engine names via platforms.py.
        """
        explicit = str(target.get("search") or "").strip()
        if explicit:
            return explicit
        platforms = str(target.get("platforms") or "").strip()
        if not platforms:
            return None
        tokens: list[str] = []
        for token in (part.strip().lower() for part in platforms.split(",")):
            if not token:
                continue
            spec = spec_for(token)
            if spec is not None:
                tokens.extend(spec.engine_names)
            elif token in _SOURCE_TO_PLATFORM:
                tokens.append(token)
        return ",".join(dict.fromkeys(tokens)) if tokens else None

    @staticmethod
    def _observed_status(profile: dict[str, Any]) -> dict[str, str]:
        status: dict[str, str] = {}
        for name, outcome in (profile.get("source_status") or {}).items():
            if isinstance(outcome, dict):
                status[str(name)] = str(outcome.get("state") or "unknown")
            elif isinstance(outcome, str):
                status[str(name)] = outcome
        return status

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # -- engine invocation helpers -----------------------------------------

    def _build_command(
        self,
        query: str,
        raw_path: Path,
        *,
        mock: bool = False,
        quick: bool = False,
        search: str | None = None,
    ) -> list[str]:
        cmd: list[str] = [
            sys.executable,
            str(self.engine),
            query,
            "--emit=json",
            "--json-profile=agent",
            "--output",
            str(raw_path),
            "--no-browser-cookies",
        ]
        if mock:
            cmd.append("--mock")
        if quick:
            cmd.append("--quick")
        if search:
            cmd.append("--search")
            cmd.append(search)
        return cmd

    def _raw_output_path(self, query: str) -> Path:
        slug = _slugify(query)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        base = self.raw_dir / f"{slug}-raw.json"
        candidate, i = base, 1
        while candidate.exists():
            candidate = self.raw_dir / f"{slug}-raw-{i}.json"
            i += 1
        return candidate

    @staticmethod
    def _parse_json(raw_path: Path, stdout: str, query: str) -> dict[str, Any]:
        blob: Any = None
        if raw_path.exists():
            try:
                blob = json.loads(raw_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                blob = None
        if blob is None:
            try:
                blob = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise CollectionError(
                    f"engine returned no valid JSON for {query!r}"
                ) from exc
        if not isinstance(blob, dict):
            raise CollectionError("engine JSON profile is not a JSON object")
        return blob

    # -- normalization to schema -------------------------------------------

    def _to_records(
        self,
        profile: dict[str, Any],
        target: dict[str, Any],
        run_id: str,
        raw_path: str | Path | None = None,
    ) -> list[SocialRecord]:
        """Convert the agent JSON profile into schema-compliant records."""
        entity = str(target["entity"])
        entity_type = str(target["entity_type"])
        generated_at = str(profile.get("generated_at") or utcnow())
        query = str(profile.get("query") or target.get("query") or "").strip()

        source_status = profile.get("source_status") or {}
        records: list[SocialRecord] = []
        for index, result in enumerate(profile.get("results") or []):
            if not isinstance(result, dict):
                continue
            engine_source = str(result.get("source") or "web").strip().lower()
            platform = self._platform_for(engine_source)
            records.append(
                SocialRecord(
                    source=self.source,
                    platform=platform,
                    entity=entity,
                    entity_type=entity_type,
                    post_id=result.get("candidate_id"),
                    author=Author(
                        name=self._author_name(result, platform),
                        id=result.get("candidate_id"),
                        url=result.get("url") or None,
                        verified=None,
                    ),
                    timestamp=self._normalize_ts(result.get("published_at") or generated_at),
                    text=str(result.get("summary") or "").strip(),
                    title=str(result.get("title") or "").strip() or None,
                    url=result.get("url") or None,
                    engagement=self._map_engagement(result.get("engagement") or {}),
                    media=[],
                    location=None,
                    collected_at=utcnow(),
                    run_id=run_id,
                    query=query or None,
                    author_handle=self._author_handle(result, engine_source),
                    source_status=self._record_source_status(source_status, engine_source),
                    raw_record_reference=self._raw_record_reference(raw_path, engine_source, index),
                    language=None,
                    media_type=None,
                )
            )
        return records

    @staticmethod
    def _author_handle(result: dict[str, Any], source: str) -> str | None:
        author = result.get("author")
        if isinstance(author, dict):
            handle = author.get("handle") or author.get("username") or author.get("id")
            if isinstance(handle, str) and handle.strip():
                return handle.strip()
        return None

    @staticmethod
    def _record_source_status(source_status: dict[str, Any], source: str) -> str | None:
        outcome = source_status.get(source)
        if isinstance(outcome, dict):
            return str(outcome.get("state") or "unknown")
        if isinstance(outcome, str):
            return outcome
        return None

    @staticmethod
    def _raw_record_reference(
        raw_path: str | Path | None, source: str, index: int
    ) -> str | None:
        if raw_path is None:
            return None
        name = Path(raw_path).name
        return f"{name}#{source}@{index}"

    @staticmethod
    def _platform_for(source: str) -> str:
        source = source.strip().lower()
        if source in _SOURCE_TO_PLATFORM:
            return _SOURCE_TO_PLATFORM[source]
        if source in {
            "reddit", "x", "youtube", "tiktok", "instagram",
            "bluesky", "threads", "pinterest", "linkedin", "web", "corpus",
        }:
            return source
        return "web"

    @staticmethod
    def _author_name(result: dict[str, Any], platform: str) -> str:
        author = result.get("author")
        if isinstance(author, dict) and author.get("name"):
            return str(author["name"])
        if isinstance(author, str) and author.strip():
            return author.strip()
        return f"{platform} update"

    @staticmethod
    def _normalize_ts(value: str) -> str:
        ts = str(value or "").strip()
        if not ts:
            return utcnow()
        if ts.endswith("Z"):
            return ts
        if re.match(r"^\d{4}-\d{2}-\d{2}$", ts):  # date-only -> UTC midnight
            return f"{ts}T00:00:00Z"
        if "T" in ts:  # RFC 3339 with offset -> convert to UTC Z
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.astimezone().strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                return ts
        return ts

    @staticmethod
    def _map_engagement(raw: dict[str, Any]) -> dict[str, Any]:
        """Map engine-native engagement counters into schema keys."""
        mapping = {
            "likes": ("likes", "like_count", "favorites"),
            "upvotes": ("upvotes", "score", "karma"),
            "comments": ("comments", "num_comments", "replies", "comment_count"),
            "shares": ("shares",),
            "views": ("views", "views_count", "viewCount", "view_count"),
            "reposts": ("reposts", "repost_count", "retweet_count"),
            "reactions": ("reactions", "reaction_count"),
            "saves": ("saves", "save_count", "bookmarks", "bookmark_count"),
            "stars": ("stars", "stargazers", "stargazers_count"),
            "forks": ("forks", "forks_count"),
            "points": ("points", "hn_points"),
            "issues": ("issues", "open_issues", "issues_count"),
        }
        engagement: dict[str, Any] = {}
        for key, aliases in mapping.items():
            engagement[key] = _first_int(raw, aliases)
        return engagement

    # -- schema enforcement ------------------------------------------------

    def _validate_record(self, record: SocialRecord, run_id: str) -> None:
        """Enforce schema §7 required fields. Platform is per-record here."""
        if not record.source or not record.platform:
            raise SchemaError("record missing source/platform")
        if not record.entity or not record.entity_type:
            raise SchemaError("record missing entity/entity_type")
        if not record.author or not record.author.name:
            raise SchemaError("record missing author.name")
        if not record.timestamp:
            raise SchemaError("record missing timestamp")
        if record.source != self.source:
            raise SchemaError(
                f"record source {record.source!r} != collector source {self.source!r}"
            )

    def _write_records(self, records: list[SocialRecord], run_id: str) -> int:
        if not records:
            return 0
        entity = getattr(records[0], "entity", "") or "unknown"
        out_dir = self.normalized_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{_slugify(entity)}.jsonl"
        count = 0
        with out_path.open("a", encoding="utf-8") as handle:
            for record in records:
                self._validate_record(record, run_id)
                handle.write(record.to_json())
                handle.write("\n")
                count += 1
        return count


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "last30days"


def _first_int(raw: dict[str, Any], aliases: tuple[str, ...]) -> int | None:
    for alias in aliases:
        value = raw.get(alias)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30days_adapter",
        description="Run ST Trinity research through the last30days engine adapter.",
    )
    parser.add_argument("-e", "--entity", required=True, help="Entity key (e.g. acme-corp)")
    parser.add_argument(
        "-t",
        "--entity-type",
        required=True,
        choices=["person", "competitor", "property", "group", "brand", "topic"],
        help="Entity type from data/social/SCHEMA.md",
    )
    parser.add_argument("-q", "--query", required=True, help="Research query")
    parser.add_argument(
        "--engine",
        default=str(DEFAULT_ENGINE),
        help="Path to the last30days engine script",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Allowlist entry 'entity:entity_type' (repeatable)",
    )
    parser.add_argument(
        "--allow-all",
        action="store_true",
        help="Bypass the allowlist (test only)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run against the engine's bundled offline fixtures (no network)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Lower-latency engine retrieval profile",
    )
    parser.add_argument(
        "--search",
        default="",
        help="Engine source filter: comma-separated engine source names",
    )
    parser.add_argument(
        "--platforms",
        default="",
        help="Schema platform filter: comma-separated schema keys (e.g. reddit,x)",
    )
    parser.add_argument(
        "--platform",
        action="append",
        dest="platform_list",
        default=[],
        help="Schema platform key filter (repeatable, e.g. --platform instagram --platform x)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not invoke")
    parser.add_argument(
        "--log",
        default=str(DEFAULT_LOG_PATH),
        help="Audit/status log path",
    )
    parser.add_argument(
        "--coverage-log",
        default=str(Path("logs") / "coverage.jsonl"),
        help="Platform coverage log path (JSONL)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import argparse

    args = _build_parser().parse_args(argv)

    validator = TargetValidator()
    if args.allow:
        for entry in args.allow:
            entity, _, entity_type = entry.partition(":")
            validator.add("web", entity, entity_type)
    elif args.allow_all:
        validator.add("web", args.entity, args.entity_type)
    else:
        print("ERROR: --allow <entity>:<entity_type> (or --allow-all for tests) is required", file=sys.stderr)
        return 2

    adapter = Last30daysAdapter(
        engine=args.engine,
        validator=validator,
        audit_log=AuditLog(args.log),
    )

    target = {
        "entity": args.entity,
        "entity_type": args.entity_type,
        "query": args.query,
        "mock": args.mock,
    }
    if args.search:
        target["search"] = args.search
    if args.platform_list or args.platforms:
        platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
        platforms.extend(args.platform_list)
        target["platforms"] = ",".join(dict.fromkeys(platforms))

    if args.dry_run:
        try:
            adapter.validate_target(target)
        except TargetValidationError as exc:
            print(f"REJECTED: {exc}", file=sys.stderr)
            adapter._audit(target, "dry-run", "rejected", str(exc))
            return 3
        raw_path = adapter._raw_output_path(args.query)
        search = adapter._search_tokens(target)
        command = " ".join(map(str, adapter._build_command(
            args.query, raw_path, mock=args.mock, quick=args.quick, search=search
        )))
        print("DRY RUN OK")
        print(f"  entity      : {args.entity}")
        print(f"  entity_type : {args.entity_type}")
        print(f"  query       : {args.query}")
        if search:
            print(f"  search      : {search}")
        print(f"  raw output  : {raw_path}")
        print(f"  normalized  : {adapter.normalized_dir / (_slugify(args.entity) + '.jsonl')}")
        print(f"  command     : {command}")
        adapter._audit(target, "dry-run", "ok", "dry-run planned; engine not invoked")
        return 0

    try:
        records = adapter.run(target)
    except TargetValidationError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 3
    except CollectionError as exc:
        print(f"COLLECTION FAILED: {exc}", file=sys.stderr)
        return 4
    except SchemaError as exc:
        print(f"SCHEMA FAILED: {exc}", file=sys.stderr)
        return 5

    print(f"OK: collected {len(records)} records")
    try:
        from coverage import build_coverage_report, coverage_to_markdown, write_coverage_report

        engine_status = adapter.last_source_status or {}
        report = build_coverage_report(
            args.entity,
            engine_status=engine_status,
            window_days=adapter.last_window_days,
            normalized_dir=adapter.normalized_dir,
        )
        write_coverage_report(report, args.coverage_log)
        print()
        print(coverage_to_markdown(report))
    except Exception as exc:
        print(f"COVERAGE REPORT FAILED: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
