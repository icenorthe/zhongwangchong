"""
Mobile order service for charger control.

Flow:
1) User submits an order from phone web page.
2) Order is stored in SQLite with status PENDING.
3) Worker thread picks pending orders and calls official charger API.
4) Status is updated to SUCCESS/FAILED.

Important:
- This service is designed for legal use with official charger APIs.
- Do not use it to bypass access control or account restrictions.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

try:
    from services.project_paths import CONFIG_DIR, RUNTIME_DIR, WEB_ASSETS_DIR
    from services.realtime_http import post_form_json as realtime_post_form_json
    from services.station_config import load_station_source_items
except ImportError:
    from project_paths import CONFIG_DIR, RUNTIME_DIR, WEB_ASSETS_DIR
    from realtime_http import post_form_json as realtime_post_form_json
    from station_config import load_station_source_items

DB_PATH = RUNTIME_DIR / "orders.db"
HTML_PATH = WEB_ASSETS_DIR / "mobile_order.html"
ADMIN_HTML_PATH = WEB_ASSETS_DIR / "admin_orders.html"
GATEWAY_CONFIG_PATH = CONFIG_DIR / "gateway_config.json"
CHARGE_API_CONFIG_PATH = CONFIG_DIR / "charge_api_config.json"
STATION_PLACEHOLDERS_PATH = CONFIG_DIR / "station_placeholders.json"
POLL_INTERVAL_SECONDS = float(os.getenv("ORDER_POLL_INTERVAL_SECONDS", "2"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "1").lower() not in {"0", "false", "no"}
SESSION_EXPIRE_DAYS = int(os.getenv("SESSION_EXPIRE_DAYS", "30"))
AGENT_HEARTBEAT_EXPIRE_SECONDS = max(15, int(os.getenv("AGENT_HEARTBEAT_EXPIRE_SECONDS", "45")))
AGENT_SOCKET_OVERVIEW_EXPIRE_SECONDS = max(
    15, int(os.getenv("AGENT_SOCKET_OVERVIEW_EXPIRE_SECONDS", "90"))
)
REQUIRE_AGENT_ONLINE_FOR_ORDERS = os.getenv("REQUIRE_AGENT_ONLINE_FOR_ORDERS", "0").lower() in {
    "1",
    "true",
    "yes",
}
PAYMENT_MODE = os.getenv("PAYMENT_MODE", "disabled").strip().lower()
PAYMENT_BRIDGE_URL = os.getenv("PAYMENT_BRIDGE_URL", "").strip()
SOCKET_OVERVIEW_BRIDGE_URL = os.getenv("SOCKET_OVERVIEW_BRIDGE_URL", "").strip()
PAYMENT_TOKEN_SECRET = os.getenv("PAYMENT_TOKEN_SECRET", "").strip()
PAYMENT_TOKEN_TTL_SECONDS = int(os.getenv("PAYMENT_TOKEN_TTL_SECONDS", "900"))
BALANCE_REFUND_ON_FAIL = os.getenv("BALANCE_REFUND_ON_FAIL", "1").lower() in {"1", "true", "yes"}
if PAYMENT_MODE not in {"disabled", "balance", "token"}:
    PAYMENT_MODE = "disabled"

# 码支付配置。默认关闭，只有显式配置后才启用。
CODEPAY_ID = os.getenv("CODEPAY_ID", "").strip()
CODEPAY_KEY = os.getenv("CODEPAY_KEY", "").strip()
CODEPAY_API = os.getenv("CODEPAY_API", "").strip().rstrip("/")
CODEPAY_ENABLED = bool(CODEPAY_ID and CODEPAY_KEY and CODEPAY_API)
SERVICE_FEE_YUAN = float(os.getenv("SERVICE_FEE_YUAN", "1.0"))
RECHARGE_BONUS_RULES = (
    (20.0, 5.0),
    (10.0, 2.0),
)

MINUTES_PER_YUAN = 207
DEFAULT_RECHARGE_QR_NOTE = "线下付款后提交充值申请，管理员确认到账后补余额。"
MANUAL_PAYMENT_CONTACT = os.getenv("MANUAL_PAYMENT_CONTACT", "").strip()
MANUAL_PAYMENT_INSTRUCTIONS = os.getenv("MANUAL_PAYMENT_INSTRUCTIONS", "").strip()
REALTIME_STATUS_TIMEOUT_SECONDS = max(2.0, float(os.getenv("REALTIME_STATUS_TIMEOUT_SECONDS", "10")))
REALTIME_STATUS_MAX_WORKERS = max(1, int(os.getenv("REALTIME_STATUS_MAX_WORKERS", "4")))
REALTIME_PARSECK_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_parseCk.action"
REALTIME_USING_ORDERS_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_pileUsingOrders.action"
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
REALTIME_STATION_CACHE_SECONDS = max(30, int(os.getenv("REALTIME_STATION_CACHE_SECONDS", "180")))
REALTIME_STATUS_SERIAL_RETRY_LIMIT = max(0, int(os.getenv("REALTIME_STATUS_SERIAL_RETRY_LIMIT", "12")))
REALTIME_STATUS_SERIAL_RETRY_SECONDS = max(
    0.0, float(os.getenv("REALTIME_STATUS_SERIAL_RETRY_SECONDS", "0.35"))
)
REGION_SORT_ORDER = {
    "综合楼": 1,
    "学术交流中心": 2,
    "东盟一号": 3,
    "图书馆": 4,
    "19栋": 5,
    "19栋女生宿舍": 5,
}
HIDDEN_STATION_NUMBERS = {3, 46, 70}
_station_realtime_cache: dict[str, dict[str, Any]] = {}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_nested_value(data: Any, path: str, default: Any = None) -> Any:
    if not path:
        return default
    current = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def infer_station_region(name: str, raw_region: str = "") -> str:
    region = raw_region.strip()
    if region:
        return region
    for keyword in REGION_SORT_ORDER:
        if keyword in name:
            return keyword
    return "未分区"


def overview_region_key(raw_region: str) -> str:
    region = str(raw_region or "").strip()
    mapping = {
        "综合楼": "图书馆",
        "图书馆": "图书馆",
        "东盟一号": "东盟",
        "东盟": "东盟",
        "学术交流中心": "学术交流中心",
        "19栋": "19栋宿舍",
        "19栋女生宿舍": "19栋宿舍",
        "19栋宿舍": "19栋宿舍",
    }
    return mapping.get(region, region or "未分区")


def station_number_from_name(name: str) -> int:
    match = re.search(r"(\d+)号站", name)
    if not match:
        return 9999
    return int(match.group(1))


def station_hidden_from_web(name: str) -> bool:
    station_no = station_number_from_name(name)
    return station_no in HIDDEN_STATION_NUMBERS


def normalize_disabled_sockets(item: dict[str, Any], socket_count: int) -> list[int]:
    raw = item.get("disabled_sockets", item.get("faulty_sockets", []))
    if not isinstance(raw, list):
        return []
    disabled: set[int] = set()
    for value in raw:
        try:
            socket_no = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= socket_no <= socket_count:
            disabled.add(socket_no)
    return sorted(disabled)


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_text(value: Any) -> str:
    return str(value or "").strip()


def expand_number_spec(spec: str) -> list[int]:
    values: set[int] = set()
    for chunk in str(spec or "").split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            try:
                start = int(left.strip())
                end = int(right.strip())
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                values.add(number)
            continue
        try:
            values.add(int(part))
        except ValueError:
            continue
    return sorted(values)


def load_station_placeholders() -> list[dict[str, Any]]:
    if not STATION_PLACEHOLDERS_PATH.exists():
        return []
    try:
        raw = STATION_PLACEHOLDERS_PATH.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    placeholders: list[dict[str, Any]] = []
    default_address = "四川省成都市龙泉驿区十陵街道成都大学"
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


def approx_charge_minutes(amount_yuan: float) -> int:
    return max(0, int(round(float(amount_yuan) * MINUTES_PER_YUAN)))


def total_cost_yuan(amount_yuan: float) -> float:
    return round(float(amount_yuan) + SERVICE_FEE_YUAN, 2)


def recharge_bonus_yuan(amount_yuan: float) -> float:
    amount = float(amount_yuan or 0)
    for threshold, bonus in RECHARGE_BONUS_RULES:
        if amount + 1e-9 >= threshold:
            return bonus
    return 0.0


def estimated_finish_at(created_at: str, amount_yuan: float) -> str:
    started_at = parse_iso(created_at)
    if started_at is None:
        return ""
    return (started_at + timedelta(minutes=approx_charge_minutes(amount_yuan))).isoformat()


def charge_state_for_order(status: str, estimated_finish: str) -> tuple[str, str]:
    normalized = str(status or "").upper()
    if normalized == "FAILED":
        return "FAILED", ""
    if normalized in {"PENDING", "PROCESSING"}:
        return normalized, ""
    finish_at = parse_iso(estimated_finish)
    if normalized == "SUCCESS" and finish_at is not None:
        if datetime.now(UTC) >= finish_at:
            return "ENDED_ESTIMATED", estimated_finish
        return "CHARGING_ESTIMATED", ""
    return normalized, ""


def charge_stop_reason_from_message(message: Any) -> str:
    text = clean_result_message(message).strip()
    for reason in ("过充", "充电被拔", "被拔", "空载"):
        if reason in text:
            return "充电被拔" if reason == "被拔" else reason
    return ""


def clean_result_message(message: Any, status: str = "") -> str:
    text = str(message or "").replace("\x00", "").strip()
    replacements = {
        "鎴愬姛": "充电已提交成功",
        "鍏呯數鎺ュ彛杩斿洖澶辫触": "充电接口返回失败",
        "config 缂哄皯 member_id": "配置缺少 member_id",
        "璁㈠崟缂哄皯 device_code": "订单缺少 device_code",
    }
    for source, target in replacements.items():
        if source in text:
            return target

    if not text:
        if status == "SUCCESS":
            return "充电已提交成功"
        if status == "FAILED":
            return "充电失败，请稍后重试"
        return ""

    suspicious = {"?", "？", "\ufffd"}
    if text and all(char in suspicious for char in text):
        if status == "SUCCESS":
            return "充电已提交成功"
        if status == "FAILED":
            return "充电失败，请稍后重试"
    meaningful_chars = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)
    replacement_count = text.count("?") + text.count("？") + text.count("\ufffd")
    if replacement_count >= 2 and len(meaningful_chars) <= 2:
        if status == "SUCCESS":
            return "充电已提交成功"
        if status == "FAILED":
            return "充电失败，请稍后重试"
    return text


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", phone)
    if len(digits) != 11:
        raise HTTPException(status_code=422, detail="手机号必须为11位数字")
    return digits


def hash_password(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split(":", 1)
    except ValueError:
        return False
    expected = hash_password(password, salt_hex)
    return secrets.compare_digest(expected, f"{salt_hex}:{digest_hex}")


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now.timestamp() + SESSION_EXPIRE_DAYS * 86400
    expires_at_iso = datetime.fromtimestamp(expires_at, UTC).isoformat()
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO user_sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, now.isoformat(), expires_at_iso),
        )
        conn.commit()
    return token


def get_user_by_session_token(token: str) -> sqlite3.Row | None:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT users.id, users.phone, users.balance_yuan, users.created_at, users.updated_at,
                   user_sessions.expires_at
            FROM user_sessions
            JOIN users ON users.id = user_sessions.user_id
            WHERE user_sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now_iso():
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return row


def load_stations() -> list[dict[str, Any]]:
    merged_data = load_station_source_items() + load_station_placeholders()
    stations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_numbers: set[int] = set()
    for item in merged_data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        device_code = str(item.get("device_code", item.get("sn", ""))).strip()
        if not name:
            continue
        if station_hidden_from_web(name):
            continue
        fallback_id = f"station-{station_number_from_name(name)}"
        station_id = str(item.get("id", device_code or fallback_id)).strip()
        socket_count = int(item.get("socket_count", item.get("total", 10)) or 10)
        socket_count = max(1, min(socket_count, 20))
        address = str(item.get("address", "")).strip()
        region = infer_station_region(name, str(item.get("region", "")))
        sort_order = int(item.get("sort_order", station_number_from_name(name)))
        if station_id in seen_ids or sort_order in seen_numbers:
            continue
        disabled_sockets = normalize_disabled_sockets(item, socket_count)
        station = {
            "id": station_id,
            "name": name,
            "device_code": device_code,
            "socket_count": socket_count,
            "address": address,
            "region": region,
            "sort_order": sort_order,
            "disabled_sockets": disabled_sockets,
            "order_enabled": bool(device_code),
        }
        for field, aliases in {
            "plot_id": ("plot_id", "plotId"),
            "gps_id": ("gps_id", "gpsId"),
            "agent_id": ("agent_id", "agentId"),
            "pid": ("pid",),
        }.items():
            value = None
            for alias in aliases:
                value = optional_int(item.get(alias))
                if value is not None:
                    break
            if value is not None:
                station[field] = value
        for field, aliases in {
            "device_ck": ("device_ck", "deviceCk"),
            "source": ("source",),
        }.items():
            value = ""
            for alias in aliases:
                value = optional_text(item.get(alias))
                if value:
                    break
            if value:
                station[field] = value
        seen_ids.add(station_id)
        seen_numbers.add(sort_order)
        stations.append(station)
    stations.sort(
        key=lambda item: (
            REGION_SORT_ORDER.get(item["region"], 99),
            int(item.get("sort_order", 9999)),
            item["name"],
        )
    )
    return stations


def load_charge_api_config() -> dict[str, Any]:
    if not CHARGE_API_CONFIG_PATH.exists():
        return {}
    try:
        raw = CHARGE_API_CONFIG_PATH.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


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


def configured_member_id() -> str:
    return optional_text(load_charge_api_config().get("member_id"))


def fetch_using_orders(member_id: str) -> tuple[dict[tuple[str, int], dict[str, Any]], str]:
    if not member_id:
        return {}, "配置缺少 member_id"
    payload = post_form_json(
        REALTIME_USING_ORDERS_URL,
        {"memberId": member_id, "miniAppType": "1"},
    )
    using_orders: dict[tuple[str, int], dict[str, Any]] = {}
    raw_rows = payload.get("usingOrders")
    if isinstance(raw_rows, list):
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            device_code = optional_text(item.get("sn"))
            socket_no = optional_int(item.get("sid"))
            if not device_code or socket_no is None or socket_no <= 0:
                continue
            start_time = optional_text(item.get("startTime"))
            # Official API fields may vary. We keep a human-friendly detail and also pass through
            # end/remaining time when available so the frontend can render a countdown.
            detail = f"开始时间：{start_time}" if start_time else ""
            end_time = optional_text(
                item.get("endTime")
                or item.get("finishTime")
                or item.get("stopTime")
                or item.get("end_time")
                or item.get("finish_time")
                or item.get("stop_time")
            )
            remain_seconds = optional_int(
                item.get("remainSeconds")
                or item.get("leftSeconds")
                or item.get("remainingSeconds")
                or item.get("surplusSeconds")
                or item.get("remain_seconds")
                or item.get("left_seconds")
                or item.get("remaining_seconds")
            )
            using_orders[(device_code, socket_no)] = {
                "status": "使用中",
                "detail": detail,
                "station_name": optional_text(item.get("devName")),
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
        {
            "ck": device_ck,
            "memberId": member_id,
            "miniAppType": "1",
        },
    )
    raw_products = payload.get("products")
    products = raw_products if isinstance(raw_products, list) else []
    ok = int(payload.get("normal", 0) or 0) == 1 and bool(products)
    message = optional_text(payload.get("msg"))
    if ok:
        return {"ok": True, "message": message, "products": products}
    if not message:
        message = "实时接口未返回插座状态"
    return {"ok": False, "message": message, "products": products}


def unknown_socket(socket_no: int, detail: str) -> dict[str, Any]:
    return {"socket_no": socket_no, "status": "未查询到", "detail": detail}


def disabled_socket(socket_no: int) -> dict[str, Any]:
    return {"socket_no": socket_no, "status": "故障", "detail": "已标记故障"}


def format_using_order_detail(snapshot: dict[str, Any]) -> str:
    return optional_text(snapshot.get("detail"))


def socket_status_from_product(
    station: dict[str, Any],
    socket_no: int,
    product: dict[str, Any],
    using_orders: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    state = optional_int(product.get("state"))
    if state == 0:
        return {"socket_no": socket_no, "status": "空闲", "detail": ""}
    if state == 1:
        snapshot = using_orders.get((str(station["device_code"]), socket_no))
        detail = format_using_order_detail(snapshot or {})
        data: dict[str, Any] = {"socket_no": socket_no, "status": "使用中", "detail": detail}
        if snapshot:
            # Pass-through optional countdown fields for the UI.
            for key in ("start_time", "end_time", "remain_seconds"):
                if snapshot.get(key) not in (None, ""):
                    data[key] = snapshot.get(key)
        return data
    return unknown_socket(socket_no, f"未知状态: {product.get('state')}")


def build_station_sockets(
    station: dict[str, Any],
    station_result: dict[str, Any],
    using_orders: dict[tuple[str, int], dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    disabled = {int(item) for item in station.get("disabled_sockets", [])}
    socket_count = int(station.get("socket_count", 10))
    device_code = str(station["device_code"])
    products = station_result.get("products")
    product_by_sid: dict[int, dict[str, Any]] = {}
    if isinstance(products, list):
        for product in products:
            if not isinstance(product, dict):
                continue
            sid = optional_int(product.get("sid"))
            if sid is None or sid <= 0:
                continue
            product_by_sid[sid] = product

    fallback_detail = optional_text(station_result.get("message"))
    sockets: list[dict[str, Any]] = []
    for socket_no in range(1, socket_count + 1):
        if socket_no in disabled:
            sockets.append(disabled_socket(socket_no))
            continue
        product = product_by_sid.get(socket_no)
        if product is not None and station_result.get("ok"):
            sockets.append(socket_status_from_product(station, socket_no, product, using_orders))
            continue
        snapshot = using_orders.get((device_code, socket_no))
        if snapshot is not None:
            data: dict[str, Any] = {
                "socket_no": socket_no,
                "status": "使用中",
                "detail": format_using_order_detail(snapshot),
            }
            for key in ("start_time", "end_time", "remain_seconds"):
                if snapshot.get(key) not in (None, ""):
                    data[key] = snapshot.get(key)
            sockets.append(data)
            continue
        if station_result.get("ok"):
            sockets.append(unknown_socket(socket_no, "实时接口未返回该插座"))
        else:
            sockets.append(unknown_socket(socket_no, ""))
    return sockets, fallback_detail


def compute_live_socket_state_snapshot(region_key: str | None = None) -> list[dict[str, Any]]:
    stations = load_stations()
    selected_region_key = overview_region_key(region_key) if region_key else ""
    if selected_region_key:
        stations = [
            station
            for station in stations
            if overview_region_key(station.get("region", "")) == selected_region_key
        ]
    member_id = configured_member_id()
    using_orders: dict[tuple[str, int], dict[str, Any]] = {}
    using_orders_message = ""
    realtime_by_device: dict[str, dict[str, Any]] = {}
    serial_retry_candidates: list[dict[str, Any]] = []

    if member_id:
        try:
            using_orders, using_orders_message = fetch_using_orders(member_id)
        except Exception as err:
            using_orders_message = f"实时接口异常: {err}"
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
        has_using_order = any(device_code == str(station["device_code"]) for device_code, _ in using_orders)
        station_result = realtime_by_device.get(str(station["device_code"]))
        if station_result is None:
            if not member_id:
                station_result = {"ok": False, "message": "配置缺少 member_id", "products": []}
            elif not optional_text(station.get("device_code")):
                station_result = {"ok": False, "message": "仅录入站号，缺少 device_code / device_ck", "products": []}
            elif optional_text(station.get("device_ck")):
                station_result = {"ok": False, "message": "实时接口未返回结果", "products": []}
            elif has_using_order:
                station_result = {"ok": False, "message": "缺少 device_ck；仅能识别当前账号充电中的插座", "products": []}
            else:
                station_result = {"ok": False, "message": "缺少 device_ck", "products": []}
        sockets, query_message = build_station_sockets(station, station_result, using_orders)
        region["stations"].append(
            {
                "id": station["id"],
                "name": station["name"],
                "device_code": station["device_code"],
                "region": region_name,
                "query_message": query_message if (not station_result.get("ok") or station_result.get("cached")) else "",
                "realtime_ok": bool(station_result.get("ok")),
                "sockets": sockets,
            }
        )
    return list(regions.values())


def db_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER DEFAULT NULL,
                pile_no TEXT NOT NULL,
                phone TEXT NOT NULL,
                minutes INTEGER NOT NULL,
                station_name TEXT NOT NULL DEFAULT '',
                device_code TEXT NOT NULL DEFAULT '',
                socket_no INTEGER NOT NULL DEFAULT 1,
                amount_yuan REAL NOT NULL DEFAULT 1,
                remark TEXT DEFAULT '',
                status TEXT NOT NULL,
                result_message TEXT DEFAULT '',
                vendor_order_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runtime (
                agent_name TEXT PRIMARY KEY,
                machine_name TEXT NOT NULL DEFAULT '',
                runner_command TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                current_order_id INTEGER DEFAULT NULL,
                heartbeat_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_socket_overview (
                agent_name TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount_yuan REAL NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT '',
                used_order_id INTEGER DEFAULT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                delta_yuan REAL NOT NULL,
                balance_after REAL NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_payments (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                station_name TEXT NOT NULL DEFAULT '',
                device_code TEXT NOT NULL,
                socket_no INTEGER NOT NULL DEFAULT 1,
                amount_yuan REAL NOT NULL DEFAULT 1,
                remark TEXT DEFAULT '',
                service_fee REAL NOT NULL DEFAULT 1.0,
                pay_type INTEGER NOT NULL DEFAULT 2,
                status TEXT NOT NULL DEFAULT 'PENDING',
                codepay_order_no TEXT DEFAULT '',
                charge_order_id INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                paid_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recharge_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                amount_yuan REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                payment_method TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_at TEXT NOT NULL DEFAULT '',
                review_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        ensure_user_columns(conn)
        ensure_order_columns(conn)
        ensure_recharge_request_columns(conn)
        conn.commit()


def ensure_user_columns(conn: sqlite3.Connection) -> None:
    required_columns = {
        "balance_yuan": "REAL NOT NULL DEFAULT 0",
    }
    rows = conn.execute("PRAGMA table_info(users)").fetchall()
    existing = {row["name"] for row in rows}
    for column_name, column_type in required_columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")


def ensure_order_columns(conn: sqlite3.Connection) -> None:
    required_columns = {
        "user_id": "INTEGER DEFAULT NULL",
        "station_name": "TEXT NOT NULL DEFAULT ''",
        "device_code": "TEXT NOT NULL DEFAULT ''",
        "socket_no": "INTEGER NOT NULL DEFAULT 1",
        "amount_yuan": "REAL NOT NULL DEFAULT 1",
        "payment_mode": "TEXT NOT NULL DEFAULT ''",
        "payment_token": "TEXT NOT NULL DEFAULT ''",
        "balance_deducted": "INTEGER NOT NULL DEFAULT 0",
        "balance_refunded": "INTEGER NOT NULL DEFAULT 0",
    }
    rows = conn.execute("PRAGMA table_info(orders)").fetchall()
    existing = {row["name"] for row in rows}
    for column_name, column_type in required_columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")


def ensure_recharge_request_columns(conn: sqlite3.Connection) -> None:
    required_columns = {
        "payment_method": "TEXT NOT NULL DEFAULT ''",
    }
    rows = conn.execute("PRAGMA table_info(recharge_requests)").fetchall()
    existing = {row["name"] for row in rows}
    for column_name, column_type in required_columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE recharge_requests ADD COLUMN {column_name} {column_type}")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    created_at = str(row["created_at"] or "")
    amount_yuan = float(row["amount_yuan"] or 0)
    estimated_finish = estimated_finish_at(created_at, amount_yuan)
    charge_state, charge_finished_at = charge_state_for_order(str(row["status"] or ""), estimated_finish)
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "phone": row["phone"],
        "station_name": row["station_name"],
        "device_code": row["device_code"],
        "socket_no": row["socket_no"],
        "amount_yuan": amount_yuan,
        "remark": row["remark"],
        "status": row["status"],
        "result_message": clean_result_message(row["result_message"], str(row["status"] or "")),
        "vendor_order_id": row["vendor_order_id"],
        "created_at": created_at,
        "updated_at": row["updated_at"],
        "estimated_minutes": approx_charge_minutes(amount_yuan),
        "estimated_finish_at": estimated_finish,
        "charge_state": charge_state,
        "charge_finished_at": charge_finished_at,
        "charge_stop_reason": charge_stop_reason_from_message(row["result_message"]),
        "service_fee_yuan": SERVICE_FEE_YUAN,
        "total_cost_yuan": total_cost_yuan(amount_yuan),
    }


class OrderCreate(BaseModel):
    station_id: str = Field(default="", max_length=64)
    station_name: str = Field(default="", max_length=120)
    device_code: str = Field(min_length=1, max_length=64)
    socket_no: int = Field(ge=1, le=20)
    amount_yuan: float = Field(gt=0, le=100)
    remark: str = Field(default="", max_length=200)
    payment_token: str = Field(default="", max_length=200)


class OrderView(BaseModel):
    id: int
    user_id: int | None = None
    phone: str
    station_name: str
    device_code: str
    socket_no: int
    amount_yuan: float
    remark: str
    status: str
    result_message: str
    vendor_order_id: str
    created_at: str
    updated_at: str
    estimated_minutes: int = 0
    estimated_finish_at: str = ""
    charge_state: str = ""
    charge_finished_at: str = ""
    charge_stop_reason: str = ""
    service_fee_yuan: float = 0
    total_cost_yuan: float = 0


class UserRegister(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class UserLogin(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class UserView(BaseModel):
    id: int
    phone: str
    balance_yuan: float = 0
    created_at: str


class AuthResponse(BaseModel):
    token: str
    user: UserView


class BalanceAdjustPayload(BaseModel):
    delta_yuan: float = Field(ge=-10000, le=10000)
    reason: str = Field(default="", max_length=200)


class PasswordResetPayload(BaseModel):
    new_password: str = Field(min_length=6, max_length=64)


class PaymentIssuePayload(BaseModel):
    user_id: int
    amount_yuan: float = Field(gt=0, le=10000)


class AgentCompletePayload(BaseModel):
    success: bool
    message: str = Field(default="", max_length=500)
    vendor_order_id: str = Field(default="", max_length=120)


class AgentHeartbeatPayload(BaseModel):
    agent_name: str = Field(min_length=1, max_length=120)
    machine_name: str = Field(default="", max_length=120)
    runner_command: str = Field(default="", max_length=300)
    status: str = Field(default="idle", max_length=32)
    current_order_id: int | None = None


class AgentSocketOverviewPayload(BaseModel):
    agent_name: str = Field(min_length=1, max_length=120)
    captured_at: str = Field(default="")
    snapshot: list[dict[str, Any]] = Field(default_factory=list)


class StationView(BaseModel):
    id: str
    name: str
    region: str = ""
    device_code: str
    socket_count: int = 10
    address: str = ""
    disabled_sockets: list[int] = Field(default_factory=list)
    order_enabled: bool = True
    plot_id: int | None = None
    gps_id: int | None = None
    agent_id: int | None = None
    pid: int | None = None
    device_ck: str = ""
    source: str = ""


class StationPublicView(BaseModel):
    id: str
    name: str
    region: str = ""
    device_code: str
    socket_count: int = 10
    address: str = ""
    disabled_sockets: list[int] = Field(default_factory=list)
    order_enabled: bool = True
    plot_id: int | None = None
    gps_id: int | None = None
    agent_id: int | None = None
    pid: int | None = None
    source: str = ""


class RechargeRequestCreate(BaseModel):
    amount_yuan: float = Field(gt=0, le=10000)
    payment_method: str = Field(default="wechat_manual", max_length=40)
    note: str = Field(default="", max_length=200)


class RechargeRequestReview(BaseModel):
    review_note: str = Field(default="", max_length=200)


class RechargeRequestView(BaseModel):
    id: int
    user_id: int
    phone: str
    amount_yuan: float
    bonus_yuan: float = 0
    credited_yuan: float = 0
    payment_method: str = ""
    status: str
    note: str
    created_at: str
    updated_at: str
    reviewed_at: str = ""
    review_note: str = ""


class PaymentCreate(BaseModel):
    station_name: str = Field(default="", max_length=120)
    device_code: str = Field(min_length=1, max_length=64)
    socket_no: int = Field(ge=1, le=20)
    amount_yuan: float = Field(gt=0, le=100)
    remark: str = Field(default="", max_length=200)
    pay_type: int = Field(default=2, ge=1, le=2)  # 1=支付宝 2=微信


def codepay_sign(params: dict[str, str]) -> str:
    """码支付签名：按key排序拼接后加key，md5"""
    sorted_str = "&".join(f"{k}={params[k]}" for k in sorted(params))
    raw = sorted_str + "&key=" + CODEPAY_KEY
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def codepay_create(
    *,
    out_trade_no: str,
    money: str,
    pay_type: int,
    notify_url: str,
    return_url: str,
) -> dict[str, Any]:
    params = {
        "id": CODEPAY_ID,
        "type": str(pay_type),
        "out_trade_no": out_trade_no,
        "money": money,
        "name": "充电服务费",
        "notify_url": notify_url,
        "return_url": return_url,
    }
    params["sign"] = codepay_sign(params)
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        f"{CODEPAY_API}/pay/index.php",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def codepay_verify_notify(params: dict[str, str]) -> bool:
    """验证码支付回调签名"""
    received_sign = params.pop("sign", "")
    expected = codepay_sign({k: v for k, v in params.items() if v})
    return secrets.compare_digest(received_sign, expected)


class ChargerGateway:
    """
    Gateway adapter for official charger API.

    gateway_config.json example:
    {
      "mode": "mock",
      "base_url": "https://official-provider.example.com",
      "start_path": "/api/start-charge",
      "token": "your-official-token",
      "timeout_seconds": 15
    }

    mode=mock:
      - no external API call, always succeeds after a short wait
    mode=official:
      - POST {base_url}{start_path} with official token and order payload
    """

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.mode = "mock"
        self.base_url = ""
        self.start_path = "/api/start-charge"
        self.token = ""
        self.headers: dict[str, str] = {}
        self.extra_payload: dict[str, Any] = {}
        self.success_field = "success"
        self.success_expected: Any = True
        self.message_field = "message"
        self.order_id_field = "order_id"
        self.timeout_seconds = 15
        self.reload()

    def reload(self) -> None:
        if not self.config_path.exists():
            self._write_default_config()

        raw = self.config_path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        self.mode = str(data.get("mode", "mock")).strip().lower() or "mock"
        self.base_url = str(data.get("base_url", "")).strip().rstrip("/")
        self.start_path = str(data.get("start_path", "/api/start-charge")).strip() or "/api/start-charge"
        self.token = str(data.get("token", "")).strip()
        self.headers = data.get("headers", {}) if isinstance(data.get("headers", {}), dict) else {}
        self.extra_payload = (
            data.get("extra_payload", {}) if isinstance(data.get("extra_payload", {}), dict) else {}
        )
        self.success_field = str(data.get("success_field", "success")).strip() or "success"
        self.success_expected = data.get("success_expected", True)
        self.message_field = str(data.get("message_field", "message")).strip() or "message"
        self.order_id_field = str(data.get("order_id_field", "order_id")).strip() or "order_id"
        self.timeout_seconds = int(data.get("timeout_seconds", 15))

    def _write_default_config(self) -> None:
        default_data = {
            "mode": "mock",
            "base_url": "",
            "start_path": "/api/start-charge",
            "token": "",
            "headers": {},
            "extra_payload": {},
            "success_field": "success",
            "success_expected": True,
            "message_field": "message",
            "order_id_field": "order_id",
            "timeout_seconds": 15,
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(default_data, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def start_charge(self, order: sqlite3.Row) -> tuple[bool, str, str]:
        if self.mode == "mock":
            time.sleep(1)
            return True, "mock start success", f"mock-{order['id']}"

        if self.mode != "official":
            return False, f"invalid mode: {self.mode}", ""

        if not self.base_url or not self.token:
            return False, "official mode requires base_url and token", ""

        endpoint = f"{self.base_url}{self.start_path}"
        payload = {
            "station_name": order["station_name"],
            "device_code": order["device_code"],
            "socket_no": order["socket_no"],
            "amount_yuan": order["amount_yuan"],
            "remark": order["remark"],
            "client_order_id": order["id"],
            # Compatibility key, some providers still call it pile_no.
            "pile_no": order["device_code"],
        }
        payload.update(self.extra_payload)
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        headers.update(self.headers)
        req = urllib.request.Request(
            url=endpoint,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="ignore")
            return False, f"http {err.code}: {detail}", ""
        except Exception as err:
            return False, f"request failed: {err}", ""

        success_value = get_nested_value(data, self.success_field, None)
        if self.success_expected is None:
            success = bool(success_value)
        else:
            success = success_value == self.success_expected
        message = str(get_nested_value(data, self.message_field, ""))
        vendor_order_id = str(
            get_nested_value(data, self.order_id_field, get_nested_value(data, "id", ""))
        )

        if not success:
            return False, message or "provider rejected request", vendor_order_id
        return True, message or "start command accepted", vendor_order_id


gateway = ChargerGateway(GATEWAY_CONFIG_PATH)
stop_event = threading.Event()
worker_thread: threading.Thread | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker_thread

    init_db()
    if WORKER_ENABLED and (worker_thread is None or not worker_thread.is_alive()):
        stop_event.clear()
        worker_thread = threading.Thread(target=worker_loop, daemon=True, name="order-worker")
        worker_thread.start()

    try:
        yield
    finally:
        stop_event.set()
        if worker_thread and worker_thread.is_alive():
            worker_thread.join(timeout=3)


app = FastAPI(title="Mobile Charger Order Service", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/admin") else "no-cache"
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' https: data: blob:; "
            "img-src 'self' https: data: blob:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
            "frame-src 'self' https:; "
            "connect-src 'self' https:; "
            "object-src 'none'; base-uri 'self'; form-action 'self' https:;"
        )
    return response


def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_admin_password: str | None = Header(default=None, alias="X-Admin-Password"),
    token: str | None = Query(default=None),
    password: str | None = Query(default=None),
) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="admin token not configured")
    candidate = x_admin_token or token
    if candidate != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")
    if ADMIN_PASSWORD:
        password_candidate = (x_admin_password or password or "").strip()
        if password_candidate != ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="invalid admin password")


def require_agent(
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
    token: str | None = Query(default=None),
) -> None:
    if not AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="agent token not configured")
    candidate = x_agent_token or token
    if candidate != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="invalid agent token")


def require_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> sqlite3.Row:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_session_token:
        token = x_session_token.strip()

    if not token:
        raise HTTPException(status_code=401, detail="login required")

    user = get_user_by_session_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")
    return user


def claim_next_pending_order() -> sqlite3.Row | None:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE status = 'PENDING' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None

        cursor = conn.execute(
            """
            UPDATE orders
            SET status = 'PROCESSING', updated_at = ?
            WHERE id = ? AND status = 'PENDING'
            """,
            (now_iso(), row["id"]),
        )
        conn.commit()
        if cursor.rowcount != 1:
            return None

        return conn.execute("SELECT * FROM orders WHERE id = ?", (row["id"],)).fetchone()


def apply_balance_delta(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    delta_yuan: float,
    reason: str,
) -> float:
    ts = now_iso()
    row = conn.execute("SELECT balance_yuan FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    current = float(row["balance_yuan"] or 0)
    new_balance = current + float(delta_yuan)
    if new_balance < -0.0001:
        raise HTTPException(status_code=400, detail="insufficient balance")
    conn.execute(
        "UPDATE users SET balance_yuan = ?, updated_at = ? WHERE id = ?",
        (new_balance, ts, user_id),
    )
    conn.execute(
        """
        INSERT INTO wallet_ledger (user_id, delta_yuan, balance_after, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, float(delta_yuan), new_balance, reason, ts),
    )
    return new_balance


