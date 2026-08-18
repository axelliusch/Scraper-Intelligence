from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Mapping, Sequence


def build_dashboard_html(*, records_count: int, evidence_count: int, events: Sequence[Any], digests: Sequence[Any], trends: Sequence[Any], knowledge: Sequence[Any], source_coverage: str, observation_window: str, generated_date: str) -> str:
    esc = lambda value: html.escape("" if value is None else str(value))
    rows = "".join(f"<tr><td>{esc(e.event_date)}</td><td>{esc(e.importance)}</td><td>{esc(e.confidence)}</td><td>{esc(e.canonical_title)}</td><td>{esc(', '.join(e.platforms))}</td></tr>" for e in sorted(events, key=lambda x: (x.event_date, x.event_id)))
    trend_rows = "".join(f"<tr><td>{esc(t.name)}</td><td>{esc(t.status)}</td><td>{t.event_count}</td></tr>" for t in sorted(trends, key=lambda x: x.name))
    decisions = {key: sorted({x.title for x in knowledge if x.decision == key}) for key in ("KEEP", "REVIEW", "DISCARD")}
    blocks = "".join(f"<section><h3>{key}</h3><ul>{''.join(f'<li>{esc(v)}</li>' for v in values) or '<li>None</li>'}</ul></section>" for key, values in decisions.items())
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scraper Intelligence</title><style>body{{font:15px system-ui;margin:0;background:#10131a;color:#e8edf5}}main{{max-width:1100px;margin:auto;padding:24px}}section{{background:#191e27;border:1px solid #303846;border-radius:10px;padding:18px;margin:16px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #303846;text-align:left}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{padding:14px;background:#202733;border-radius:8px}}a{{color:#8ab4ff}}</style></head><body><main><h1>Scraper Intelligence</h1><p>Observation window: {esc(observation_window)}. Generated: {esc(generated_date)}.</p><p>{esc(source_coverage)}</p><div class="cards"><div class="card">Records: {records_count}</div><div class="card">Evidence: {evidence_count}</div><div class="card">Events: {len(events)}</div><div class="card">Digests: {len(digests)}</div></div><section><h2>Events</h2><table><tr><th>Date</th><th>Importance</th><th>Confidence</th><th>Reported item</th><th>Platforms</th></tr>{rows}</table></section><section><h2>Trends</h2><table><tr><th>Topic</th><th>Status</th><th>Events</th></tr>{trend_rows}</table></section><section><h2>Knowledge decisions</h2>{blocks}</section><section><h2>Offline source trail</h2><p>All event URLs and source text remain available in the intermediate evidence and event artifacts.</p></section></main></body></html>'''


def write_dashboard_html(path: Path, **kwargs: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(build_dashboard_html(**kwargs), encoding="utf-8"); return path
