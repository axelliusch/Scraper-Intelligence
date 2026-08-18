from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from platforms import (
    AVAILABLE,
    NOT_CONFIGURED,
    NOT_INSTALLED,
    MISSING_CREDENTIALS,
    NO_RESULTS,
    PARTIAL,
    PLATFORM_SPECS,
    STATUSES,
    classify_observed,
    spec_for,
)

logger = logging.getLogger("st_trinity.coverage")

DEFAULT_COVERAGE_PATH = Path("logs") / "coverage.jsonl"


@dataclass
class CoverageRow:
    """One platform's status in a coverage report."""

    platform: str
    name: str
    status: str
    engine_source: str | None = None  # engine source name that produced results
    engine_state: str | None = None  # raw observed engine outcome state
    records: int = 0  # normalized records collected for this platform
    evidence: int = 0  # analysis-layer evidence items from those records
    note: str = ""


@dataclass
class CoverageReport:
    """Snapshot of platform availability for one entity/run."""

    entity: str
    generated_at: str
    window_days: int | None = None
    rows: list[CoverageRow] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "generated_at": self.generated_at,
            "window_days": self.window_days,
            "rows": [asdict(r) for r in self.rows],
            "summary": self.summary(),
        }


def _count_evidence(normalized_dir: Path, entity: str, platform: str) -> tuple[int, int]:
    """Return (records, evidence) counts for one platform in one entity corpus.

    Records are read from the normalized JSONL; evidence mirrors the analysis
    layer's evidence index path (data/evidence/<entity>.jsonl).
    """
    records = 0
    records_path = normalized_dir / f"{entity}.jsonl"
    if records_path.exists():
        try:
            for line in records_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                blob = json.loads(line)
                if blob.get("platform") == platform:
                    records += 1
        except json.JSONDecodeError as exc:
            logger.warning("skipping malformed line in %s: %s", records_path, exc)

    evidence = 0
    # Evidence index lives at data/evidence/<entity>.jsonl (analysis layer),
    # i.e. at the *parent* of the normalized dir (data/social -> data).
    evidence_dir = normalized_dir.parent.parent / "evidence"
    evidence_path = evidence_dir / f"{entity}.jsonl"
    if evidence_path.exists():
        try:
            for line in evidence_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                blob = json.loads(line)
                if blob.get("platform") == platform:
                    evidence += 1
        except json.JSONDecodeError as exc:
            logger.warning("skipping malformed line in %s: %s", evidence_path, exc)
    return records, evidence


def build_coverage_report(
    entity: str,
    *,
    engine_status: Mapping[str, str] | None = None,
    window_days: int | None = None,
    normalized_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CoverageReport:
    """Build a coverage report for one entity.

    engine_status maps engine source names -> observed outcome states (the
    adapter's ``last_source_status``). Platforms the run did not observe fall
    back to static classification from the local environment.
    """
    normalized_dir = Path(normalized_dir) if normalized_dir else Path("data") / "social" / "normalized"
    engine_status = dict(engine_status or {})

    # Map observed statuses by schema platform, keeping the first state seen.
    observed_by_platform: dict[str, str] = {}
    engine_by_platform: dict[str, str] = {}
    for source, state in engine_status.items():
        spec = spec_for(source)
        platform = spec.key if spec else source
        observed_by_platform.setdefault(platform, state)
        engine_by_platform.setdefault(platform, source)

    rows: list[CoverageRow] = []
    for spec in PLATFORM_SPECS:
        state = observed_by_platform.get(spec.key)
        status = classify_observed(spec, state, env=env)
        records, evidence = _count_evidence(normalized_dir, entity, spec.key)
        if state is None and records > 0:
            status = AVAILABLE  # we demonstrably collected from this platform
        note = ""
        if status in (PARTIAL, MISSING_CREDENTIALS, NOT_INSTALLED, NOT_CONFIGURED):
            if not spec.keyless and not spec.env:
                note = "no route" if status == NOT_CONFIGURED else ""
            elif status == NOT_INSTALLED:
                note = f"install {spec.cli}" if spec.cli else "engine CLI missing"
            elif status == MISSING_CREDENTIALS:
                note = "credential required"
            elif status == PARTIAL and not spec.env:
                note = "best-effort (anonymous caps)"
        rows.append(
            CoverageRow(
                platform=spec.key,
                name=spec.name,
                status=status,
                engine_source=engine_by_platform.get(spec.key),
                engine_state=state,
                records=records,
                evidence=evidence,
                note=note,
            )
        )

    rows.sort(key=lambda r: (r.status != AVAILABLE, r.platform))
    return CoverageReport(
        entity=entity,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_days=window_days,
        rows=rows,
    )


def coverage_to_markdown(report: CoverageReport) -> str:
    """Render a coverage report as a markdown table."""
    lines = [
        f"# Platform Coverage — {report.entity}",
        "",
        f"- Generated: {report.generated_at}",
        f"- Observation window: {report.window_days or 'n/a'} days",
        "",
        "| Platform | Status | Records | Evidence | Engine source | Note |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in report.rows:
        source = row.engine_source or ""
        lines.append(
            f"| {row.name} (`{row.platform}`) | {row.status} | "
            f"{row.records} | {row.evidence} | {source} | {row.note} |"
        )
    summary = report.summary()
    lines += [
        "",
        "**Summary:** " + ", ".join(f"{k}: {summary.get(k, 0)}" for k in STATUSES),
    ]
    return "\n".join(lines)


def write_coverage_report(
    report: CoverageReport,
    path: str | Path = DEFAULT_COVERAGE_PATH,
) -> Path:
    """Append a coverage report line to logs/coverage.jsonl (UTF-8)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report.to_dict(), ensure_ascii=False))
        handle.write("\n")
    return path