def payment_token_key(raw_token: str) -> str:
    if PAYMENT_TOKEN_SECRET:
        digest = hashlib.sha256(f"{PAYMENT_TOKEN_SECRET}:{raw_token}".encode("utf-8")).hexdigest()
        return digest
    return raw_token


def issue_payment_token(conn: sqlite3.Connection, user_id: int, amount_yuan: float) -> dict[str, str]:
    raw_token = secrets.token_urlsafe(24)
    token_key = payment_token_key(raw_token)
    created_at = now_iso()
    expires_at = datetime.fromtimestamp(
        datetime.now(UTC).timestamp() + PAYMENT_TOKEN_TTL_SECONDS,
        UTC,
    ).isoformat()
    conn.execute(
        """
        INSERT INTO payment_tokens (token, user_id, amount_yuan, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (token_key, user_id, float(amount_yuan), created_at, expires_at),
    )
    return {"token": raw_token, "expires_at": expires_at}


def load_payment_token(conn: sqlite3.Connection, raw_token: str) -> sqlite3.Row | None:
    token_key = payment_token_key(raw_token)
    return conn.execute(
        """
        SELECT token, user_id, amount_yuan, expires_at, used_at, used_order_id
        FROM payment_tokens
        WHERE token = ?
        """,
        (token_key,),
    ).fetchone()


def validate_payment_token(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    amount_yuan: float,
    raw_token: str,
) -> sqlite3.Row:
    row = load_payment_token(conn, raw_token)
    if row is None:
        raise HTTPException(status_code=400, detail="invalid payment token")
    if int(row["user_id"]) != int(user_id):
        raise HTTPException(status_code=403, detail="payment token does not belong to user")
    if str(row["used_at"] or "").strip():
        raise HTTPException(status_code=409, detail="payment token already used")
    expires_at = parse_iso(str(row["expires_at"] or ""))
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="payment token expired")
    if float(row["amount_yuan"]) + 1e-9 < float(amount_yuan):
        raise HTTPException(status_code=400, detail="payment token amount is insufficient")
    return row


def find_station(station_id: str, device_code: str) -> dict[str, Any] | None:
    station_id = station_id.strip()
    device_code = device_code.strip()
    for station in load_stations():
        if station_id and station["id"] == station_id:
            return station
        if device_code and station["device_code"] == device_code:
            return station
    return None


def validate_station_socket(station: dict[str, Any], socket_no: int) -> None:
    if socket_no < 1 or socket_no > int(station.get("socket_count", 10)):
        raise HTTPException(status_code=422, detail="插座号超出当前站点范围")
    disabled_sockets = {int(value) for value in station.get("disabled_sockets", [])}
    if socket_no in disabled_sockets:
        raise HTTPException(status_code=409, detail=f"{socket_no}号插座故障，请换一个插座")


def recharge_request_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    amount_yuan = float(row["amount_yuan"] or 0)
    bonus_yuan = recharge_bonus_yuan(amount_yuan)
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "phone": str(row["phone"] or ""),
        "amount_yuan": amount_yuan,
        "bonus_yuan": bonus_yuan,
        "credited_yuan": round(amount_yuan + bonus_yuan, 2),
        "payment_method": str(row["payment_method"] or ""),
        "status": str(row["status"] or ""),
        "note": str(row["note"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "reviewed_at": str(row["reviewed_at"] or ""),
        "review_note": str(row["review_note"] or ""),
    }


def filter_socket_overview_by_region(
    snapshot: list[dict[str, Any]],
    region_key: str | None = None,
) -> list[dict[str, Any]]:
    selected_region_key = overview_region_key(region_key) if region_key else ""
    if not selected_region_key:
        return snapshot
    return [
        region
        for region in snapshot
        if overview_region_key(region.get("region", "")) == selected_region_key
    ]


def socket_state_snapshot(region_key: str | None = None) -> list[dict[str, Any]]:
    pushed_snapshot = latest_agent_socket_overview()
    if pushed_snapshot is not None:
        return filter_socket_overview_by_region(pushed_snapshot, region_key)
    return compute_live_socket_state_snapshot(region_key=region_key)


def create_recharge_request(
    conn: sqlite3.Connection,
    *,
    user: sqlite3.Row,
    amount_yuan: float,
    payment_method: str,
    note: str,
) -> sqlite3.Row:
    ts = now_iso()
    cursor = conn.execute(
        """
        INSERT INTO recharge_requests (user_id, phone, amount_yuan, payment_method, status, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?)
        """,
        (
            int(user["id"]),
            str(user["phone"] or ""),
            float(amount_yuan),
            payment_method.strip(),
            note.strip(),
            ts,
            ts,
        ),
    )
    row = conn.execute("SELECT * FROM recharge_requests WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="failed to create recharge request")
    return row


def review_recharge_request(
    conn: sqlite3.Connection,
    *,
    request_id: int,
    approve: bool,
    review_note: str,
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM recharge_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="recharge request not found")
    if str(row["status"] or "") != "PENDING":
        raise HTTPException(status_code=409, detail="recharge request already reviewed")

    ts = now_iso()
    next_status = "APPROVED" if approve else "REJECTED"
    conn.execute(
        """
        UPDATE recharge_requests
        SET status = ?, updated_at = ?, reviewed_at = ?, review_note = ?
        WHERE id = ?
        """,
        (next_status, ts, ts, review_note.strip(), request_id),
    )
    if approve:
        amount_yuan = float(row["amount_yuan"] or 0)
        bonus_yuan = recharge_bonus_yuan(amount_yuan)
        apply_balance_delta(
            conn,
            user_id=int(row["user_id"]),
            delta_yuan=round(amount_yuan + bonus_yuan, 2),
            reason=f"recharge_request:{request_id}",
        )
        if bonus_yuan > 0:
            merged_note = review_note.strip()
            bonus_note = f"充值赠送 ¥{bonus_yuan:.2f}"
            conn.execute(
                "UPDATE recharge_requests SET review_note = ? WHERE id = ?",
                ((f"{merged_note}；{bonus_note}" if merged_note else bonus_note), request_id),
            )
    updated = conn.execute("SELECT * FROM recharge_requests WHERE id = ?", (request_id,)).fetchone()
    if updated is None:
        raise HTTPException(status_code=500, detail="failed to update recharge request")
    return updated


def update_order_result(order_id: int, status: str, message: str, vendor_order_id: str = "") -> None:
    message = clean_result_message(message, status)
    with db_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT id, user_id, amount_yuan, payment_mode, balance_deducted, balance_refunded
            FROM orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return

        conn.execute(
            """
            UPDATE orders
            SET status = ?, result_message = ?, vendor_order_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, message, vendor_order_id, now_iso(), order_id),
        )

        if (
            status == "SUCCESS"
            and row["payment_mode"] == "balance"
            and int(row["balance_deducted"] or 0) == 0
        ):
            charge_amount = total_cost_yuan(float(row["amount_yuan"] or 0))
            try:
                apply_balance_delta(
                    conn,
                    user_id=int(row["user_id"]),
                    delta_yuan=-charge_amount,
                    reason=f"order_success_charge:{order_id}",
                )
                conn.execute(
                    "UPDATE orders SET balance_deducted = 1 WHERE id = ?",
                    (order_id,),
                )
            except HTTPException as err:
                if getattr(err, "status_code", 0) == 400:
                    message = f"{message}；充电成功，但余额扣款失败，请联系管理员处理".strip("；")
                    conn.execute(
                        """
                        UPDATE orders
                        SET result_message = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (message, now_iso(), order_id),
                    )
                else:
                    raise

        if (
            status == "FAILED"
            and BALANCE_REFUND_ON_FAIL
            and row["payment_mode"] == "balance"
            and int(row["balance_deducted"] or 0) == 1
            and int(row["balance_refunded"] or 0) == 0
        ):
            refund_amount = total_cost_yuan(float(row["amount_yuan"] or 0))
            apply_balance_delta(
                conn,
                user_id=int(row["user_id"]),
                delta_yuan=refund_amount,
                reason=f"order_failed_refund:{order_id}",
            )
            conn.execute(
                "UPDATE orders SET balance_refunded = 1 WHERE id = ?",
                (order_id,),
            )

        conn.commit()


def upsert_agent_runtime(payload: AgentHeartbeatPayload) -> None:
    ts = now_iso()
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_runtime
                (agent_name, machine_name, runner_command, status, current_order_id, heartbeat_at, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_name) DO UPDATE SET
                machine_name = excluded.machine_name,
                runner_command = excluded.runner_command,
                status = excluded.status,
                current_order_id = excluded.current_order_id,
                heartbeat_at = excluded.heartbeat_at,
                updated_at = excluded.updated_at
            """,
            (
                payload.agent_name.strip(),
                payload.machine_name.strip(),
                payload.runner_command.strip(),
                payload.status.strip().upper(),
                payload.current_order_id,
                ts,
                ts,
            ),
        )
        conn.commit()


