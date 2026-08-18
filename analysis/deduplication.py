from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import parse_qsl, urlparse, urlunparse
from typing import Any, Iterable

from analysis.extraction_models import deterministic_id, normalize_phrase
from analysis.signal_models import EvidenceCluster, validate_cluster

NEAR_DUPLICATE_THRESHOLD = .75
SHARED_ENTITY_WINDOW_DAYS = 30
GENERIC_ENTITY_NAMES = frozenset({"ai", "artificial intelligence", "technology", "software", "data", "web", "github", "reddit", "youtube", "x"})
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "ref"}


def normalize_url(url: str | None) -> str:
    if not url: return ""
    parsed = urlparse(str(url).strip()); host = (parsed.hostname or "").lower().removeprefix("www."); path = (parsed.path or "/").rstrip("/") or "/"
    query = "&".join(f"{k}={v}" for k, v in sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in TRACKING))
    return urlunparse(("https" if parsed.scheme in ("", "http", "https") else parsed.scheme.lower(), host, path, "", query, "")).lower()


def normalize_post_id(post_id: str | None) -> str: return normalize_phrase(post_id or "")
def normalize_evidence_text(text: str | None) -> str: return " ".join((text or "").lower().split())
def token_set(text: str) -> set[str]: return set(re.findall(r"[a-z0-9]+", normalize_evidence_text(text)))
def jaccard(a: str, b: str) -> float:
    x, y = token_set(a), token_set(b)
    return 1.0 if not x and not y else 0.0 if not x or not y else len(x & y) / len(x | y)


def _union(groups: list[set[int]], a: int, b: int) -> None:
    left = next(g for g in groups if a in g); right = next(g for g in groups if b in g)
    if left is not right: left.update(right); groups.remove(right)


def cluster_evidence(items: Iterable[Any], *, entities: Iterable[Any] | None = None, topics: Iterable[Any] | None = None, near_duplicate_threshold: float = NEAR_DUPLICATE_THRESHOLD, shared_entity_window_days: int = SHARED_ENTITY_WINDOW_DAYS) -> list[EvidenceCluster]:
    items = sorted(list(items), key=lambda x: x.evidence_id)
    if not items: return []
    groups = [{i} for i in range(len(items))]; reason: dict[frozenset[int], str] = {}
    rank = {"exact_url": 0, "duplicate_post_id": 1, "exact_text": 2, "near_duplicate_text": 3, "shared_entity": 4, "isolated": 5}
    def merge(key_fn, label):
        buckets: dict[str, list[int]] = defaultdict(list)
        for idx, item in enumerate(items):
            key = key_fn(item)
            if key: buckets[key].append(idx)
        for indexes in buckets.values():
            for idx in indexes[1:]: _union(groups, indexes[0], idx); reason[frozenset(indexes)] = label
    merge(lambda x: normalize_url(getattr(x, "url", None)), "exact_url")
    merge(lambda x: normalize_post_id(getattr(x, "post_id", None)), "duplicate_post_id")
    merge(lambda x: normalize_evidence_text(getattr(x, "cleaned_text", "") or getattr(x, "text", "")), "exact_text")
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if jaccard(getattr(items[a], "cleaned_text", "") or items[a].text, getattr(items[b], "cleaned_text", "") or items[b].text) >= near_duplicate_threshold:
                _union(groups, a, b); reason[frozenset((a, b))] = "near_duplicate_text"
    entity_map: dict[str, set[str]] = defaultdict(set); topic_map: dict[str, set[str]] = defaultdict(set)
    for value in entities or []:
        for eid in value.source_evidence_ids: entity_map[eid].add(value.canonical_name)
    for value in topics or []:
        for eid in value.source_evidence_ids: topic_map[eid].add(value.canonical_name)
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            shared = (entity_map[items[a].evidence_id] & entity_map[items[b].evidence_id]) - GENERIC_ENTITY_NAMES
            if shared and topic_map[items[a].evidence_id] & topic_map[items[b].evidence_id]:
                from analysis.signal_models import days_between
                if days_between(min(items[a].timestamp, items[b].timestamp), max(items[a].timestamp, items[b].timestamp)) <= shared_entity_window_days:
                    _union(groups, a, b); reason[frozenset((a, b))] = "shared_entity"
    output = []
    for group in sorted(groups, key=lambda g: min(items[i].evidence_id for i in g)):
        members = [items[i] for i in sorted(group)]; ids = [x.evidence_id for x in members]; key = frozenset(group)
        candidates = [label for keyset, label in reason.items() if keyset <= key]
        label = min(candidates, key=lambda x: rank[x]) if candidates else "isolated"
        title = next((" ".join((x.cleaned_text or x.text).split())[:120] for x in sorted(members, key=lambda x: (x.timestamp, x.evidence_id)) if x.cleaned_text or x.text), "Untitled evidence")
        cluster = EvidenceCluster(deterministic_id("clu", label, *sorted(ids)), ids, title, sorted({n for x in members for n in entity_map[x.evidence_id]}), sorted({n for x in members for n in topic_map[x.evidence_id]}), len({x.source for x in members}), len({x.platform for x in members}), min(x.timestamp for x in members), max(x.timestamp for x in members), label)
        validate_cluster(cluster); output.append(cluster)
    return sorted(output, key=lambda x: (x.first_seen, x.cluster_id))

find_duplicate_clusters = cluster_evidence


def clusters_jsonl(clusters: Iterable[EvidenceCluster], path: str) -> int:
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True); count = 0
    with open(path, "w", encoding="utf-8") as handle:
        for value in clusters: handle.write(value.to_json() + "\n"); count += 1
    return count
