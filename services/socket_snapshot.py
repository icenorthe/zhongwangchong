from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    from services.project_paths import CONFIG_DIR
    from services.realtime_http import post_form_json as realtime_post_form_json
    from services.station_config import load_station_source_items
except ImportError:
    from project_paths import CONFIG_DIR
    from realtime_http import post_form_json as realtime_post_form_json
    from station_config import load_station_source_items


CHARGE_API_CONFIG_PATH = CONFIG_DIR / "charge_api_config.json"
STATION_PLACEHOLDERS_PATH = CONFIG_DIR / "station_placeholders.json"
REALTIME_PARSECK_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_parseCk.action"
REALTIME_USING_ORDERS_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_pileUsingOrders.action"
REALTIME_STATUS_TIMEOUT_SECONDS = max(2.0, float(os.getenv("REALTIME_STATUS_TIMEOUT_SECONDS", "10")))
REALTIME_STATUS_MAX_WORKERS = max(1, int(os.getenv("REALTIME_STATUS_MAX_WORKERS", "2")))
REALTIME_API_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
        "MiniProgramEnv/Windows WindowsWechat/WMPF"
    ),
    "Authorization": "",
}
REALTIME_STATION_CACHE_SECONDS = max(30, int(os.getenv("REALTIME_STATION_CACHE_SECONDS", "300")))
REALTIME_STATUS_SERIAL_RETRY_LIMIT = max(0, int(os.getenv("REALTIME_STATUS_SERIAL_RETRY_LIMIT", "2")))
REALTIME_STATUS_SERIAL_RETRY_SECONDS = max(
    0.0, float(os.getenv("REALTIME_STATUS_SERIAL_RETRY_SECONDS", "1.0"))
)
REGION_SORT_ORDER = {
    "综合楼": 1,
    "综合楼/图书馆": 1,
    "学术交流中心": 2,
    "东盟一号": 3,
    "19栋": 4,
    "19栋女生宿舍": 4,
    "19栋宿舍": 4,
}
HIDDEN_STATION_NUMBERS = {3, 46, 70}
_station_realtime_cache: dict[str, dict[str, Any]] = {}


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_numeric(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def parse_seconds(value: Any) -> int | None:
    raw = parse_numeric(value)
    if raw is None or raw <= 0:
        return None
    return raw


def parse_millis_as_seconds(value: Any) -> int | None:
    raw = parse_numeric(value)
    if raw is None or raw <= 0:
        return None
    return max(1, (raw + 999) // 1000)


def optional_text(value: Any) -> str:
    return str(value or "").strip()


def pick_end_time(item: dict[str, Any]) -> str:
    raw = (
        item.get("endTime")
        or item.get("finishTime")
        or item.get("stopTime")
        or item.get("end_time")
        or item.get("finish_time")
        or item.get("stop_time")
    )
    text = optional_text(raw)
    if not text:
        return ""
    if parse_numeric(text) is not None:
        return ""
    return text


def pick_remain_seconds(item: dict[str, Any]) -> int | None:
    remain = parse_seconds(
        item.get("remainSeconds")
        or item.get("leftSeconds")
        or item.get("remainingSeconds")
        or item.get("surplusSeconds")
        or item.get("countdown")
        or item.get("remain_seconds")
        or item.get("left_seconds")
        or item.get("remaining_seconds")
    )
    if remain is not None and remain > 0:
        return remain
    end_time_raw = (
        item.get("endTime")
        or item.get("finishTime")
        or item.get("stopTime")
        or item.get("end_time")
        or item.get("finish_time")
        or item.get("stop_time")
    )
    return parse_millis_as_seconds(end_time_raw)


def station_number_from_name(name: str) -> int:
    digits = []
    for ch in str(name or ""):
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    return int("".join(digits)) if digits else 9999


def station_hidden_from_web(name: str) -> bool:
    return station_number_from_name(name) in HIDDEN_STATION_NUMBERS


def infer_station_region(name: str, raw_region: str = "") -> str:
    region = raw_region.strip()
    if region:
        return region
    for keyword in REGION_SORT_ORDER:
        if keyword in name:
            return keyword
    if "东盟一号" in name:
        return "东盟一号"
    if "学术交流中心" in name:
        return "学术交流中心"
    if "19栋女生宿舍" in name:
        return "19栋"
    return "综合楼"


def normalize_disabled_sockets(item: dict[str, Any], socket_count: int) -> list[int]:
    raw = item.get("disabled_sockets", item.get("faulty_sockets", []))
    if not isinstance(raw, list):
        return []
    disabled: set[int] = set()
    for value in raw:
        socket_no = optional_int(value)
        if socket_no is not None and 1 <= socket_no <= socket_count:
            disabled.add(socket_no)
    return sorted(disabled)


def expand_number_spec(spec: str) -> list[int]:
    values: set[int] = set()
    for chunk in str(spec or "").split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = optional_int(left)
            end = optional_int(right)
            if start is None or end is None:
                continue
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                values.add(number)
            continue
        single = optional_int(part)
        if single is not None:
            values.add(single)
    return sorted(values)


def load_station_placeholders() -> list[dict[str, Any]]:
    if not STATION_PLACEHOLDERS_PATH.exists():
        return []
    try:
        data = json.loads(STATION_PLACEHOLDERS_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    default_address = "四川省成都市龙泉驿区十陵街道成都大学"
    placeholders: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        region = optional_text(item.get("region"))
        name_template = optional_text(item.get("name_template"))
        number_spec = optional_text(item.get("station_numbers"))
        if not region or not name_template or not number_spec:
            continue
        address = optional_text(item.get("address")) or default_address
        source = optional_text(item.get("source")) or "user-provided-list"
        socket_count = optional_int(item.get("socket_count")) or 10
        socket_count = max(1, min(socket_count, 20))
        for number in expand_number_spec(number_spec):
            placeholders.append(
                {
                    "id": f"cd-{number}",
                    "region": region,
                    "sort_order": number,
                    "name": name_template.replace("{n}", str(number)),
                    "device_code": "",
                    "socket_count": socket_count,
                    "disabled_sockets": [],
                    "address": address,
                    "source": source,
                }
            )
    return placeholders


def load_stations() -> list[dict[str, Any]]:
    merged_data = load_station_source_items() + load_station_placeholders()
    stations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_numbers: set[int] = set()
    for item in merged_data:
        if not isinstance(item, dict):
            continue
        name = optional_text(item.get("name"))
        device_code = optional_text(item.get("device_code", item.get("sn", "")))
        if not name:
            continue
        if station_hidden_from_web(name):
            continue
        sort_order = optional_int(item.get("sort_order")) or station_number_from_name(name)
        station_id = optional_text(item.get("id")) or (device_code or f"station-{sort_order}")
        if station_id in seen_ids or sort_order in seen_numbers:
            continue
        socket_count = optional_int(item.get("socket_count", item.get("total", 10))) or 10
        socket_count = max(1, min(socket_count, 20))
        station = {
            "id": station_id,
            "name": name,
            "device_code": device_code,
            "socket_count": socket_count,
            "address": optional_text(item.get("address")),
            "region": infer_station_region(name, optional_text(item.get("region"))),
            "sort_order": sort_order,
            "disabled_sockets": normalize_disabled_sockets(item, socket_count),
        }
        for key, aliases in {
            "plot_id": ("plot_id", "plotId"),
            "gps_id": ("gps_id", "gpsId"),
            "agent_id": ("agent_id", "agentId"),
            "pid": ("pid",),
        }.items():
            for alias in aliases:
                value = optional_int(item.get(alias))
                if value is not None:
                    station[key] = value
                    break
        for key, aliases in {
            "device_ck": ("device_ck", "deviceCk"),
            "source": ("source",),
        }.items():
            for alias in aliases:
                value = optional_text(item.get(alias))
                if value:
                    station[key] = value
                    break
        stations.append(station)
        seen_ids.add(station_id)
        seen_numbers.add(sort_order)
    stations.sort(
        key=lambda item: (
            REGION_SORT_ORDER.get(str(item.get("region", "")), 99),
            int(item.get("sort_order", 9999)),
            str(item.get("name", "")),
        )
    )
    return stations


def load_charge_api_config() -> dict[str, Any]:
    if not CHARGE_API_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CHARGE_API_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def configured_member_id() -> str:
    """状态查询专用：优先使用只读ID（member_id_status），没有则回退使用充电ID"""
    data = load_charge_api_config()
    
    # 优先使用专门的状态查询ID（推荐用于插座状态）
    status_id = optional_text(data.get("member_id_status"))
    if status_id:
        return status_id
    
    # 回退到充电ID
    charge_id = optional_text(data.get("member_id"))
    if charge_id:
        return charge_id
    
    return ""


def post_form_json(url: str, payload: dict[str, Any], timeout: float = REALTIME_STATUS_TIMEOUT_SECONDS) -> dict[str, Any]:
    return realtime_post_form_json(
        url,
        payload,
        REALTIME_API_HEADERS,
        timeout=timeout,
    )


def cache_station_realtime(device_code: str, result: dict[str, Any]) -> None:
    if not device_code or not result.get("ok"):
        return
    _station_realtime_cache[device_code] = {
        "cached_at": time.time(),
        "result": json.loads(json.dumps(result, ensure_ascii=False)),
    }


def cached_station_realtime(device_code: str) -> dict[str, Any] | None:
    cached = _station_realtime_cache.get(device_code)
    if not cached:
        return None
    if (time.time() - float(cached.get("cached_at", 0))) > REALTIME_STATION_CACHE_SECONDS:
        _station_realtime_cache.pop(device_code, None)
        return None
    result = cached.get("result")
    if not isinstance(result, dict):
        return None
    data = json.loads(json.dumps(result, ensure_ascii=False))
    message = optional_text(data.get("message"))
    data["message"] = "实时接口短暂异常，已回退最近成功快照" if not message else f"{message}（已回退最近成功快照）"
    data["cached"] = True
    return data


def should_serial_retry_realtime_error(err: BaseException) -> bool:
    text = str(err or "").lower()
    markers = (
        "unexpected eof while reading",
        "eof occurred in violation of protocol",
        "timed out",
        "connection reset by peer",
        "remote end closed connection",
        "handshake operation timed out",
    )
    return any(marker in text for marker in markers)


def fetch_using_orders(member_id: str) -> tuple[dict[tuple[str, int], dict[str, Any]], str]:
    if not member_id:
        return {}, "配置缺少 member_id"
    payload = post_form_json(REALTIME_USING_ORDERS_URL, {"memberId": member_id, "miniAppType": "1"})
    using_orders: dict[tuple[str, int], dict[str, Any]] = {}
    rows = payload.get("usingOrders")
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict):
                continue
            device_code = optional_text(item.get("sn"))
            socket_no = optional_int(item.get("sid"))
            if not device_code or socket_no is None or socket_no <= 0:
                continue
            start_time = optional_text(item.get("startTime"))
            end_time = pick_end_time(item)
            remain_seconds = pick_remain_seconds(item)
            using_orders[(device_code, socket_no)] = {
                "status": "充电中",
                "detail": f"开始时间：{start_time}" if start_time else "",
                "start_time": start_time,
                "end_time": end_time,
                "remain_seconds": remain_seconds,
            }
    return using_orders, optional_text(payload.get("msg"))


def fetch_station_realtime(station: dict[str, Any], member_id: str) -> dict[str, Any]:
    device_ck = optional_text(station.get("device_ck"))
    if not member_id:
        return {"ok": False, "message": "配置缺少 member_id", "products": []}
    if not device_ck:
        return {"ok": False, "message": "缺少 device_ck", "products": []}
    payload = post_form_json(
        REALTIME_PARSECK_URL,
        {"ck": device_ck, "memberId": member_id, "miniAppType": "1"},
    )
    products = payload.get("products")
    product_list = products if isinstance(products, list) else []
    ok = int(payload.get("normal", 0) or 0) == 1 and bool(product_list)
    message = optional_text(payload.get("msg"))
    if ok:
        return {"ok": True, "message": message, "products": product_list}
    return {"ok": False, "message": message or "实时接口未返回插座状态", "products": product_list}


def compute_live_socket_state_snapshot() -> list[dict[str, Any]]:
    stations = load_stations()
    member_id = configured_member_id()
    using_orders: dict[tuple[str, int], dict[str, Any]] = {}
    realtime_by_device: dict[str, dict[str, Any]] = {}
    serial_retry_candidates: list[dict[str, Any]] = []

    if member_id:
        try:
            using_orders, _ = fetch_using_orders(member_id)
        except Exception:
            using_orders = {}
        realtime_candidates = [station for station in stations if optional_text(station.get("device_ck"))]
        if realtime_candidates:
            max_workers = min(REALTIME_STATUS_MAX_WORKERS, len(realtime_candidates))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_station = {
                    executor.submit(fetch_station_realtime, station, member_id): station for station in realtime_candidates
                }
                for future in as_completed(future_to_station):
                    station = future_to_station[future]
                    device_code = str(station["device_code"])
                    try:
                        result = future.result()
                        realtime_by_device[device_code] = result
                        cache_station_realtime(device_code, result)
                    except Exception as err:
                        cached = cached_station_realtime(device_code)
                        if cached is not None:
                            realtime_by_device[device_code] = cached
                        else:
                            realtime_by_device[device_code] = {
                                "ok": False,
                                "message": f"实时接口异常: {err}",
                                "products": [],
                            }
                            if should_serial_retry_realtime_error(err):
                                serial_retry_candidates.append(station)
            if serial_retry_candidates:
                for station in serial_retry_candidates[:REALTIME_STATUS_SERIAL_RETRY_LIMIT]:
                    device_code = str(station["device_code"])
                    try:
                        result = fetch_station_realtime(station, member_id)
                        realtime_by_device[device_code] = result
                        cache_station_realtime(device_code, result)
                    except Exception:
                        pass
                    if REALTIME_STATUS_SERIAL_RETRY_SECONDS > 0:
                        time.sleep(REALTIME_STATUS_SERIAL_RETRY_SECONDS)

    regions: dict[str, dict[str, Any]] = {}
    for station in stations:
        region_name = str(station["region"])
        region = regions.setdefault(region_name, {"region": region_name, "stations": []})
        station_result = realtime_by_device.get(str(station["device_code"]))
        if station_result is None:
            if not member_id:
                station_result = {"ok": False, "message": "配置缺少 member_id", "products": []}
            elif not optional_text(station.get("device_code")):
                station_result = {"ok": False, "message": "仅录入站号，缺少 device_code / device_ck", "products": []}
            elif optional_text(station.get("device_ck")):
                station_result = {"ok": False, "message": "实时接口未返回结果", "products": []}
            else:
                station_result = {"ok": False, "message": "缺少 device_ck", "products": []}

        disabled = {int(item) for item in station.get("disabled_sockets", [])}
        product_map = {}
        for product in station_result.get("products", []):
            if not isinstance(product, dict):
                continue
            sid = optional_int(product.get("sid"))
            if sid is not None and sid > 0:
                product_map[sid] = product

        sockets = []
        for socket_no in range(1, int(station.get("socket_count", 10)) + 1):
            if socket_no in disabled:
                sockets.append({"socket_no": socket_no, "status": "故障", "detail": "已标记故障"})
                continue
            product = product_map.get(socket_no)
            if station_result.get("ok") and product is not None:
                state = optional_int(product.get("state"))
                if state == 1:
                    snapshot = using_orders.get((str(station.get("device_code", "")), socket_no))
                    if snapshot is not None:
                        socket_data = {
                            "socket_no": socket_no,
                            "status": "充电中",
                            "detail": optional_text(snapshot.get("detail")),
                        }
                        for key in ("start_time", "end_time", "remain_seconds"):
                            if snapshot.get(key) not in (None, ""):
                                socket_data[key] = snapshot.get(key)
                        sockets.append(socket_data)
                        continue
                    end_time = pick_end_time(product)
                    remain_seconds = pick_remain_seconds(product)
                    socket_data = {
                        "socket_no": socket_no,
                        "status": "充电中",
                        "detail": "",
                    }
                    if end_time:
                        socket_data["end_time"] = end_time
                    if remain_seconds is not None and remain_seconds > 0:
                        socket_data["remain_seconds"] = remain_seconds
                    sockets.append(socket_data)
                    continue
                socket_data = {
                    "socket_no": socket_no,
                    "status": "空闲" if state == 0 else "充电中" if state == 1 else "未查询到",
                    "detail": "",
                }
                if state == 0:
                    snapshot = using_orders.get((str(station.get("device_code", "")), socket_no))
                    if snapshot is not None:
                        for key in ("start_time", "end_time", "remain_seconds"):
                            if snapshot.get(key) not in (None, ""):
                                socket_data[key] = snapshot.get(key)
                    end_time = pick_end_time(product)
                    remain_seconds = pick_remain_seconds(product)
                    if "end_time" not in socket_data and end_time:
                        socket_data["end_time"] = end_time
                    if (
                        "remain_seconds" not in socket_data
                        and remain_seconds is not None
                        and remain_seconds > 0
                    ):
                        socket_data["remain_seconds"] = remain_seconds
                sockets.append(socket_data)
                continue
            snapshot = using_orders.get((str(station.get("device_code", "")), socket_no))
            if snapshot is not None:
                socket_data = {
                    "socket_no": socket_no,
                    "status": "充电中",
                    "detail": optional_text(snapshot.get("detail")),
                }
                for key in ("start_time", "end_time", "remain_seconds"):
                    if snapshot.get(key) not in (None, ""):
                        socket_data[key] = snapshot.get(key)
                sockets.append(socket_data)
            else:
                sockets.append({"socket_no": socket_no, "status": "未查询到", "detail": ""})

        region["stations"].append(
            {
                "id": station["id"],
                "name": station["name"],
                "device_code": station["device_code"],
                "region": region_name,
                "query_message": optional_text(station_result.get("message"))
                if (not station_result.get("ok") or station_result.get("cached"))
                else "",
                "realtime_ok": bool(station_result.get("ok")),
                "sockets": sockets,
            }
        )

    return list(regions.values())