def upsert_agent_socket_overview(payload: AgentSocketOverviewPayload) -> None:
    ts = now_iso()
    captured_at = payload.captured_at.strip() or ts
    snapshot_json = json.dumps(payload.snapshot, ensure_ascii=False)
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_socket_overview (agent_name, snapshot_json, captured_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(agent_name) DO UPDATE SET
                snapshot_json = excluded.snapshot_json,
                captured_at = excluded.captured_at,
                updated_at = excluded.updated_at
            """,
            (
                payload.agent_name.strip(),
                snapshot_json,
                captured_at,
                ts,
            ),
        )
        conn.commit()


def latest_agent_socket_overview() -> list[dict[str, Any]] | None:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT agent_name, snapshot_json, captured_at, updated_at
            FROM agent_socket_overview
            ORDER BY captured_at DESC, updated_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    captured_at = parse_iso(str(row["captured_at"] or ""))
    if captured_at is None:
        return None
    if (datetime.now(UTC) - captured_at).total_seconds() > AGENT_SOCKET_OVERVIEW_EXPIRE_SECONDS:
        return None
    try:
        snapshot = json.loads(str(row["snapshot_json"] or "[]"))
    except Exception:
        return None
    return snapshot if isinstance(snapshot, list) else None


def get_agent_runtime_status() -> dict[str, Any]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT agent_name, machine_name, runner_command, status, current_order_id, heartbeat_at
            FROM agent_runtime
            ORDER BY heartbeat_at DESC, updated_at DESC
            """
        ).fetchall()

    latest = rows[0] if rows else None
    now = datetime.now(UTC)
    active_rows = []
    for row in rows:
        heartbeat_at = parse_iso(str(row["heartbeat_at"] or ""))
        if heartbeat_at is None:
            continue
        if (now - heartbeat_at).total_seconds() <= AGENT_HEARTBEAT_EXPIRE_SECONDS:
            active_rows.append(row)

    return {
        "agent_online": bool(active_rows),
        "active_agents": len(active_rows),
        "agent_last_seen_at": str(latest["heartbeat_at"]) if latest else "",
        "agent_name": str(latest["agent_name"]) if latest else "",
        "agent_status": str(latest["status"]) if latest else "",
        "agent_current_order_id": latest["current_order_id"] if latest else None,
    }


