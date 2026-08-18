from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class ConfigError(ValueError): pass


def load_config(path: str | Path) -> dict[str, Any]:
    value = Path(path).read_text(encoding="utf-8-sig")
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        data = _minimal_yaml(value)
    if not isinstance(data, dict) or not isinstance(data.get("entities"), dict): raise ConfigError("config must contain an entities mapping")
    default_type = str(data.get("default_entity_type") or "topic"); entities = []
    for name, spec in data["entities"].items():
        spec = spec if isinstance(spec, dict) else {}; entities.append({"entity": str(name), "entity_type": str(spec.get("entity_type") or default_type), **{k: spec[k] for k in ("query", "platforms", "feeds", "channels") if k in spec}})
    return {"default_entity_type": default_type, "entities": entities}


def _minimal_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {"entities": {}}; in_entities = False; entity: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        if line == "entities:": in_entities = True; entity = None; continue
        if not in_entities and line.startswith("default_entity_type:"):
            data["default_entity_type"] = line.split(":", 1)[1].strip(); continue
        if in_entities and ":" in line and not line.startswith("-"):
            key, value = line.split(":", 1); value = value.strip()
            if not value:
                entity = data["entities"].setdefault(key.strip(), {}); continue
            if entity is not None:
                entity[key.strip()] = value.strip().strip('"')
    return data


def run_project(config: Mapping[str, Any], *, workdir: Path | None = None, mock: bool = False, skip_collection: bool = False) -> list[dict[str, Any]]:
    from run_pipeline import run
    results = []
    for spec in config["entities"]:
        if not skip_collection and spec.get("query"):
            import sys
            scrapers_dir = Path(__file__).resolve().parent.parent / "scrapers"
            if str(scrapers_dir) not in sys.path:
                sys.path.insert(0, str(scrapers_dir))
            from run_collector import main
            args = ["--source", "last30days", "--entity", spec["entity"], "--entity-type", spec["entity_type"], "--query", str(spec["query"]), "--allow", f"{spec['entity']}:{spec['entity_type']}"]
            if mock: args.append("--mock")
            main(args)
        results.append(run(spec["entity"], workdir=workdir))
    return results
