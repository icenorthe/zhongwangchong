from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.project_paths import CONFIG_DIR


STATIONS_PUBLIC_PATH = CONFIG_DIR / "stations.public.json"
STATIONS_LOCAL_PATH = CONFIG_DIR / "stations.local.json"
STATIONS_LEGACY_PATH = CONFIG_DIR / "stations.json"


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def load_station_source_items() -> list[dict[str, Any]]:
    public_items = load_json_list(STATIONS_PUBLIC_PATH)
    local_items = load_json_list(STATIONS_LOCAL_PATH)
    if public_items or local_items:
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for source_items in (public_items, local_items):
            for item in source_items:
                station_id = str(item.get("id", "")).strip()
                device_code = str(item.get("device_code", "")).strip()
                sort_order = str(item.get("sort_order", "")).strip()
                name = str(item.get("name", "")).strip()
                key = station_id or device_code or sort_order or name
                if not key:
                    continue
                if key not in merged:
                    merged[key] = {}
                    order.append(key)
                merged[key].update(item)
        return [merged[key] for key in order]
    return load_json_list(STATIONS_LEGACY_PATH)