def get_service_status() -> dict[str, Any]:
    worker_alive = bool(worker_thread and worker_thread.is_alive())
    service_mode = "local_worker" if WORKER_ENABLED else "cloud_agent"
    agent_status = get_agent_runtime_status()
    live_processor_online = worker_alive if WORKER_ENABLED else agent_status["agent_online"]
    allow_order_submission = not REQUIRE_AGENT_ONLINE_FOR_ORDERS or live_processor_online
    qr_name = "wechat_qr.png"
    qr_path = WEB_ASSETS_DIR / qr_name
    payment_qr_url = f"/assets/{qr_name}" if qr_path.exists() else ""
    manual_recharge_enabled = bool(payment_qr_url)
    return {
        "service_mode": service_mode,
        "worker_enabled": WORKER_ENABLED,
        "worker_alive": worker_alive,
        "require_agent_online_for_orders": REQUIRE_AGENT_ONLINE_FOR_ORDERS,
        "accepting_orders": live_processor_online,
        "allow_order_submission": allow_order_submission,
        "payment_mode": PAYMENT_MODE,
        "payment_bridge_url": PAYMENT_BRIDGE_URL,
        "socket_overview_bridge_url": SOCKET_OVERVIEW_BRIDGE_URL,
        "payment_token_required": PAYMENT_MODE == "token",
        "balance_enabled": PAYMENT_MODE == "balance",
        "balance_refund_on_fail": BALANCE_REFUND_ON_FAIL,
        "payment_qr_url": payment_qr_url,
        "manual_recharge_enabled": manual_recharge_enabled,
        "manual_payment_contact": MANUAL_PAYMENT_CONTACT,
        "manual_payment_instructions": MANUAL_PAYMENT_INSTRUCTIONS or DEFAULT_RECHARGE_QR_NOTE,
        "recharge_qr_note": MANUAL_PAYMENT_INSTRUCTIONS or DEFAULT_RECHARGE_QR_NOTE,
        **agent_status,
    }


