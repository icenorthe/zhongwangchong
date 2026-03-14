from __future__ import annotations

import argparse
import json
import re
from json import JSONDecodeError, JSONDecoder
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATIONS_PATH = PROJECT_ROOT / "config" / "stations.local.json"
JSON_PARSER = JSONDecoder()
REGION_SORT_ORDER = {
    "综合楼": 1,
    "学术交流中心": 2,
    "东盟一号": 3,
    "19栋女生宿舍": 4,
}


def station_number_from_name(name: str) -> int:
    match = re.search(r"(\d+)号站", name)
    if not match:
        return 9999
    return int(match.group(1))


def infer_region(name: str, raw_region: str = "") -> str:
    region = raw_region.strip()
    if region:
        return region
    for keyword in REGION_SORT_ORDER:
        if keyword in name:
            return keyword
    return "未分区"


def extract_json_after_url(text: str, url: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    marker = f"URL: {url}"
    start_at = 0
    while True:
        marker_at = text.find(marker, start_at)
        if marker_at < 0:
            return blocks
        json_start = text.find("{", marker_at)
        if json_start < 0:
            return blocks
        try:
            payload, consumed = JSON_PARSER.raw_decode(text[json_start:])
        except JSONDecodeError:
            start_at = json_start + 1
            continue
        if isinstance(payload, dict):
            blocks.append(payload)
        start_at = json_start + consumed


def parse_capture_stations(capture_path: Path) -> list[dict[str, Any]]:
    text = capture_path.read_text(encoding="utf-8", errors="replace")
    stations: dict[str, dict[str, Any]] = {}

    def upsert(station: dict[str, Any]) -> None:
        device_code = str(station.get("device_code", "")).strip()
        name = str(station.get("name", "")).strip()
        if not device_code or not name:
            return
        existing = stations.get(device_code, {})
        merged = dict(existing)
        for key, value in station.items():
            if value in (None, "", [], {}):
                continue
            merged[key] = value
        merged.setdefault("id", f"cd-{station_number_from_name(name)}")
        merged.setdefault("name", name)
        merged.setdefault("device_code", device_code)
        merged.setdefault("sort_order", station_number_from_name(name))
        merged.setdefault("socket_count", 10)
        merged.setdefault("region", infer_region(name, str(merged.get("region", ""))))
        merged.setdefault("address", "四川省成都市龙泉驿区十陵街道成都大学")
        merged.setdefault("disabled_sockets", [])
        stations[device_code] = merged

    for payload in extract_json_after_url(text, "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_parseCk.action"):
        dev = payload.get("devInfo")
        if not isinstance(dev, dict):
            continue
        products = payload.get("products")
        socket_count = len(products) if isinstance(products, list) and products else 10
        upsert(
            {
                "id": f"cd-{station_number_from_name(str(dev.get('devName', '')))}",
                "name": str(dev.get("devName", "")).strip(),
                "device_code": str(dev.get("sn", "")).strip(),
                "sort_order": station_number_from_name(str(dev.get("devName", ""))),
                "socket_count": socket_count,
                "region": infer_region(str(dev.get("devName", ""))),
                "address": "四川省成都市龙泉驿区十陵街道成都大学",
                "plot_id": dev.get("plotId"),
                "gps_id": dev.get("gpsId"),
                "agent_id": dev.get("agentId"),
                "pid": dev.get("pid"),
                "device_ck": str(payload.get("deviceCk") or payload.get("ck") or "").strip(),
                "source": str(capture_path),
            }
        )

    for payload in extract_json_after_url(text, "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_pileUsingOrders.action"):
        using_orders = payload.get("usingOrders")
        if not isinstance(using_orders, list):
            continue
        for item in using_orders:
            if not isinstance(item, dict):
                continue
            upsert(
                {
                    "id": f"cd-{station_number_from_name(str(item.get('devName', '')))}",
                    "name": str(item.get("devName", "")).strip(),
                    "device_code": str(item.get("sn", "")).strip(),
                    "sort_order": station_number_from_name(str(item.get("devName", ""))),
                    "socket_count": 10,
                    "region": infer_region(str(item.get("devName", ""))),
                    "address": "四川省成都市龙泉驿区十陵街道成都大学",
                    "source": str(capture_path),
                }
            )

    return sorted(
        stations.values(),
        key=lambda item: (
            REGION_SORT_ORDER.get(str(item.get("region", "")), 99),
            int(item.get("sort_order", 9999)),
            str(item.get("name", "")),
        ),
    )


def merge_stations(existing: list[dict[str, Any]], discovered: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    by_device_code: dict[str, dict[str, Any]] = {}
    for item in existing:
        device_code = str(item.get("device_code", "")).strip()
        if device_code:
            by_device_code[device_code] = dict(item)

    added: list[str] = []
    updated: list[str] = []
    for item in discovered:
        device_code = str(item.get("device_code", "")).strip()
        if not device_code:
            continue
        current = by_device_code.get(device_code)
        if current is None:
            by_device_code[device_code] = dict(item)
            added.append(device_code)
            continue
        merged = dict(current)
        before = json.dumps(current, ensure_ascii=False, sort_keys=True)
        for key, value in item.items():
            if value in (None, "", [], {}):
                continue
            if key == "address" and str(merged.get("address", "")).strip():
                continue
            if key == "region" and str(merged.get("region", "")).strip() and merged.get("region") != "未分区":
                continue
            merged[key] = value
        after = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        by_device_code[device_code] = merged
        if after != before:
            updated.append(device_code)

    merged_list = sorted(
        by_device_code.values(),
        key=lambda item: (
            REGION_SORT_ORDER.get(str(item.get("region", "")), 99),
            int(item.get("sort_order", 9999)),
            str(item.get("name", "")),
        ),
    )
    return merged_list, added, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge station metadata from a capture log into local station config")
    parser.add_argument("--capture", required=True, help="Path to the captured log file")
    parser.add_argument("--stations", default=str(DEFAULT_STATIONS_PATH), help="Path to stations.local.json")
    parser.add_argument("--write", action="store_true", help="Write merged results back to the selected stations file")
    args = parser.parse_args()

    capture_path = Path(args.capture).expanduser().resolve()
    stations_path = Path(args.stations).expanduser().resolve()
    existing = json.loads(stations_path.read_text(encoding="utf-8-sig"))
    if not isinstance(existing, list):
        raise RuntimeError(f"Expected a list in {stations_path}")

    discovered = parse_capture_stations(capture_path)
    merged, added, updated = merge_stations(existing, discovered)

    print(f"capture={capture_path}")
    print(f"stations_before={len(existing)} discovered={len(discovered)} stations_after={len(merged)}")
    print(f"added={added}")
    print(f"updated={updated}")
    for item in discovered:
        print(json.dumps(item, ensure_ascii=False))

    if args.write:
        stations_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote={stations_path}")


if __name__ == "__main__":
    main()
