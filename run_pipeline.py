#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from analysis.daily_digest import build_daily_digests, digest_json_file, digest_to_markdown
from analysis.deduplication import cluster_evidence, clusters_jsonl
from analysis.entities import extract_entities
from analysis.evidence import build_evidence, dedupe, load_records, save_evidence
from analysis.events import events_jsonl, extract_events
from analysis.knowledge import classify_entities, classify_events, classify_topics, knowledge_jsonl
from analysis.obsidian import LINK_STYLES, export_obsidian_vault
from analysis.signals import score_signals, signals_jsonl
from analysis.timeline import build_timeline, timeline_json_file, timeline_to_markdown
from analysis.topics import extract_topics
from analysis.dashboard_html import write_dashboard_html
from analysis.word_report import DocxDocument, build_report_docx, write_markdown_report


def _today() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")
def _now() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _observation_window(*, as_of: str | None = None, window_days: int = 30) -> tuple[str, str]:
    end = datetime.strptime((as_of or _today())[:10], "%Y-%m-%d").date(); start = end - timedelta(days=max(0, window_days - 1)); return start.isoformat(), end.isoformat()


def _within_window(timestamp: str, start: str, end: str) -> bool: return bool(timestamp) and start <= str(timestamp)[:10] <= end


def _derive_run_id(records: list[dict], run_id: str | None = None) -> str:
    if run_id: return run_id
    values = sorted({str(r.get("run_id")) for r in records if r.get("run_id")})
    return values[0] if len(values) == 1 else "run_" + _now().replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")


def _source_coverage(records: list[dict]) -> str:
    counts: dict[str, int] = {}
    for record in records: counts[record.get("platform", "unknown")] = counts.get(record.get("platform", "unknown"), 0) + 1
    if not counts: return "No sources contributed evidence in this run."
    return "Contributing platforms: " + ", ".join(f"{name} ({count})" for name, count in sorted(counts.items())) + ". Platforms not listed were not observed in this corpus; they must not be described as searched."