def worker_loop() -> None:
    while not stop_event.is_set():
        order = claim_next_pending_order()
        if order is None:
            stop_event.wait(POLL_INTERVAL_SECONDS)
            continue

        ok, message, vendor_order_id = gateway.start_charge(order)
        if ok:
            update_order_result(order["id"], "SUCCESS", message, vendor_order_id)
        else:
            update_order_result(order["id"], "FAILED", message, vendor_order_id)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    if not HTML_PATH.exists():
        return "<h3>mobile_order.html not found</h3>"
    return HTML_PATH.read_text(encoding="utf-8")


@app.get("/assets/{name}")
def assets(name: str) -> FileResponse:
    # Basic allowlist to avoid path traversal and serving arbitrary files.
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404, detail="asset not found")
    if name.lower() != "wechat_qr.png":
        raise HTTPException(status_code=404, detail="asset not found")

    file_path = WEB_ASSETS_DIR / name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path=file_path)


@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin_page(token: str | None = Query(default=None)) -> str:
    if not ADMIN_HTML_PATH.exists():
        return "<h3>admin_orders.html not found</h3>"
    content = ADMIN_HTML_PATH.read_text(encoding="utf-8")
    token_json = json.dumps(token or "", ensure_ascii=False)
    return content.replace('"__ADMIN_TOKEN__"', token_json)


