from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable
from urllib.parse import urlparse

from analysis.extraction_models import EntityExtraction, best_method, confidence, contains_term, deterministic_id, evidence_searchable, normalize_phrase, validate_entity

GAZETTEER = (
    ("OpenAI", "organization", ("openai",)), ("Google", "organization", ("google", "alphabet")),
    ("GitHub", "organization", ("github", "github.com")), ("Reddit", "organization", ("reddit", "reddit.com")),
    ("YouTube", "organization", ("youtube",)), ("Artificial Intelligence", "technology", ("artificial intelligence", "ai")),
    ("Large Language Model", "technology", ("llm", "large language model")), ("United States", "location", ("united states", "america")),
)
HOST_ORGANIZATIONS = {"github.com": "GitHub", "reddit.com": "Reddit", "youtube.com": "YouTube", "openai.com": "OpenAI"}


def extract_entities(items: Iterable[Any]) -> list[EntityExtraction]:
    items = list(items); buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        surface = evidence_searchable(item)
        for name, etype, aliases in GAZETTEER:
            if any(contains_term(surface, term) for term in (name, *aliases)):
                key = (normalize_phrase(name), etype); bucket = buckets.setdefault(key, {"name": name, "methods": set(), "ids": set(), "aliases": set()}); bucket["methods"].add("explicit"); bucket["ids"].add(item.evidence_id)
        url = getattr(item, "url", "") or ""
        host = (urlparse(url).hostname or "").lower()
        if host in HOST_ORGANIZATIONS:
            name = HOST_ORGANIZATIONS[host]; key = (normalize_phrase(name), "organization"); bucket = buckets.setdefault(key, {"name": name, "methods": set(), "ids": set(), "aliases": set()}); bucket["methods"].add("pattern"); bucket["ids"].add(item.evidence_id)
        for match in re.finditer(r"\b(?:v|version)\s*(\d+(?:\.\d+)*)\b", getattr(item, "text", ""), re.I):
            name = f"Version {match.group(1)}"; key = (normalize_phrase(name), "product"); bucket = buckets.setdefault(key, {"name": name, "methods": set(), "ids": set(), "aliases": set()}); bucket["methods"].add("pattern"); bucket["ids"].add(item.evidence_id)
    result = []
    for (_key, etype), bucket in buckets.items():
        method = best_method(bucket["methods"]); ids = sorted(bucket["ids"]); value = EntityExtraction(deterministic_id("ent", bucket["name"], etype), bucket["name"], etype, sorted(bucket["aliases"]), ids, confidence(method, len(ids)), method, f"Matched explicitly or structurally in {len(ids)} evidence item(s).")
        validate_entity(value); result.append(value)
    return sorted(result, key=lambda x: (-x.confidence, x.canonical_name, x.entity_type))