def run(entity: str, *, workdir: Path | None = None, as_of: str | None = None, window_days: int = 30, link_style: str = "wikilink", run_id: str | None = None, no_report: bool = False) -> dict:
    workdir = workdir or ROOT; record_path = workdir / "data" / "social" / "normalized" / f"{entity}.jsonl"
    if not record_path.exists(): raise FileNotFoundError(f"no normalized records at {record_path}")
    start, end = _observation_window(as_of=as_of, window_days=window_days); records = load_records(record_path); label = _derive_run_id(records, run_id)
    all_evidence = dedupe(build_evidence(records, require_single_run=False)); items = [x for x in all_evidence if _within_window(x.timestamp, start, end)]; item_map = {x.evidence_id: x for x in items}
    save_evidence(items, workdir / "data" / "evidence" / f"{entity}.jsonl")
    entities = extract_entities(items); topics = extract_topics(items); clusters = cluster_evidence(items, entities=entities, topics=topics); signals = score_signals(clusters, items=item_map, as_of=as_of); events = extract_events(clusters, signals, items=item_map, as_of=as_of)
    clusters_jsonl(clusters, str(workdir / "data" / "clusters" / f"{entity}-clusters.jsonl")); signals_jsonl(signals, str(workdir / "data" / "signals" / f"{entity}-signals.jsonl")); events_jsonl(events, str(workdir / "data" / "events" / f"{entity}-events.jsonl"))
    digests = build_daily_digests(events, signals, items=item_map, title_for={s.cluster_id: s.explanation for s in signals}); daily_dir = workdir / "data" / "daily"; daily_dir.mkdir(parents=True, exist_ok=True)
    for digest in digests: digest_json_file(digest, daily_dir / f"{digest.date}.json"); (daily_dir / f"{digest.date}.md").write_text(digest_to_markdown(digest), encoding="utf-8")
    coverage = _source_coverage(records); timeline = build_timeline(events, signals, items=item_map, source_coverage=coverage, start_date=start, end_date=end); timeline_dir = workdir / "data" / "timeline"; timeline_json_file(timeline, timeline_dir / f"{start}-to-{end}.json"); (timeline_dir / f"{start}-to-{end}.md").write_text(timeline_to_markdown(timeline), encoding="utf-8")
    knowledge = classify_events(events, topic_status={t.name: t.status for t in timeline.topics}) + classify_topics(events, timeline.topics) + classify_entities(events); knowledge_jsonl(knowledge, str(workdir / "data" / "knowledge" / f"{entity}-knowledge.jsonl"))
    vault = workdir / "obsidian" / (as_of or _today())[:10] / label; vault_counts = export_obsidian_vault(vault, digests=digests, events=events, topics=timeline.topics, entities=timeline.entities, trends=timeline.topics, knowledge=knowledge, link_style=link_style)
    dashboard = write_dashboard_html(workdir / "dashboard" / "index.html", records_count=len(records), evidence_count=len(items), events=events, digests=digests, trends=timeline.topics, knowledge=knowledge, source_coverage=coverage, observation_window=f"{start}-to-{end}", generated_date=(as_of or _today())[:10])
    records_by_source: dict[str, int] = {}
    for record in records: records_by_source[record.get("platform", "unknown")] = records_by_source.get(record.get("platform", "unknown"), 0) + 1
    reports = workdir / "reports"; base = reports / f"Scraper_Intelligence_Report_{(as_of or _today())[:10]}_{label}"
    report_docx = str(base.with_suffix(".docx")); report_md = str(base.with_suffix(".md"))
    if not no_report:
        doc = DocxDocument(); build_report_docx(doc, start_date=start, end_date=end, generated_date=(as_of or _today())[:10], records_by_source=records_by_source, unavailable_sources=[], events=events, digests=digests, topics=timeline.topics, entities=timeline.entities, trends=timeline.topics, signals=signals, knowledge=knowledge, vault_counts=vault_counts, daily_events_by_date={}, evidence_items=items); doc.save(base.with_suffix(".docx")); write_markdown_report(base.with_suffix(".md"), start_date=start, end_date=end, generated_date=(as_of or _today())[:10], events=events, digests=digests, topics=timeline.topics, trends=timeline.topics, knowledge=knowledge, records_by_source=records_by_source, unavailable_sources=[])
    return {"entity": entity, "run_id": label, "records": len(records), "evidence": len(items), "clusters": len(clusters), "signals": len(signals), "events": len(events), "digests": len(digests), "knowledge": len(knowledge), "kept": sum(x.decision == "KEEP" for x in knowledge), "review": sum(x.decision == "REVIEW" for x in knowledge), "discard": sum(x.decision == "DISCARD" for x in knowledge), "vault": str(vault), "report_docx": report_docx, "report_md": report_md, "dashboard": str(dashboard), "timeline": f"{start}-to-{end}", "observation_window": f"{start}-to-{end}", "source_coverage": coverage, "vault_counts": vault_counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline Scraper Intelligence pipeline"); parser.add_argument("entity", nargs="?", default="ai-agent-market"); parser.add_argument("--workdir", type=Path, default=ROOT); parser.add_argument("--as-of"); parser.add_argument("--window-days", type=int, default=30); parser.add_argument("--link-style", choices=LINK_STYLES, default="wikilink"); parser.add_argument("--config", type=Path); parser.add_argument("--mock", action="store_true"); parser.add_argument("--skip-collection", action="store_true"); parser.add_argument("--run-id"); parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.config:
            from analysis.project_config import load_config, run_project
            for result in run_project(load_config(args.config), workdir=args.workdir, mock=args.mock, skip_collection=args.skip_collection): print(result)
        else: print(run(args.entity, workdir=args.workdir, as_of=args.as_of, window_days=args.window_days, link_style=args.link_style, run_id=args.run_id, no_report=args.no_report))
        return 0
    except Exception as exc:
        print(f"PIPELINE FAILED: {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