@app.get("/api/health")
def health() -> dict[str, Any]:
    service_status = get_service_status()
    return {
        "ok": True,
        "gateway_mode": gateway.mode,
        "time": now_iso(),
        **service_status,
    }


@app.get("/api/stations", response_model=list[StationPublicView])
def list_stations(
    q: str | None = Query(default=None, max_length=100),
    region: str | None = Query(default=None, max_length=100),
) -> list[StationPublicView]:
    stations = load_stations()
    if region:
        region_name = region.strip().lower()
        stations = [station for station in stations if region_name in station["region"].lower()]
    if q:
        query = q.strip().lower()
        stations = [
            station
            for station in stations
            if query in station["name"].lower() or query in station["device_code"].lower()
        ]
    return [StationPublicView(**station) for station in stations[:200]]


@app.get("/api/socket-overview")
def get_socket_overview(region: str | None = Query(default=None, max_length=50)) -> list[dict[str, Any]]:
    return socket_state_snapshot(region_key=region)


@app.post("/api/auth/register", response_model=AuthResponse)
def register(payload: UserRegister) -> AuthResponse:
    phone = normalize_phone(payload.phone)
    password_hash = hash_password(payload.password)
    ts = now_iso()

    with db_connect() as conn:
        exists = conn.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
        if exists is not None:
            raise HTTPException(status_code=409, detail="phone already registered")

        cursor = conn.execute(
            """
            INSERT INTO users (phone, password_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (phone, password_hash, ts, ts),
        )
        conn.commit()
        user = conn.execute(
            "SELECT id, phone, balance_yuan, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    if user is None:
        raise HTTPException(status_code=500, detail="failed to create user")

    token = create_session(user["id"])
    return AuthResponse(token=token, user=UserView(**dict(user)))


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: UserLogin) -> AuthResponse:
    phone = normalize_phone(payload.phone)
    with db_connect() as conn:
        user = conn.execute(
            "SELECT id, phone, password_hash, balance_yuan, created_at FROM users WHERE phone = ?",
            (phone,),
        ).fetchone()

    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="phone or password is incorrect")

    token = create_session(user["id"])
    return AuthResponse(
        token=token,
        user=UserView(
            id=user["id"],
            phone=user["phone"],
            balance_yuan=float(user["balance_yuan"] or 0),
            created_at=user["created_at"],
        ),
    )


@app.post("/api/auth/logout")
def logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_session_token:
        token = x_session_token.strip()

    if token:
        with db_connect() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()
    return {"ok": True}


@app.get("/api/me", response_model=UserView)
def me(user: sqlite3.Row = Depends(require_user)) -> UserView:
    return UserView(
        id=user["id"],
        phone=user["phone"],
        balance_yuan=float(user["balance_yuan"] or 0),
        created_at=user["created_at"],
    )


@app.get("/api/me/orders", response_model=list[OrderView])
def my_orders(
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(require_user),
) -> list[OrderView]:
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()
    items = [row_to_dict(row) for row in rows]
    member_id = configured_member_id()
    if member_id:
        try:
            using_orders, _ = fetch_using_orders(member_id)
        except Exception:
            using_orders = {}
        for item in items:
            key = (str(item.get("device_code", "")), int(item.get("socket_no", 0) or 0))
            if key in using_orders and str(item.get("status", "")).upper() == "SUCCESS":
                item["charge_state"] = "CHARGING_LIVE"
                item["charge_finished_at"] = ""
    return [OrderView(**item) for item in items]


@app.get("/api/me/recharge-requests", response_model=list[RechargeRequestView])
def my_recharge_requests(
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(require_user),
) -> list[RechargeRequestView]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM recharge_requests
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user["id"], limit),
        ).fetchall()
    return [RechargeRequestView(**recharge_request_row_to_dict(row)) for row in rows]


@app.post("/api/me/recharge-requests", response_model=RechargeRequestView)
def create_my_recharge_request(
    payload: RechargeRequestCreate,
    user: sqlite3.Row = Depends(require_user),
) -> RechargeRequestView:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = create_recharge_request(
                conn,
                user=user,
                amount_yuan=float(payload.amount_yuan),
                payment_method=payload.payment_method,
                note=payload.note,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return RechargeRequestView(**recharge_request_row_to_dict(row))


@app.post("/api/orders", response_model=OrderView)
def create_order(payload: OrderCreate, user: sqlite3.Row = Depends(require_user)) -> OrderView:
    service_status = get_service_status()
    if REQUIRE_AGENT_ONLINE_FOR_ORDERS and not service_status["accepting_orders"]:
        raise HTTPException(status_code=503, detail="接单电脑离线，暂时无法下单")

    ts = now_iso()
    phone = user["phone"]
    payment_mode = PAYMENT_MODE
    payment_token = payload.payment_token.strip()
    balance_deducted = 0
    total_cost = total_cost_yuan(float(payload.amount_yuan))
    station = find_station(payload.station_id, payload.device_code)
    if station is not None:
        validate_station_socket(station, int(payload.socket_no))
        station_name = station["name"]
        device_code = station["device_code"]
        if not device_code:
            raise HTTPException(status_code=422, detail="该站点尚未录入设备编码，暂不可下单")
    else:
        station_name = payload.station_name.strip()
        device_code = payload.device_code.strip()
        if not device_code:
            raise HTTPException(status_code=422, detail="设备编码不能为空")

    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            if payment_mode == "balance":
                balance_row = conn.execute(
                    "SELECT balance_yuan FROM users WHERE id = ?",
                    (user["id"],),
                ).fetchone()
                if balance_row is None:
                    raise HTTPException(status_code=404, detail="user not found")
                current_balance = float(balance_row["balance_yuan"] or 0)
                if current_balance + 1e-9 < total_cost:
                    raise HTTPException(status_code=402, detail="余额不足，请先充值")
            elif payment_mode == "token":
                if not payment_token:
                    raise HTTPException(status_code=400, detail="支付码不能为空")
                validate_payment_token(
                    conn,
                    user_id=int(user["id"]),
                    amount_yuan=total_cost,
                    raw_token=payment_token,
                )

            cursor = conn.execute(
                """
                INSERT INTO orders
                    (
                        user_id, pile_no, phone, minutes,
                        station_name, device_code, socket_no, amount_yuan,
                        remark, status, result_message, vendor_order_id,
                        payment_mode, payment_token, balance_deducted, balance_refunded,
                        created_at, updated_at
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', '', '',
                     ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    device_code,
                    phone,
                    0,
                    station_name,
                    device_code,
                    payload.socket_no,
                    payload.amount_yuan,
                    payload.remark,
                    payment_mode,
                    payment_token,
                    balance_deducted,
                    0,
                    ts,
                    ts,
                ),
            )
            order_id = int(cursor.lastrowid)

            if payment_mode == "token":
                token_key = payment_token_key(payment_token)
                updated = conn.execute(
                    """
                    UPDATE payment_tokens
                    SET used_at = ?, used_order_id = ?
                    WHERE token = ? AND used_at = ''
                    """,
                    (ts, order_id, token_key),
                ).rowcount
                if updated != 1:
                    raise HTTPException(status_code=409, detail="支付码已被使用")

            conn.commit()
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        except Exception:
            conn.rollback()
            raise

    if row is None:
        raise HTTPException(status_code=500, detail="failed to create order")
    return OrderView(**row_to_dict(row))


