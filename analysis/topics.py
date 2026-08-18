from __future__ import annotations

from typing import Any, Iterable
from analysis.extraction_models import TopicExtraction, best_method, confidence, contains_term, deterministic_id, evidence_searchable, normalize_phrase, validate_topic

TOPIC_LEXICON = (
    ("Funding & Investment", ("funding", "investment", "valuation", "raises", "investors")),
    ("Product & Technology Releases", ("launch", "release", "released", "unveils", "update", "version")),
    ("Research & Publications", ("research", "study", "paper", "publication", "arxiv", "report", "survey", "data")),
    ("Labor Market", ("jobs", "hiring", "employment", "labor market", "workforce")),
    ("Regulation & Policy", ("regulation", "regulator", "law", "policy", "government", "ban", "council", "planning")),
    ("Market Developments", ("market", "prices", "sales", "demand", "economy", "growth")),
    ("Construction & Development", ("construction", "developer", "development", "approvals", "building", "site", "works")),
    ("Infrastructure & Transport", ("transport", "transit", "station", "road", "metro", "rail")),
    ("Supply & Housing", ("supply", "housing", "rent", "mortgage", "listings", "property")),
)


def extract_topics(items: Iterable[Any]) -> list[TopicExtraction]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        surface = evidence_searchable(item)
        for name, keywords in TOPIC_LEXICON:
            matched = sorted(k for k in keywords if contains_term(surface, k))
            if matched:
                bucket = buckets.setdefault(name, {"keywords": set(), "ids": set(), "methods": set()}); bucket["keywords"].update(matched); bucket["ids"].add(item.evidence_id); bucket["methods"].add("explicit")
    result = []
    for name, bucket in buckets.items():
        method = best_method(bucket["methods"]); ids = sorted(bucket["ids"]); value = TopicExtraction(deterministic_id("top", name), name, sorted(bucket["keywords"]), ids, confidence(method, len(ids)), method, f"Matched keywords {sorted(bucket['keywords'])} in {len(ids)} evidence item(s).")
        validate_topic(value); result.append(value)
    return sorted(result, key=lambda x: (-x.confidence, x.canonical_name))
