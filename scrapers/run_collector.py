from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from .registry import register_default_collectors
    from .social_base import AuditLog, CollectionError, SchemaError, TargetValidationError
except ImportError:
    from registry import register_default_collectors
    from social_base import AuditLog, CollectionError, SchemaError, TargetValidationError


def main(argv: list[str] | None = None) -> int:
    registry = register_default_collectors()
    parser = argparse.ArgumentParser(description="Collect one explicitly authorized public target")
    parser.add_argument("--source", required=True, choices=registry.sources())
    parser.add_argument("--entity", "-e", required=True)
    parser.add_argument("--entity-type", "-t", required=True, choices=["person", "competitor", "property", "group", "brand", "topic"])
    parser.add_argument("--query", "-q")
    parser.add_argument("--allow", action="append", default=[])
    parser.add_argument("--allow-all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--search", default="")
    parser.add_argument("--platforms", default="")
    parser.add_argument("--platform", action="append", dest="platform_list", default=[])
    parser.add_argument("--feed-url", action="append", default=[])
    parser.add_argument("--channel", default="")
    parser.add_argument("--location", default="", help="Country/place label recorded on collected records")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--log", default="logs/social-audit.jsonl")
    args = parser.parse_args(argv)
    collector = registry.create(args.source, audit_log=AuditLog(args.log))
    if not args.allow and not args.allow_all:
        print("ERROR: --allow entity:type or --allow-all is required", file=sys.stderr)
        return 2
    gate = getattr(collector, "platform", "web")
    for entry in args.allow or [f"{args.entity}:{args.entity_type}"]:
        entity, _, entity_type = entry.partition(":")
        collector.validator.add(gate, entity, entity_type)
    target = {"entity": args.entity, "entity_type": args.entity_type, "query": args.query, "mock": args.mock, "quick": args.quick}
    if args.search: target["search"] = args.search
    platforms = [x.strip() for x in args.platforms.split(",") if x.strip()] + args.platform_list
    if platforms: target["platforms"] = ",".join(dict.fromkeys(platforms))
    if args.feed_url: target["feeds"] = args.feed_url
    if args.channel: target["channel"] = args.channel
    if args.location: target["location"] = args.location
    try:
        collector.validate_target(target)
        if args.dry_run:
            print("DRY RUN OK"); print(f"source: {args.source}"); print(f"entity: {args.entity}"); print(f"query: {args.query or ''}"); return 0
        if args.reset:
            path = Path("data/social/normalized") / f"{args.entity}.jsonl"
            if path.exists(): path.unlink()
        records = collector.run(target)
        print(f"OK: collected {len(records)} records")
        return 0
    except TargetValidationError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr); return 3
    except CollectionError as exc:
        print(f"COLLECTION FAILED: {exc}", file=sys.stderr); return 4
    except SchemaError as exc:
        print(f"SCHEMA FAILED: {exc}", file=sys.stderr); return 5


if __name__ == "__main__": raise SystemExit(main())