@app.get("/api/orders/{order_id}", response_model=OrderView)
def get_order(order_id: int, user: sqlite3.Row = Depends(require_user)) -> OrderView:
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    if row["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="forbidden")
    return OrderView(**row_to_dict(row))


@app.get("/api/orders", response_model=list[OrderView], dependencies=[Depends(require_admin)])
def list_orders(
    limit: int = Query(default=20, ge=1, le=500),
    status: str | None = Query(default=None),
    device_code: str | None = Query(default=None),
) -> list[OrderView]:
    clauses: list[str] = []
    params: list[Any] = []

    if status:
        clauses.append("status = ?")
        params.append(status.strip().upper())
    if device_code:
        clauses.append("device_code = ?")
        params.append(device_code.strip())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with db_connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM orders {where_sql} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
    return [OrderView(**row_to_dict(row)) for row in rows]


@app.get("/api/admin/users", response_model=list[UserView], dependencies=[Depends(require_admin)])
def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    q: str | None = Query(default=None, max_length=50),
) -> list[UserView]:
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append("phone LIKE ?")
        params.append(f"%{q.strip()}%")
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, phone, balance_yuan, created_at
            FROM users
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        UserView(
            id=row["id"],
            phone=row["phone"],
            balance_yuan=float(row["balance_yuan"] or 0),
            created_at=row["created_at"],
        )
        for row in rows
    ]


@app.post("/api/admin/users/{user_id}/balance", dependencies=[Depends(require_admin)])
def adjust_user_balance(user_id: int, payload: BalanceAdjustPayload) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            new_balance = apply_balance_delta(
                conn,
                user_id=user_id,
                delta_yuan=float(payload.delta_yuan),
                reason=payload.reason or "admin_adjust",
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True, "user_id": user_id, "balance_yuan": new_balance}


@app.post("/api/admin/users/{user_id}/password", dependencies=[Depends(require_admin)])
def reset_user_password(user_id: int, payload: PasswordResetPayload) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT id, phone FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(payload.new_password), now_iso(), user_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True, "user_id": user_id, "phone": str(user["phone"] or "")}


@app.get("/api/admin/recharge-requests", dependencies=[Depends(require_admin)])
def admin_list_recharge_requests(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None, max_length=20),
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status.strip().upper())
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM recharge_requests
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [recharge_request_row_to_dict(row) for row in rows]


