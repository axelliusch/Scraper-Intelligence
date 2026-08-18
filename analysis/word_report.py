from __future__ import annotations

import html
import zipfile
from pathlib import Path
from typing import Any, Iterable


class _Document:
    def __init__(self) -> None: self.paragraphs: list[str] = []
    def add_heading(self, text: str, level: int = 1) -> None: self.paragraphs.append(text)
    def add_paragraph(self, text: str = "") -> None: self.paragraphs.append(text)
    def save(self, path: Path) -> None:
        body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{html.escape(p)}</w:t></w:r></w:p>" for p in self.paragraphs)
        document = f"<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>{body}<w:sectPr/></w:body></w:document>"
        content_types = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/></Types>"
        rels = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/></Relationships>"
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types); archive.writestr("_rels/.rels", rels); archive.writestr("word/document.xml", document)


DocxDocument = _Document


def build_report_docx(doc: _Document, *, start_date: str, end_date: str, generated_date: str, records_by_source: dict[str, int], unavailable_sources: list[str], events: Iterable[Any], digests: Iterable[Any], topics: Iterable[Any], entities: Iterable[Any], trends: Iterable[Any], signals: Iterable[Any], knowledge: Iterable[Any], vault_counts: dict[str, int], daily_events_by_date: dict[str, Any], evidence_items: Iterable[Any]) -> None:
    doc.add_heading("Scraper Intelligence Report"); doc.add_paragraph(f"Observation window: {start_date} to {end_date}. Generated: {generated_date}."); doc.add_paragraph("This report distinguishes reported observations from analysis. Event dates are earliest evidence report dates, not inferred occurrence dates.")
    doc.add_heading("Source coverage", 1); doc.add_paragraph("; ".join(f"{k}: {v}" for k, v in sorted(records_by_source.items())) or "No records contributed."); doc.add_paragraph("Unavailable or unqueried platforms: " + ", ".join(unavailable_sources) if unavailable_sources else "No unavailable platforms recorded.")
    doc.add_heading("Events", 1)
    for event in events: doc.add_paragraph(f"{event.event_date} | {event.importance} | {event.canonical_title} | {event.summary}")
    doc.add_heading("Trends", 1)
    for topic in topics: doc.add_paragraph(f"{topic.name}: {topic.status}. {topic.explanation}")


def write_markdown_report(path: Path, *, start_date: str, end_date: str, generated_date: str, events: Iterable[Any], digests: Iterable[Any], topics: Iterable[Any], trends: Iterable[Any], knowledge: Iterable[Any], records_by_source: dict[str, int], unavailable_sources: list[str]) -> None:
    lines = ["# Scraper Intelligence Report", "", f"Observation window: `{start_date}` to `{end_date}`", f"Generated: `{generated_date}`", "", "## Source coverage", ""]
    lines.extend(f"- `{key}`: {value} record(s)" for key, value in sorted(records_by_source.items())); lines.append("- Unavailable or unqueried: " + (", ".join(unavailable_sources) if unavailable_sources else "none")); lines += ["", "## Reported events", ""]
    lines.extend(f"- **{event.event_date} - {event.canonical_title}** ({event.importance}, confidence {event.confidence:.2f}) - {event.summary}" for event in events); lines += ["", "## Trends", ""]; lines.extend(f"- **{topic.name}**: {topic.status} - {topic.explanation}" for topic in topics); lines.append(""); path.parent.mkdir(parents=True, exist_ok=True); path.write_text("\n".join(lines), encoding="utf-8")
