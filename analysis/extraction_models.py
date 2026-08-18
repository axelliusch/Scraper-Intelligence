from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

STOPWORDS = frozenset("a an the and or but if for in on at to of from with by is are was were be been have has had this that these those it its as how what why who which about into over under new now more most very just use used using".split())
ENTITY_TYPES = ("organization", "product", "person", "technology", "location", "other")
EXTRACTION_METHODS = ("explicit", "pattern", "heuristic")


def normalize_text(text: str | None) -> str:
    value = unicodedata.normalize("NFC", text or "")
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", value).strip().lower()


def normalize_phrase(text: str | None) -> str:
    return " ".join(re.sub(r"[^\w.-]+", " ", normalize_text(text)).split())


def punctuation_collapsed(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(text)).strip()


def contains_term(text: str, term: str) -> bool:
    surface = punctuation_collapsed(text)
    needle = punctuation_collapsed(term)
    return bool(needle and re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", surface))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_phrase(name)).strip("-") or "item"


def deterministic_id(prefix: str, *parts: str) -> str:
    raw = "|".join((prefix, *parts))
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def best_method(methods: set[str]) -> str:
    return min(methods, key=EXTRACTION_METHODS.index)


def confidence(method: str, support: int) -> float:
    base = {"explicit": .85, "pattern": .70, "heuristic": .55}[method]
    cap = {"explicit": .95, "pattern": .90, "heuristic": .85}[method]
    return round(min(cap, base + max(0, support - 1) * .04), 3)


@dataclass
class EntityExtraction:
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    source_evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    extraction_method: str = "explicit"
    rationale: str = ""
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass
class TopicExtraction:
    topic_id: str
    canonical_name: str
    keywords: list[str] = field(default_factory=list)
    source_evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    extraction_method: str = "explicit"
    rationale: str = ""
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class ExtractionValidationError(ValueError): pass


def validate_entity(value: EntityExtraction) -> None:
    if not value.entity_id or not value.canonical_name or value.entity_type not in ENTITY_TYPES:
        raise ExtractionValidationError("invalid entity extraction")
    if not value.source_evidence_ids or value.extraction_method not in EXTRACTION_METHODS:
        raise ExtractionValidationError("entity extraction is not evidence-gated")
    if not 0 <= value.confidence <= 1: raise ExtractionValidationError("entity confidence out of range")


def validate_topic(value: TopicExtraction) -> None:
    if not value.topic_id or not value.canonical_name or not value.keywords or not value.source_evidence_ids:
        raise ExtractionValidationError("invalid topic extraction")
    if value.extraction_method not in EXTRACTION_METHODS or not 0 <= value.confidence <= 1:
        raise ExtractionValidationError("invalid topic extraction metadata")


def evidence_searchable(item: Any) -> str:
    from analysis.cleaning import clean_text
    return normalize_text(" ".join((getattr(item, "cleaned_text", "") or clean_text(getattr(item, "text", "")), getattr(item, "url", "") or "", getattr(item, "post_id", "") or "")))