@app.post("/api/admin/recharge-requests/{request_id}/approve", dependencies=[Depends(require_admin)])
def admin_approve_recharge_request(request_id: int, payload: RechargeRequestReview) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = review_recharge_request(
                conn,
                request_id=request_id,
                approve=True,
                review_note=payload.review_note,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True, "request": recharge_request_row_to_dict(row)}


@app.post("/api/admin/recharge-requests/{request_id}/reject", dependencies=[Depends(require_admin)])
def admin_reject_recharge_request(request_id: int, payload: RechargeRequestReview) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = review_recharge_request(
                conn,
                request_id=request_id,
                approve=False,
                review_note=payload.review_note,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True, "request": recharge_request_row_to_dict(row)}


@app.post("/api/admin/payments/issue", dependencies=[Depends(require_admin)])
def admin_issue_payment_token(payload: PaymentIssuePayload) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            token_data = issue_payment_token(conn, payload.user_id, payload.amount_yuan)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True, **token_data, "user_id": payload.user_id, "amount_yuan": payload.amount_yuan}


@app.post("/api/admin/reload-gateway", dependencies=[Depends(require_admin)])
def reload_gateway() -> dict[str, Any]:
    gateway.reload()
    return {"ok": True, "mode": gateway.mode}


@app.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats() -> dict[str, Any]:
    with db_connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'PENDING'").fetchone()[0]
        processing = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'PROCESSING'").fetchone()[0]
        success = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'SUCCESS'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'FAILED'").fetchone()[0]
        recharge_pending = conn.execute(
            "SELECT COUNT(*) FROM recharge_requests WHERE status = 'PENDING'"
        ).fetchone()[0]
    return {
        "ok": True,
        "gateway_mode": gateway.mode,
        "total": total,
        "pending": pending,
        "processing": processing,
        "success": success,
        "failed": failed,
        "recharge_pending": recharge_pending,
        **get_service_status(),
    }


@app.get("/api/admin/realtime-snapshot-config", dependencies=[Depends(require_admin)])
def admin_realtime_snapshot_config() -> dict[str, Any]:
    stations = load_stations()
    return {
        "ok": True,
        "time": now_iso(),
        "member_id": configured_member_id(),
        "stations": [
            {
                "id": station.get("id", ""),
                "name": station.get("name", ""),
                "region": station.get("region", ""),
                "device_code": station.get("device_code", ""),
                "socket_count": int(station.get("socket_count", 10) or 10),
                "disabled_sockets": list(station.get("disabled_sockets", []) or []),
                "device_ck": station.get("device_ck", ""),
            }
            for station in stations
        ],
    }


@app.post("/api/admin/orders/{order_id}/retry", dependencies=[Depends(require_admin)])
def retry_order(order_id: int) -> dict[str, Any]:
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="order not found")

        conn.execute(
            """
            UPDATE orders
            SET status = 'PENDING', result_message = '', vendor_order_id = '', updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), order_id),
        )
        conn.commit()
    return {"ok": True, "id": order_id, "status": "PENDING"}


@app.post("/api/agent/orders/claim", dependencies=[Depends(require_agent)])
def agent_claim_order() -> dict[str, Any]:
    order = claim_next_pending_order()
    if order is None:
        return {"ok": True, "order": None}
    return {"ok": True, "order": row_to_dict(order)}


@app.post("/api/agent/heartbeat", dependencies=[Depends(require_agent)])
def agent_heartbeat(payload: AgentHeartbeatPayload) -> dict[str, Any]:
    upsert_agent_runtime(payload)
    return {
        "ok": True,
        "agent_name": payload.agent_name,
        "agent_online": True,
        "heartbeat_at": now_iso(),
    }


@app.post("/api/agent/socket-overview", dependencies=[Depends(require_agent)])
def agent_socket_overview(payload: AgentSocketOverviewPayload) -> dict[str, Any]:
    upsert_agent_socket_overview(payload)
    return {
        "ok": True,
        "agent_name": payload.agent_name,
        "captured_at": payload.captured_at or now_iso(),
        "regions": len(payload.snapshot),
    }


@app.post("/api/agent/orders/{order_id}/complete", dependencies=[Depends(require_agent)])
def agent_complete_order(order_id: int, payload: AgentCompletePayload) -> dict[str, Any]:
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")

    status = "SUCCESS" if payload.success else "FAILED"
    update_order_result(order_id, status, payload.message, payload.vendor_order_id)
    return {
        "ok": True,
        "id": order_id,
        "status": status,
        "message": payload.message,
        "vendor_order_id": payload.vendor_order_id,
    }


# ── 码支付路由 ────────────────────────────────────────────────

@app.post("/api/payment/create", response_model=dict)
def payment_create(payload: PaymentCreate, user: sqlite3.Row = Depends(require_user)) -> dict[str, Any]:
    """创建码支付订单，返回支付二维码URL"""
    if not CODEPAY_ENABLED:
        raise HTTPException(status_code=503, detail="支付功能未启用")

    pay_id = secrets.token_urlsafe(16)
    ts = now_iso()
    expires_at = datetime.fromtimestamp(
        datetime.now(UTC).timestamp() + 600, UTC
    ).isoformat()

    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO pending_payments
              (id, user_id, station_name, device_code, socket_no, amount_yuan, remark,
               service_fee, pay_type, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                pay_id, user["id"], payload.station_name, payload.device_code,
                payload.socket_no, payload.amount_yuan, payload.remark,
                SERVICE_FEE_YUAN, payload.pay_type, ts, expires_at,
            ),
        )
        conn.commit()

    notify_url = f"https://icenorth.pythonanywhere.com/api/payment/notify"
    return_url = f"https://icenorth.pythonanywhere.com/"

    try:
        result = codepay_create(
            out_trade_no=pay_id,
            money=f"{SERVICE_FEE_YUAN:.2f}",
            pay_type=payload.pay_type,
            notify_url=notify_url,
            return_url=return_url,
        )
    except urllib.error.URLError:
        raise HTTPException(status_code=503, detail="支付服务当前不可用，请联系管理员切换支付方式")
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"支付接口错误: {err}")

    if str(result.get("code", "")) != "1":
        raise HTTPException(status_code=502, detail=result.get("msg", "支付创建失败"))

    return {
        "ok": True,
        "pay_id": pay_id,
        "qrcode": result.get("qrcode", ""),
        "pay_url": result.get("pay_url", ""),
        "amount": SERVICE_FEE_YUAN,
        "expires_at": expires_at,
    }


@app.get("/api/payment/status/{pay_id}")
def payment_status(pay_id: str, user: sqlite3.Row = Depends(require_user)) -> dict[str, Any]:
    """轮询支付状态"""
    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_payments WHERE id = ? AND user_id = ?",
            (pay_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="支付订单不存在")
    return {
        "ok": True,
        "status": row["status"],
        "charge_order_id": row["charge_order_id"],
        "paid_at": row["paid_at"],
    }


@app.post("/api/payment/notify")
async def payment_notify(request) -> dict[str, Any]:
    """码支付异步回调（免鉴权）"""
    from fastapi import Request
    body = await request.body()
    params = dict(urllib.parse.parse_qsl(body.decode("utf-8")))

    if not codepay_verify_notify(dict(params)):
        return {"code": 0, "msg": "sign error"}

    pay_id = params.get("out_trade_no", "")
    trade_no = params.get("trade_no", "")
    trade_status = params.get("trade_status", "")

    if trade_status != "TRADE_SUCCESS":
        return {"code": 1, "msg": "ok"}

    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_payments WHERE id = ? AND status = 'PENDING'",
            (pay_id,),
        ).fetchone()
        if row is None:
            return {"code": 1, "msg": "ok"}

        ts = now_iso()
        conn.execute(
            "UPDATE pending_payments SET status='PAID', codepay_order_no=?, paid_at=? WHERE id=?",
            (trade_no, ts, pay_id),
        )
        conn.commit()

        # 创建充电订单
        try:
            cursor = conn.execute(
                """
                INSERT INTO orders
                  (user_id, pile_no, phone, minutes, station_name, device_code, socket_no,
                   amount_yuan, remark, payment_mode, payment_token, balance_deducted,
                   balance_refunded, status, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, 'codepay', ?, 0, 0, 'PENDING', ?, ?)
                """,
                (
                    row["user_id"], row["device_code"],
                    str(row["user_id"]),
                    row["station_name"], row["device_code"],
                    row["socket_no"], row["amount_yuan"],
                    row["remark"], pay_id, ts, ts,
                ),
            )
            charge_order_id = cursor.lastrowid
            conn.execute(
                "UPDATE pending_payments SET charge_order_id=? WHERE id=?",
                (charge_order_id, pay_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()

    return {"code": 1, "msg": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
