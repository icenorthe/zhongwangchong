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
from datetime import UTC, datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

try:
    from services.project_paths import CONFIG_DIR, RUNTIME_DIR, WEB_ASSETS_DIR
    from services.realtime_http import post_form_json as realtime_post_form_json
    from services.station_config import load_station_source_items
except ImportError:
    from .project_paths import CONFIG_DIR, RUNTIME_DIR, WEB_ASSETS_DIR
    from .realtime_http import post_form_json as realtime_post_form_json
    from .station_config import load_station_source_items

DB_PATH = RUNTIME_DIR / "orders.db"
HTML_PATH = WEB_ASSETS_DIR / "mobile_order.html"
ADMIN_HTML_PATH = WEB_ASSETS_DIR / "admin_orders.html"
ADMIN_USERS_HTML_PATH = WEB_ASSETS_DIR / "admin_users.html"
GATEWAY_CONFIG_PATH = CONFIG_DIR / "gateway_config.json"
CHARGE_API_CONFIG_PATH = CONFIG_DIR / "charge_api_config.json"
STATION_PLACEHOLDERS_PATH = CONFIG_DIR / "station_placeholders.json"
POLL_INTERVAL_SECONDS = float(os.getenv("ORDER_POLL_INTERVAL_SECONDS", "5"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "icenorthe").strip() or "icenorthe"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "www2003.").strip() or "www2003."
ADMIN_SESSION_COOKIE_NAME = os.getenv("ADMIN_SESSION_COOKIE_NAME", "zwc_admin_session").strip() or "zwc_admin_session"
ADMIN_SESSION_EXPIRE_DAYS = max(1, int(os.getenv("ADMIN_SESSION_EXPIRE_DAYS", "7")))
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "1").lower() not in {"0", "false", "no"}
SESSION_EXPIRE_DAYS = int(os.getenv("SESSION_EXPIRE_DAYS", "30"))
AGENT_HEARTBEAT_EXPIRE_SECONDS = max(15, int(os.getenv("AGENT_HEARTBEAT_EXPIRE_SECONDS", "45")))
AGENT_SOCKET_OVERVIEW_EXPIRE_SECONDS = max(
    15, int(os.getenv("AGENT_SOCKET_OVERVIEW_EXPIRE_SECONDS", "90"))
)
VISITOR_COOKIE_NAME = os.getenv("VISITOR_COOKIE_NAME", "zwc_visitor_id").strip() or "zwc_visitor_id"
VISITOR_COOKIE_MAX_AGE_SECONDS = max(
    86400, int(os.getenv("VISITOR_COOKIE_MAX_AGE_SECONDS", "31536000"))
)
REGISTER_VISITOR_SUCCESS_LIMIT = max(
    0, int(os.getenv("REGISTER_VISITOR_SUCCESS_LIMIT", "0"))
)
REGISTER_VISITOR_WINDOW_HOURS = max(
    1, int(os.getenv("REGISTER_VISITOR_WINDOW_HOURS", "168"))
)
REGISTER_IP_SUCCESS_LIMIT = max(0, int(os.getenv("REGISTER_IP_SUCCESS_LIMIT", "5")))
REGISTER_IP_WINDOW_HOURS = max(1, int(os.getenv("REGISTER_IP_WINDOW_HOURS", "24")))
REGISTER_IP_ATTEMPT_LIMIT = max(0, int(os.getenv("REGISTER_IP_ATTEMPT_LIMIT", "20")))
REGISTER_IP_ATTEMPT_WINDOW_MINUTES = max(
    1, int(os.getenv("REGISTER_IP_ATTEMPT_WINDOW_MINUTES", "60"))
)
REQUIRE_AGENT_ONLINE_FOR_ORDERS = os.getenv("REQUIRE_AGENT_ONLINE_FOR_ORDERS", "0").lower() in {
    "1",
    "true",
    "yes",
}
PAYMENT_MODE = os.getenv("PAYMENT_MODE", "disabled").strip().lower()
PAYMENT_BRIDGE_URL = os.getenv("PAYMENT_BRIDGE_URL", "").strip()
PAYMENT_BRIDGE_UPSTREAM = os.getenv("PAYMENT_BRIDGE_UPSTREAM", "").strip()
SOCKET_OVERVIEW_BRIDGE_URL = os.getenv("SOCKET_OVERVIEW_BRIDGE_URL", "").strip()
ORDER_PAY_MODE = os.getenv("ORDER_PAY_MODE", "balance").strip().lower()
PAYMENT_TOKEN_SECRET = os.getenv("PAYMENT_TOKEN_SECRET", "").strip()
PAYMENT_TOKEN_TTL_SECONDS = int(os.getenv("PAYMENT_TOKEN_TTL_SECONDS", "900"))
BALANCE_REFUND_ON_FAIL = os.getenv("BALANCE_REFUND_ON_FAIL", "1").lower() in {"1", "true", "yes"}
NO_LOAD_AUTO_REFUND_ENABLED = os.getenv("NO_LOAD_AUTO_REFUND_ENABLED", "1").lower() in {
    "1",
    "true",
    "yes",
}
NO_LOAD_AUTO_REFUND_MAX_WORK_MINUTES = max(
    0, int(os.getenv("NO_LOAD_AUTO_REFUND_MAX_WORK_MINUTES", "2"))
)
NO_LOAD_AUTO_REFUND_SCAN_LIMIT = max(20, int(os.getenv("NO_LOAD_AUTO_REFUND_SCAN_LIMIT", "120")))
NO_LOAD_AUTO_REFUND_MESSAGE = os.getenv(
    "NO_LOAD_AUTO_REFUND_MESSAGE",
    "检测到插座空载自动结束，已自动退款。请确认插头已插牢后再下单。",
).strip()
PROCESSING_TIMEOUT_SECONDS = max(30, int(os.getenv("PROCESSING_TIMEOUT_SECONDS", "60")))
PROCESSING_TIMEOUT_SCAN_LIMIT = max(20, int(os.getenv("PROCESSING_TIMEOUT_SCAN_LIMIT", "200")))
PROCESSING_TIMEOUT_MESSAGE = os.getenv(
    "PROCESSING_TIMEOUT_MESSAGE",
    "设备长时间未回传结果，订单已自动转为失败。请联系管理员核实。",
).strip()
ORDER_RECENT_SUBMIT_COOLDOWN_MINUTES = max(
    0, int(os.getenv("ORDER_RECENT_SUBMIT_COOLDOWN_MINUTES", "2"))
)
ORDER_FAILURE_WINDOW_MINUTES = max(0, int(os.getenv("ORDER_FAILURE_WINDOW_MINUTES", "30")))
ORDER_FAILURE_THRESHOLD = max(0, int(os.getenv("ORDER_FAILURE_THRESHOLD", "3")))
ORDER_EMPTY_LOAD_COOLDOWN_MINUTES = max(
    0, int(os.getenv("ORDER_EMPTY_LOAD_COOLDOWN_MINUTES", "20"))
)
PREFER_AGENT_SNAPSHOT = os.getenv("PREFER_AGENT_SNAPSHOT", "0").lower() in {"1", "true", "yes"}
ALLOW_STALE_AGENT_SNAPSHOT = os.getenv("ALLOW_STALE_AGENT_SNAPSHOT", "0").lower() in {
    "1",
    "true",
    "yes",
}
if PAYMENT_MODE not in {"disabled", "balance", "token"}:
    PAYMENT_MODE = "disabled"
if ORDER_PAY_MODE not in {"balance", "wechat"}:
    ORDER_PAY_MODE = "balance"

# 码支付配置。默认关闭，只有显式配置后才启用。
CODEPAY_ID = os.getenv("CODEPAY_ID", "").strip()
CODEPAY_KEY = os.getenv("CODEPAY_KEY", "").strip()
CODEPAY_API = os.getenv("CODEPAY_API", "").strip().rstrip("/")
CODEPAY_ENABLED = bool(CODEPAY_ID and CODEPAY_KEY and CODEPAY_API)

QJPAY_API = os.getenv("QJPAY_API", "https://pro.qjpay.icu").strip().rstrip("/")
QJPAY_PID = os.getenv("QJPAY_PID", "").strip()
QJPAY_KEY = os.getenv("QJPAY_KEY", "").strip()
QJPAY_CHANNEL_ID = os.getenv("QJPAY_CHANNEL_ID", "").strip()
QJPAY_ENABLED = bool(QJPAY_PID and QJPAY_KEY)
SERVICE_FEE_YUAN = float(os.getenv("SERVICE_FEE_YUAN", "0.5"))
SERVICE_FEE_ONE_YUAN = float(os.getenv("SERVICE_FEE_ONE_YUAN", "0.5"))
FIRST_RECHARGE_MIN_AMOUNT_YUAN = float(os.getenv("FIRST_RECHARGE_MIN_AMOUNT_YUAN", "5"))
FIRST_RECHARGE_FREE_CHARGE_BONUS = int(os.getenv("FIRST_RECHARGE_FREE_CHARGE_BONUS", "1"))
RECHARGE_FREE_CHARGE_RULES = (
    (30.0, 5),
    (20.0, 3),
    (10.0, 1),
)

MINUTES_PER_YUAN = 207
CHARGE_RESUME_HOUR = 7
DEFAULT_RECHARGE_QR_NOTE = "请付款后提交充值申请，审核通过后更新余额。"
MANUAL_PAYMENT_CONTACT = os.getenv("MANUAL_PAYMENT_CONTACT", "").strip()
MANUAL_PAYMENT_INSTRUCTIONS = os.getenv("MANUAL_PAYMENT_INSTRUCTIONS", "").strip()
REALTIME_STATUS_TIMEOUT_SECONDS = max(2.0, float(os.getenv("REALTIME_STATUS_TIMEOUT_SECONDS", "10")))
REALTIME_STATUS_MAX_WORKERS = max(1, int(os.getenv("REALTIME_STATUS_MAX_WORKERS", "2")))
REALTIME_PARSECK_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_parseCk.action"
REALTIME_USING_ORDERS_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_pileUsingOrders.action"
OFFICIAL_CONSUME_RECORD_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_consumeRecord.action"
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
SOCKET_OVERVIEW_CACHE_SECONDS = max(15, int(os.getenv("SOCKET_OVERVIEW_CACHE_SECONDS", "60")))
REALTIME_STATUS_SERIAL_RETRY_LIMIT = max(0, int(os.getenv("REALTIME_STATUS_SERIAL_RETRY_LIMIT", "2")))
REALTIME_STATUS_SERIAL_RETRY_SECONDS = max(
    0.0, float(os.getenv("REALTIME_STATUS_SERIAL_RETRY_SECONDS", "1.0"))
)
OFFICIAL_MATCH_MAX_SECONDS = max(300, int(os.getenv("OFFICIAL_MATCH_MAX_SECONDS", "21600")))
OFFICIAL_MATCH_MAX_PAST_SECONDS = max(0, int(os.getenv("OFFICIAL_MATCH_MAX_PAST_SECONDS", "1800")))
OFFICIAL_HEURISTIC_MATCH_MAX_SECONDS = max(
    1200,
    OFFICIAL_MATCH_MAX_SECONDS if OFFICIAL_MATCH_MAX_SECONDS > 0 else 1200,
)
USING_ORDER_MATCH_MAX_SECONDS = max(300, int(os.getenv("USING_ORDER_MATCH_MAX_SECONDS", "1800")))
REGION_SORT_ORDER = {
    "综合楼": 1,
    "学术交流中心": 2,
    "东盟一号": 3,
    "图书馆": 4,
    "综合楼/图书馆": 4,
    "19栋": 5,
    "19栋女生宿舍": 5,
    "19栋宿舍": 5,
}
HIDDEN_STATION_NUMBERS = {3, 46, 70}
_station_realtime_cache: dict[str, dict[str, Any]] = {}
_consume_record_snapshot: dict[str, Any] = {}
_socket_overview_cache: dict[str, dict[str, Any]] = {}
VISITOR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{12,128}$")


def load_official_timezone() -> timezone:
    key = os.getenv("OFFICIAL_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(key)
    except Exception:
        return timezone(timedelta(hours=8))


OFFICIAL_TIMEZONE = load_official_timezone()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def cutoff_iso(*, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=days, hours=hours, minutes=minutes)).isoformat()


def client_ip_from_request(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()[:128]
    client = getattr(request, "client", None)
    if client and getattr(client, "host", ""):
        return str(client.host).strip()[:128]
    return ""


def request_user_agent(request: Request) -> str:
    return str(request.headers.get("user-agent") or "").strip()[:300]


def request_visitor_id(request: Request) -> str:
    raw = str(request.cookies.get(VISITOR_COOKIE_NAME) or "").strip()
    if raw and VISITOR_ID_RE.fullmatch(raw):
        return raw
    return ""


def ensure_visitor_cookie(response: HTMLResponse, request: Request) -> str:
    visitor_id = request_visitor_id(request)
    if visitor_id:
        return visitor_id
    visitor_id = secrets.token_urlsafe(18)
    response.set_cookie(
        VISITOR_COOKIE_NAME,
        visitor_id,
        max_age=VISITOR_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return visitor_id


def upsert_site_visitor(request: Request, response: HTMLResponse, path: str = "/") -> None:
    visitor_id = ensure_visitor_cookie(response, request)
    ts = now_iso()
    ip = client_ip_from_request(request)
    user_agent = request_user_agent(request)
    try:
        with db_connect() as conn:
            updated = conn.execute(
                """
                UPDATE site_visitors
                SET last_seen_at = ?, last_path = ?, visit_count = visit_count + 1,
                    ip = ?, user_agent = ?
                WHERE visitor_id = ?
                """,
                (ts, path, ip, user_agent, visitor_id),
            ).rowcount
            if updated != 1:
                conn.execute(
                    """
                    INSERT INTO site_visitors
                        (visitor_id, first_seen_at, last_seen_at, first_path, last_path,
                         visit_count, ip, user_agent)
                    VALUES
                        (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (visitor_id, ts, ts, path, path, ip, user_agent),
                )
            conn.commit()
    except Exception:
        # Metrics collection should never block the landing page.
        return


def log_registration_attempt(
    conn: sqlite3.Connection,
    *,
    phone: str,
    request: Request,
    status: str,
    reason: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO registration_attempts
            (phone, visitor_id, ip, user_agent, status, reason, created_at)
        VALUES
            (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            phone,
            request_visitor_id(request),
            client_ip_from_request(request),
            request_user_agent(request),
            status[:32],
            reason[:120],
            now_iso(),
        ),
    )


def validate_registration_risk(conn: sqlite3.Connection, request: Request) -> str:
    ip = client_ip_from_request(request)
    if ip and REGISTER_IP_ATTEMPT_LIMIT > 0:
        attempt_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM registration_attempts
            WHERE ip = ? AND created_at >= ?
            """,
            (ip, cutoff_iso(minutes=REGISTER_IP_ATTEMPT_WINDOW_MINUTES)),
        ).fetchone()[0]
        if int(attempt_count or 0) >= REGISTER_IP_ATTEMPT_LIMIT:
            return "ip_attempt_limit"
    if ip and REGISTER_IP_SUCCESS_LIMIT > 0:
        ip_success = conn.execute(
            """
            SELECT COUNT(*)
            FROM registration_attempts
            WHERE ip = ? AND status = 'SUCCESS' AND created_at >= ?
            """,
            (ip, cutoff_iso(hours=REGISTER_IP_WINDOW_HOURS)),
        ).fetchone()[0]
        if int(ip_success or 0) >= REGISTER_IP_SUCCESS_LIMIT:
            return "ip_success_limit"
    return ""


def should_block_for_recent_activity(rows: list[sqlite3.Row], *, now: datetime) -> str | None:
    if not rows:
        return None

    recent_cutoff = (
        now - timedelta(minutes=ORDER_RECENT_SUBMIT_COOLDOWN_MINUTES)
        if ORDER_RECENT_SUBMIT_COOLDOWN_MINUTES > 0
        else None
    )
    failure_cutoff = (
        now - timedelta(minutes=ORDER_FAILURE_WINDOW_MINUTES)
        if ORDER_FAILURE_WINDOW_MINUTES > 0
        else None
    )
    empty_cutoff = (
        now - timedelta(minutes=ORDER_EMPTY_LOAD_COOLDOWN_MINUTES)
        if ORDER_EMPTY_LOAD_COOLDOWN_MINUTES > 0
        else None
    )
    empty_keywords = ("空载", "未插", "未插好", "插头", "无负载")

    recent_failures = 0
    last_failure_at: datetime | None = None
    last_failure_message = ""

    for row in rows:
        updated_at = parse_iso(str(row["updated_at"] or row["created_at"] or ""))
        if updated_at is None:
            continue
        status = str(row["status"] or "").upper()
        message = str(row["result_message"] or "")

        if recent_cutoff and updated_at >= recent_cutoff:
            return "该插座刚刚提交过订单，请稍后再试。"

        if status == "FAILED":
            if failure_cutoff and updated_at >= failure_cutoff:
                recent_failures += 1
            if last_failure_at is None or updated_at > last_failure_at:
                last_failure_at = updated_at
                last_failure_message = message

    if ORDER_FAILURE_THRESHOLD > 0 and failure_cutoff and recent_failures >= ORDER_FAILURE_THRESHOLD:
        return "该插座近期失败次数过多，已临时暂停下单，请稍后再试。"

    if (
        empty_cutoff
        and last_failure_at is not None
        and last_failure_at >= empty_cutoff
        and any(keyword in last_failure_message for keyword in empty_keywords)
    ):
        return "检测到插座空载/未插好，已临时暂停下单，请确认插头后再试。"

    return None


def parse_official_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=OFFICIAL_TIMEZONE).astimezone(UTC)


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
        "综合楼/图书馆": "图书馆",
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


def normalize_socket_remap(item: dict[str, Any], socket_count: int) -> dict[str, int]:
    raw = item.get("socket_remap", item.get("socket_map", {}))
    if not isinstance(raw, dict):
        return {}
    remap: dict[str, int] = {}
    for src, dst in raw.items():
        src_no = optional_int(src)
        dst_no = optional_int(dst)
        if (
            src_no is None
            or dst_no is None
            or src_no < 1
            or src_no > socket_count
            or dst_no < 1
            or dst_no > socket_count
        ):
            continue
        remap[str(src_no)] = dst_no
    return remap


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


def payment_bridge_upstream() -> str:
    upstream = PAYMENT_BRIDGE_UPSTREAM or PAYMENT_BRIDGE_URL
    return upstream.strip().rstrip("/")


def append_qjpay_log(message: str) -> None:
    try:
        log_path = RUNTIME_DIR / "qjpay_notify.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8") if not log_path.exists() else None
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{now_iso()}] {message}\n")
    except Exception:
        pass


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
    default_address = "四川省成都市龙泉驿区十陵街道"
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


def service_fee_yuan(amount_yuan: float) -> float:
    return SERVICE_FEE_YUAN


def total_cost_yuan(amount_yuan: float) -> float:
    return round(float(amount_yuan) + service_fee_yuan(amount_yuan), 2)


def order_service_fee_yuan(amount_yuan: float, free_charge_used: int | bool = 0) -> float:
    """Compute service fee for an order, respecting free-charge vouchers.

    free_charge_used=1 means the service fee is waived for this order.
    """

    if int(free_charge_used or 0) > 0:
        return 0.0
    return service_fee_yuan(amount_yuan)


def order_total_cost_yuan(amount_yuan: float, free_charge_used: int | bool = 0) -> float:
    return round(float(amount_yuan) + order_service_fee_yuan(amount_yuan, free_charge_used), 2)


def build_order_settlement(
    *,
    amount_yuan: float,
    free_charge_used: int | bool = 0,
    status: str = "",
    balance_refunded: int | bool = 0,
    official_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total_cost = order_total_cost_yuan(amount_yuan, free_charge_used)
    detail = official_detail or {}
    normalized_status = str(status or "").strip().upper()
    official_refund = round(max(float(detail.get("refund") or 0), 0.0), 2)
    official_total_fee = round(max(float(detail.get("total_fee") or 0), 0.0), 2)
    has_official_settlement = any(
        key in detail and detail.get(key) not in (None, "")
        for key in ("total_fee", "refund")
    )

    consumed_amount = 0.0
    refund_amount = 0.0
    actual_paid = 0.0
    settlement_ready = False

    if normalized_status == "FAILED" and int(balance_refunded or 0) == 1:
        refund_amount = total_cost
        settlement_ready = True
    elif has_official_settlement:
        consumed_amount = official_total_fee
        refund_amount = official_refund
        actual_paid = round(max(total_cost - official_refund, 0.0), 2)
        settlement_ready = True

    return {
        "consumed_amount_yuan": consumed_amount,
        "refund_amount_yuan": refund_amount,
        "actual_paid_yuan": actual_paid,
        "settlement_ready": settlement_ready,
    }


def recharge_bonus_free_charge_count(amount_yuan: float) -> int:
    amount = float(amount_yuan or 0)
    for threshold, bonus_count in RECHARGE_FREE_CHARGE_RULES:
        if amount + 1e-9 >= threshold:
            return int(bonus_count)
    return 0


def consume_record_cid(record: dict[str, Any]) -> str:
    return str(record.get("cid") or "").strip()


def consume_record_key(record: dict[str, Any]) -> str:
    cid = consume_record_cid(record)
    if cid:
        return f"cid:{cid}"
    return "|".join(
        [
            str(record.get("sn") or "").strip(),
            str(record.get("sid") or "").strip(),
            str(record.get("startTime") or "").strip(),
            str(record.get("endTime") or "").strip(),
            str(record.get("totalFee") or "").strip(),
        ]
    )


def merge_consume_records(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for record in group:
            if not isinstance(record, dict):
                continue
            key = consume_record_key(record)
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)
    return merged


def order_bound_official_id(order: dict[str, Any]) -> str:
    for value in (
        order.get("official_order_id"),
        get_nested_value(order, "official_detail.cid", ""),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def looks_like_official_order_id(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return (text.isdigit() and len(text) >= 8) or lowered.startswith("official-")


def official_amount_for_record(record: dict[str, Any]) -> float:
    total_fee = float(record.get("totalFee") or 0)
    refund = float(record.get("refund") or 0)
    return round(total_fee + refund, 2)


def build_consume_match_candidate(
    order: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any] | None:
    device_code = str(order.get("device_code") or "").strip()
    socket_no = optional_int(order.get("socket_no"))
    if not device_code or not socket_no:
        return None
    sn = str(record.get("sn") or "").strip()
    sid = optional_int(record.get("sid"))
    if sn != device_code or sid != socket_no:
        return None

    cid = consume_record_cid(record)
    created_at = parse_iso(str(order.get("created_at") or ""))
    start_time = parse_official_datetime(record.get("startTime"))
    end_time = parse_official_datetime(record.get("endTime"))
    if created_at is None or start_time is None:
        return None
    if OFFICIAL_MATCH_MAX_PAST_SECONDS and start_time < created_at - timedelta(
        seconds=OFFICIAL_MATCH_MAX_PAST_SECONDS
    ):
        return None
    diff_seconds = abs((start_time - created_at).total_seconds())
    if OFFICIAL_HEURISTIC_MATCH_MAX_SECONDS and diff_seconds > OFFICIAL_HEURISTIC_MATCH_MAX_SECONDS:
        return None

    amount_yuan = round(float(order.get("amount_yuan") or 0), 2)
    expected_amount = official_amount_for_record(record)
    fee_delta = abs(expected_amount - amount_yuan)
    if fee_delta > 0.01:
        return None

    return {
        "order_id": int(order.get("id") or 0),
        "record": record,
        "record_key": consume_record_key(record),
        "cid": cid,
        "score": diff_seconds + (fee_delta * 600),
        "diff_seconds": diff_seconds,
        "fee_delta": fee_delta,
        "start_time": start_time,
        "end_time": end_time,
    }


def match_consume_record_for_order(
    order: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any] | None:
    stored_official_id = order_bound_official_id(order)
    vendor_order_id = str(order.get("vendor_order_id") or "").strip()
    exact_ids = [value for value in (stored_official_id,) if value]
    if looks_like_official_order_id(vendor_order_id) and vendor_order_id not in exact_ids:
        exact_ids.append(vendor_order_id)
    best_candidate: dict[str, Any] | None = None
    second_best_candidate: dict[str, Any] | None = None
    for record in records:
        cid = consume_record_cid(record)
        if exact_ids:
            if cid and cid in exact_ids:
                return record
            continue
        candidate = build_consume_match_candidate(order, record)
        if candidate is None:
            continue
        if best_candidate is None or candidate["score"] < best_candidate["score"]:
            second_best_candidate = best_candidate
            best_candidate = candidate
        elif second_best_candidate is None or candidate["score"] < second_best_candidate["score"]:
            second_best_candidate = candidate

    if best_candidate is None:
        return None
    if second_best_candidate is not None:
        if abs(float(second_best_candidate["score"]) - float(best_candidate["score"])) < 120:
            return None
    return best_candidate["record"]


def build_official_detail(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "cid": optional_text(record.get("cid")),
        "device_code": optional_text(record.get("sn")),
        "station_name": optional_text(record.get("snName")),
        "socket_no": optional_int(record.get("sid")),
        "start_time": optional_text(record.get("startTime")),
        "end_time": optional_text(record.get("endTime")),
        "work_time_minutes": optional_int(record.get("workTime")),
        "refund": float(record.get("refund") or 0),
        "total_fee": float(record.get("totalFee") or 0),
        "pay_way": optional_text(record.get("payWay")),
        "order_end_message": normalize_stop_reason(
            optional_text(record.get("orderEndMessage")),
            preserve_unknown=True,
        ),
        "order_end_code": optional_int(record.get("orderEndCode")),
        "order_end_power": optional_int(record.get("orderEndPower")),
    }


def official_detail_end_markers(detail: dict[str, Any] | None) -> tuple[bool, str]:
    payload = detail if isinstance(detail, dict) else {}
    end_time = optional_text(payload.get("end_time"))
    end_message = optional_text(payload.get("order_end_message"))
    end_power = optional_int(payload.get("order_end_power"))
    end_code = optional_int(payload.get("order_end_code"))
    parsed_end_time = parse_official_datetime(end_time)
    has_end_power = end_power not in (None, 0)
    has_end_code = end_code not in (None, 0)
    end_time_reached = bool(
        parsed_end_time is not None and parsed_end_time <= datetime.now(UTC) + timedelta(seconds=30)
    )
    ended = bool(end_message) or (end_time_reached and (has_end_power or has_end_code))
    return ended, end_time


def load_latest_order_ids_for_socket_keys(
    keys: set[tuple[str, int]] | list[tuple[str, int]] | tuple[tuple[str, int], ...],
) -> dict[tuple[str, int], int]:
    normalized = sorted(
        {
            (str(device_code).strip(), int(socket_no))
            for device_code, socket_no in keys
            if str(device_code).strip() and int(socket_no) > 0
        }
    )
    if not normalized:
        return {}
    latest: dict[tuple[str, int], int] = {}
    with db_connect() as conn:
        for device_code, socket_no in normalized:
            row = conn.execute(
                """
                SELECT id
                FROM orders
                WHERE device_code = ? AND socket_no = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (device_code, socket_no),
            ).fetchone()
            if row is not None:
                latest[(device_code, socket_no)] = int(row["id"])
    return latest


def using_snapshot_matches_order(
    order: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    latest_order_id: int | None,
) -> bool:
    if not snapshot:
        return False
    order_id = int(order.get("id") or 0)
    if order_id <= 0 or latest_order_id != order_id:
        return False

    start_time = parse_official_datetime(snapshot.get("start_time"))
    if start_time is None:
        return True

    refs: list[datetime] = []
    created_at = parse_iso(str(order.get("created_at") or ""))
    if created_at is not None:
        refs.append(created_at)
    official_start = parse_official_datetime(get_nested_value(order, "official_detail.start_time", ""))
    if official_start is not None:
        refs.append(official_start)
    if not refs:
        return True

    best_diff = min(abs((start_time - ref).total_seconds()) for ref in refs)
    return best_diff <= USING_ORDER_MATCH_MAX_SECONDS


def should_auto_refund_no_load(order_row: sqlite3.Row, official_detail: dict[str, Any]) -> bool:
    if not NO_LOAD_AUTO_REFUND_ENABLED:
        return False
    if not BALANCE_REFUND_ON_FAIL:
        return False
    if str(order_row["status"] or "").strip().upper() != "SUCCESS":
        return False
    if str(order_row["payment_mode"] or "").strip().lower() != "balance":
        return False
    if int(order_row["balance_deducted"] or 0) != 1:
        return False
    if int(order_row["balance_refunded"] or 0) != 0:
        return False
    if order_row["user_id"] is None:
        return False

    stop_reason = str(official_detail.get("order_end_message") or "").strip()
    if stop_reason != "空载":
        return False
    work_time = official_detail.get("work_time_minutes")
    try:
        work_minutes = int(work_time) if work_time not in (None, "") else None
    except (TypeError, ValueError):
        work_minutes = None
    if work_minutes is None or work_minutes > NO_LOAD_AUTO_REFUND_MAX_WORK_MINUTES:
        return False

    try:
        total_fee = float(official_detail.get("total_fee") or 0)
    except (TypeError, ValueError):
        total_fee = 0.0
    if total_fee > 1e-6:
        # Has actual consumption; do not auto-refund as "no-load".
        return False
    return True


def auto_refund_no_load_orders(consume_records: list[dict[str, Any]]) -> int:
    if not NO_LOAD_AUTO_REFUND_ENABLED:
        return 0
    if not consume_records:
        return 0
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE status = 'SUCCESS'
              AND payment_mode = 'balance'
              AND balance_deducted = 1
              AND balance_refunded = 0
            ORDER BY id DESC
            LIMIT ?
            """,
            (NO_LOAD_AUTO_REFUND_SCAN_LIMIT,),
        ).fetchall()
    refunded = 0
    for row in rows:
        order = row_to_dict(row)
        match = match_consume_record_for_order(order, consume_records)
        if not match:
            continue
        detail = build_official_detail(match)
        if not should_auto_refund_no_load(row, detail):
            continue
        update_order_result(
            int(row["id"]),
            "FAILED",
            NO_LOAD_AUTO_REFUND_MESSAGE,
            vendor_order_id=str(row["vendor_order_id"] or ""),
        )
        refunded += 1
    return refunded


def estimated_finish_at(created_at: str, amount_yuan: float) -> str:
    started_at = parse_iso(created_at)
    if started_at is None:
        return ""
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return add_charge_runtime_minutes(started_at, approx_charge_minutes(amount_yuan)).astimezone(UTC).isoformat()


def align_charge_runtime_start(started_at: datetime) -> datetime:
    local_started_at = started_at.astimezone(OFFICIAL_TIMEZONE)
    if local_started_at.hour >= CHARGE_RESUME_HOUR:
        return local_started_at
    return local_started_at.replace(hour=CHARGE_RESUME_HOUR, minute=0, second=0, microsecond=0)


def add_charge_runtime_minutes(started_at: datetime, runtime_minutes: int | float) -> datetime:
    current = align_charge_runtime_start(started_at)
    remaining_seconds = max(float(runtime_minutes or 0), 0.0) * 60.0
    while remaining_seconds > 0:
        local_midnight = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        seconds_until_pause = max((local_midnight - current).total_seconds(), 0.0)
        if remaining_seconds <= seconds_until_pause:
            return current + timedelta(seconds=remaining_seconds)
        remaining_seconds -= seconds_until_pause
        current = local_midnight + timedelta(hours=CHARGE_RESUME_HOUR)
    return current


def charge_state_for_order(status: str, estimated_finish: str) -> tuple[str, str]:
    normalized = str(status or "").upper()
    if normalized == "FAILED":
        return "FAILED", ""
    if normalized in {"PENDING", "PROCESSING"}:
        return normalized, ""
    finish_at = parse_iso(estimated_finish)
    if normalized == "SUCCESS" and finish_at is not None:
        return "CHARGING_ESTIMATED", ""
    return normalized, ""


def charge_stop_reason_from_message(message: Any) -> str:
    text = clean_result_message(message).strip()
    return normalize_stop_reason(text)


def charge_stop_reason_from_text(text: Any) -> str:
    normalized = str(text or "").strip()
    return normalize_stop_reason(normalized)


def normalize_stop_reason(text: Any, *, preserve_unknown: bool = False) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if "过载" in normalized or "超出极限功率" in normalized:
        return "过载（超出极限功率）"
    if "充满" in normalized or "已充满" in normalized:
        return "充满"
    if "过充" in normalized:
        return "过充"
    if any(key in normalized for key in ("充电中断", "中断结束")):
        return "充电中断"
    if any(key in normalized for key in ("被拔", "充电被拔", "拔出", "枪被拔", "插头被拔")):
        return "被拔出"
    if "空载" in normalized:
        return "空载"
    if any(key in normalized for key in ("终止", "手动", "主动结束", "用户结束", "停止", "关闭")):
        return "终止"
    if any(
        key in normalized
        for key in (
            "达到预定时间",
            "达到预定时长",
            "到达预定时间",
            "达到设定时间",
            "达到预约时间",
            "工作完成",
            "时间到",
            "定时结束",
        )
    ):
        return "达到预定时长"
    return normalized if preserve_unknown else ""


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

    if status == "FAILED":
        lower_text = text.lower()
        in_use_markers = (
            "使用中",
            "已使用",
            "占用",
            "被占用",
            "in use",
            "occupied",
        )
        if any(marker in text for marker in in_use_markers) or any(
            marker in lower_text for marker in ("in use", "occupied")
        ):
            return "当前插座正在使用中，请更换插座后重试"

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


def format_realtime_error(err: BaseException) -> str:
    detail = str(err or "").strip()
    if detail:
        joiner = "" if detail.startswith("[") else " "
        return f"官方实时未查询到，接口异常{joiner}{detail}"
    return "官方实时未查询到"


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
            SELECT users.id, users.phone, users.balance_yuan, users.free_charge_count, users.created_at, users.updated_at,
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
        socket_remap = normalize_socket_remap(item, socket_count)
        station = {
            "id": station_id,
            "name": name,
            "device_code": device_code,
            "socket_count": socket_count,
            "address": address,
            "region": region,
            "sort_order": sort_order,
            "disabled_sockets": disabled_sockets,
            "socket_remap": socket_remap,
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


def cache_socket_overview(region_key: str | None, snapshot: list[dict[str, Any]]) -> None:
    cache_key = overview_region_key(region_key) if region_key else "__all__"
    _socket_overview_cache[cache_key] = {
        "cached_at": time.time(),
        "snapshot": json.loads(json.dumps(snapshot, ensure_ascii=False)),
    }


def cached_socket_overview(region_key: str | None) -> list[dict[str, Any]] | None:
    cache_key = overview_region_key(region_key) if region_key else "__all__"
    cached = _socket_overview_cache.get(cache_key)
    if not cached:
        return None
    if (time.time() - float(cached.get("cached_at", 0))) > SOCKET_OVERVIEW_CACHE_SECONDS:
        _socket_overview_cache.pop(cache_key, None)
        return None
    snapshot = cached.get("snapshot")
    if not isinstance(snapshot, list):
        return None
    return json.loads(json.dumps(snapshot, ensure_ascii=False))


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


def configured_charge_member_id() -> str:
    return optional_text(load_charge_api_config().get("member_id"))


def configured_status_member_id() -> str:
    data = load_charge_api_config()
    status_id = optional_text(data.get("member_id_status"))
    if status_id:
        return status_id
    return optional_text(data.get("member_id"))


def configured_official_record_member_ids() -> list[str]:
    member_ids: list[str] = []
    for value in (configured_charge_member_id(), configured_status_member_id()):
        text = str(value or "").strip()
        if text and text not in member_ids:
            member_ids.append(text)
    return member_ids


def configured_realtime_using_member_ids() -> list[str]:
    member_ids: list[str] = []
    for value in (configured_status_member_id(), configured_charge_member_id()):
        text = str(value or "").strip()
        if text and text not in member_ids:
            member_ids.append(text)
    return member_ids


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
            remain_seconds = parse_seconds(
                item.get("remainSeconds")
                or item.get("leftSeconds")
                or item.get("remainingSeconds")
                or item.get("surplusSeconds")
                or item.get("countdown")
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


def merge_using_orders_for_member_ids(
    member_ids: list[str] | tuple[str, ...],
) -> tuple[dict[tuple[str, int], dict[str, Any]], str]:
    ordered_ids: list[str] = []
    for value in member_ids:
        text = str(value or "").strip()
        if text and text not in ordered_ids:
            ordered_ids.append(text)
    if not ordered_ids:
        return {}, "配置缺少 member_id"

    merged: dict[tuple[str, int], dict[str, Any]] = {}
    errors: list[str] = []
    success = False
    for member_id in ordered_ids:
        try:
            using_orders, _ = fetch_using_orders(member_id)
            success = True
        except Exception as err:
            message = format_realtime_error(err)
            if message and message not in errors:
                errors.append(message)
            continue
        for key, data in using_orders.items():
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(data)
                continue
            for field, value in data.items():
                if existing.get(field) in (None, "") and value not in (None, ""):
                    existing[field] = value
    if success:
        return merged, ""
    return merged, "；".join(errors)


def fetch_consume_records(
    member_id: str, *, page_index: int = 1, page_size: int = 50
) -> tuple[list[dict[str, Any]], str]:
    if not member_id:
        return [], "配置缺少 member_id"
    payload = post_form_json(
        OFFICIAL_CONSUME_RECORD_URL,
        {
            "memberId": member_id,
            "pageIndex": str(max(1, int(page_index))),
            "pageSize": str(max(1, min(int(page_size), 100))),
        },
    )
    records = payload.get("list")
    if not isinstance(records, list):
        records = []
    return [item for item in records if isinstance(item, dict)], optional_text(payload.get("msg"))


def set_consume_record_snapshot(records: list[dict[str, Any]], captured_at: str | None = None) -> None:
    _consume_record_snapshot.clear()
    _consume_record_snapshot.update(
        {
            "captured_at": captured_at or now_iso(),
            "records": json.loads(json.dumps(records, ensure_ascii=False)),
        }
    )


def latest_consume_record_snapshot(max_age_seconds: int = 180) -> list[dict[str, Any]] | None:
    cached_at = _consume_record_snapshot.get("captured_at")
    if not cached_at:
        return None
    parsed = parse_iso(str(cached_at))
    if parsed is None:
        return None
    if (datetime.now(UTC) - parsed).total_seconds() > max_age_seconds:
        return None
    records = _consume_record_snapshot.get("records")
    if not isinstance(records, list):
        return None
    return [item for item in records if isinstance(item, dict)]


def order_needs_official_refresh(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").upper()
    if status == "FAILED":
        return False
    return status in {"PENDING", "PROCESSING"} or not bool(item.get("official_detail"))


def earliest_order_created_at_for_official_lookup(items: list[dict[str, Any]]) -> datetime | None:
    refs: list[datetime] = []
    for item in items:
        if not order_needs_official_refresh(item):
            continue
        created_at = parse_iso(str(item.get("created_at") or ""))
        if created_at is not None:
            refs.append(created_at)
    return min(refs) if refs else None


def fetch_consume_records_for_items(
    member_id: str,
    items: list[dict[str, Any]],
    *,
    max_pages: int = 5,
    page_size: int = 100,
) -> tuple[list[dict[str, Any]], str]:
    if not member_id:
        return [], "配置缺少 member_id"

    earliest_created_at = earliest_order_created_at_for_official_lookup(items)
    cutoff = (
        earliest_created_at - timedelta(seconds=OFFICIAL_MATCH_MAX_PAST_SECONDS)
        if earliest_created_at is not None
        else None
    )
    collected: list[dict[str, Any]] = []
    message = ""

    for page_index in range(1, max(1, int(max_pages)) + 1):
        rows, message = fetch_consume_records(member_id, page_index=page_index, page_size=page_size)
        collected = merge_consume_records(collected, rows)
        if not rows or len(rows) < page_size:
            break
        if cutoff is None:
            break
        oldest_ref: datetime | None = None
        for record in rows:
            ref = parse_official_datetime(record.get("startTime")) or parse_official_datetime(
                record.get("endTime")
            )
            if ref is None:
                continue
            if oldest_ref is None or ref < oldest_ref:
                oldest_ref = ref
        if oldest_ref is not None and oldest_ref <= cutoff:
            break

    return collected, message


def load_existing_official_order_bindings(cids: set[str]) -> dict[str, int]:
    normalized = sorted({cid.strip() for cid in cids if cid and cid.strip()})
    if not normalized:
        return {}
    placeholders = ",".join("?" for _ in normalized)
    params = normalized + normalized
    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, official_order_id, vendor_order_id
            FROM orders
            WHERE official_order_id IN ({placeholders})
               OR vendor_order_id IN ({placeholders})
            """,
            params,
        ).fetchall()
    claimed: dict[str, int] = {}
    for row in rows:
        order_id = int(row["id"])
        official_order_id = str(row["official_order_id"] or "").strip()
        if official_order_id and official_order_id in normalized and official_order_id not in claimed:
            claimed[official_order_id] = order_id
        vendor_order_id = str(row["vendor_order_id"] or "").strip()
        if (
            looks_like_official_order_id(vendor_order_id)
            and vendor_order_id in normalized
            and vendor_order_id not in claimed
        ):
            claimed[vendor_order_id] = order_id
    return claimed


def persist_official_detail_for_order(order_id: int, detail: dict[str, Any]) -> None:
    if order_id <= 0 or not detail:
        return
    official_order_id = str(detail.get("cid") or "").strip()
    payload = json.dumps(detail, ensure_ascii=False)
    ts = now_iso()
    with db_connect() as conn:
        if official_order_id:
            existing = conn.execute(
                "SELECT id FROM orders WHERE id != ? AND official_order_id = ? LIMIT 1",
                (order_id, official_order_id),
            ).fetchone()
            if existing is not None:
                return
        if official_order_id:
            conn.execute(
                """
                UPDATE orders
                SET official_order_id = ?, official_detail_json = ?, official_detail_updated_at = ?
                WHERE id = ?
                """,
                (official_order_id, payload, ts, order_id),
            )
        else:
            conn.execute(
                """
                UPDATE orders
                SET official_detail_json = ?, official_detail_updated_at = ?
                WHERE id = ?
                """,
                (payload, ts, order_id),
            )
        conn.commit()


def refresh_order_item_from_db(
    order_id: int,
    items_by_id: dict[int, dict[str, Any]],
    row_by_id: dict[int, sqlite3.Row],
) -> sqlite3.Row | None:
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return None
    row_by_id[order_id] = row
    items_by_id[order_id] = row_to_dict(row)
    return row


def reconcile_order_status_with_consume_record(
    item: dict[str, Any],
    row_by_id: dict[int, sqlite3.Row],
    items_by_id: dict[int, dict[str, Any]],
    detail: dict[str, Any],
) -> sqlite3.Row | None:
    order_id = int(item.get("id") or 0)
    if order_id <= 0:
        return row_by_id.get(order_id)
    current_status = str(item.get("status") or "").upper()
    if current_status not in {"PENDING", "PROCESSING"}:
        return row_by_id.get(order_id)
    vendor_order_id = str(item.get("vendor_order_id") or detail.get("cid") or "").strip()
    success_message = str(item.get("result_message") or "").strip() or "充电已提交成功"
    update_order_result(order_id, "SUCCESS", success_message, vendor_order_id)
    return refresh_order_item_from_db(order_id, items_by_id, row_by_id)


def select_consume_record_matches(
    items: list[dict[str, Any]],
    consume_records: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    if not items or not consume_records:
        return {}

    record_cids = {consume_record_cid(record) for record in consume_records if consume_record_cid(record)}
    claimed_cids = load_existing_official_order_bindings(record_cids)
    matches: dict[int, dict[str, Any]] = {}
    used_record_keys: set[str] = set()
    used_order_ids: set[int] = set()

    for item in items:
        order_id = int(item.get("id") or 0)
        if order_id <= 0:
            continue
        exact_ids = []
        stored_id = order_bound_official_id(item)
        vendor_id = str(item.get("vendor_order_id") or "").strip()
        if stored_id:
            exact_ids.append(stored_id)
        if looks_like_official_order_id(vendor_id) and vendor_id not in exact_ids:
            exact_ids.append(vendor_id)
        if not exact_ids:
            continue
        for record in consume_records:
            cid = consume_record_cid(record)
            if not cid or cid not in exact_ids:
                continue
            owner = claimed_cids.get(cid)
            if owner not in (None, order_id):
                continue
            matches[order_id] = record
            used_order_ids.add(order_id)
            used_record_keys.add(consume_record_key(record))
            claimed_cids[cid] = order_id
            break

    candidates_by_order: dict[int, list[dict[str, Any]]] = {}
    candidates_by_record: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        order_id = int(item.get("id") or 0)
        if order_id <= 0 or order_id in used_order_ids or order_bound_official_id(item):
            continue
        for record in consume_records:
            record_key = consume_record_key(record)
            if record_key in used_record_keys:
                continue
            cid = consume_record_cid(record)
            if not cid:
                continue
            owner = claimed_cids.get(cid)
            if owner not in (None, order_id):
                continue
            candidate = build_consume_match_candidate(item, record)
            if candidate is None:
                continue
            candidates_by_order.setdefault(order_id, []).append(candidate)
            candidates_by_record.setdefault(record_key, []).append(candidate)

    safe_candidates: list[dict[str, Any]] = []
    for order_id, candidates in candidates_by_order.items():
        ranked_for_order = sorted(candidates, key=lambda candidate: float(candidate["score"]))
        best_for_order = ranked_for_order[0]
        second_for_order = ranked_for_order[1] if len(ranked_for_order) > 1 else None
        ranked_for_record = sorted(
            candidates_by_record.get(str(best_for_order["record_key"]), []),
            key=lambda candidate: float(candidate["score"]),
        )
        if not ranked_for_record or int(ranked_for_record[0]["order_id"]) != order_id:
            continue
        second_for_record = ranked_for_record[1] if len(ranked_for_record) > 1 else None
        if second_for_order is not None and (
            float(second_for_order["score"]) - float(best_for_order["score"])
        ) < 120:
            continue
        if second_for_record is not None and (
            float(second_for_record["score"]) - float(best_for_order["score"])
        ) < 120:
            continue
        safe_candidates.append(best_for_order)

    for candidate in sorted(safe_candidates, key=lambda current: float(current["score"])):
        order_id = int(candidate["order_id"])
        record = candidate["record"]
        record_key = str(candidate["record_key"])
        cid = str(candidate["cid"] or "").strip()
        if order_id in used_order_ids or record_key in used_record_keys:
            continue
        owner = claimed_cids.get(cid) if cid else None
        if owner not in (None, order_id):
            continue
        matches[order_id] = record
        used_order_ids.add(order_id)
        used_record_keys.add(record_key)
        if cid:
            claimed_cids[cid] = order_id

    return matches


def apply_consume_records_to_order_items(
    items: list[dict[str, Any]],
    row_by_id: dict[int, sqlite3.Row],
    consume_records: list[dict[str, Any]],
) -> None:
    if not items or not consume_records:
        return
    items_by_id = {int(item.get("id") or 0): item for item in items}
    matched_records = select_consume_record_matches(items, consume_records)
    for index, item in enumerate(items):
        match = matched_records.get(int(item.get("id") or 0))
        if not match:
            continue
        detail = build_official_detail(match)
        updated_row = reconcile_order_status_with_consume_record(item, row_by_id, items_by_id, detail)
        persist_official_detail_for_order(int(item.get("id") or 0), detail)
        if updated_row is None:
            updated_row = refresh_order_item_from_db(int(item.get("id") or 0), items_by_id, row_by_id)
        current_item = items_by_id.get(int(item.get("id") or 0), item)
        current_item["official_detail"] = detail
        ended_flag, official_end_time = official_detail_end_markers(detail)
        realtime_status = str(current_item.get("realtime_status") or "").strip()
        realtime_active = realtime_status in {"使用中", "充电中"}
        if realtime_active and str(current_item.get("status") or "").upper() == "SUCCESS":
            current_item["charge_state"] = "CHARGING_LIVE"
            current_item["charge_finished_at"] = ""
        if not realtime_active and ended_flag and str(current_item.get("charge_state") or "").upper() in {
            "CHARGING_ESTIMATED",
            "CHARGING_LIVE",
            "PROCESSING",
        }:
            current_item["charge_state"] = "ENDED_LIVE"
            parsed_end = parse_official_datetime(official_end_time)
            current_item["charge_finished_at"] = parsed_end.isoformat() if parsed_end else ""
        if not current_item.get("charge_stop_reason") and detail.get("order_end_message"):
            current_item["charge_stop_reason"] = detail.get("order_end_message")

        order_id = int(current_item.get("id") or 0)
        order_row = updated_row or row_by_id.get(order_id)
        if order_row is not None and should_auto_refund_no_load(order_row, detail):
            try:
                update_order_result(
                    order_id,
                    "FAILED",
                    NO_LOAD_AUTO_REFUND_MESSAGE,
                    vendor_order_id=str(order_row["vendor_order_id"] or detail.get("cid") or ""),
                )
                failed_row = refresh_order_item_from_db(order_id, items_by_id, row_by_id)
                current_item = items_by_id.get(order_id, current_item)
                current_item["official_detail"] = detail
                current_item["status"] = "FAILED"
                current_item["result_message"] = NO_LOAD_AUTO_REFUND_MESSAGE
                current_item["charge_state"] = "FAILED"
                if not current_item.get("charge_stop_reason"):
                    current_item["charge_stop_reason"] = "空载"
                if failed_row is not None:
                    row_by_id[order_id] = failed_row
                    order_row = failed_row
            except Exception:
                pass
        settlement = build_order_settlement(
            amount_yuan=float(current_item.get("amount_yuan") or 0),
            free_charge_used=int(current_item.get("free_charge_used") or 0),
            status=str(current_item.get("status") or ""),
            balance_refunded=int(order_row["balance_refunded"] or 0) if order_row is not None else 0,
            official_detail=current_item.get("official_detail") or {},
        )
        current_item.update(settlement)
        items[index] = current_item


def attach_official_details_to_order_items(
    items: list[dict[str, Any]],
    row_by_id: dict[int, sqlite3.Row],
    *,
    limit: int,
) -> str:
    if not items:
        return ""

    consume_message = ""
    cached_records = latest_consume_record_snapshot()
    consume_records = cached_records or []
    if consume_records:
        apply_consume_records_to_order_items(items, row_by_id, consume_records)

    if not any(order_needs_official_refresh(item) for item in items):
        return ""

    member_ids = configured_official_record_member_ids()
    if not member_ids:
        return "配置缺少 member_id" if not consume_records else ""

    try:
        merged_records = list(consume_records)
        latest_message = ""
        for member_id in member_ids:
            fresh_records, current_message = fetch_consume_records_for_items(
                member_id,
                items,
                page_size=min(100, max(50, limit)),
            )
            if current_message:
                latest_message = current_message
            if fresh_records:
                merged_records = merge_consume_records(merged_records, fresh_records)
        consume_message = latest_message
        if merged_records:
            set_consume_record_snapshot(merged_records, now_iso())
            apply_consume_records_to_order_items(items, row_by_id, merged_records)
    except Exception as err:
        if not consume_records:
            return format_realtime_error(err)
        return ""

    return consume_message


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


def extract_socket_countdown(product: dict[str, Any]) -> tuple[int | None, str]:
    remain_seconds = parse_seconds(
        product.get("remainSeconds")
        or product.get("leftSeconds")
        or product.get("remainingSeconds")
        or product.get("surplusSeconds")
        or product.get("countdown")
        or product.get("remain_seconds")
        or product.get("left_seconds")
        or product.get("remaining_seconds")
    )
    if remain_seconds is not None and remain_seconds > 0:
        return remain_seconds, ""
    end_time_raw = (
        product.get("endTime")
        or product.get("finishTime")
        or product.get("stopTime")
        or product.get("end_time")
        or product.get("finish_time")
        or product.get("stop_time")
    )
    end_time_seconds = parse_millis_as_seconds(end_time_raw)
    if end_time_seconds is not None:
        return end_time_seconds, ""
    end_time = optional_text(end_time_raw)
    return None, end_time


def socket_status_from_product(
    station: dict[str, Any],
    socket_no: int,
    product: dict[str, Any],
    using_orders: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    state = optional_int(product.get("state"))
    if state == 0:
        data: dict[str, Any] = {"socket_no": socket_no, "status": "空闲", "detail": ""}
        snapshot = using_orders.get((str(station["device_code"]), socket_no))
        if snapshot:
            for key in ("start_time", "end_time", "remain_seconds"):
                if snapshot.get(key) not in (None, ""):
                    data[key] = snapshot.get(key)
        remain_seconds, end_time = extract_socket_countdown(product)
        if "remain_seconds" not in data and remain_seconds is not None:
            data["remain_seconds"] = remain_seconds
        if "end_time" not in data and end_time:
            data["end_time"] = end_time
        return data
    if state == 1:
        snapshot = using_orders.get((str(station["device_code"]), socket_no))
        detail = format_using_order_detail(snapshot or {})
        data: dict[str, Any] = {"socket_no": socket_no, "status": "使用中", "detail": detail}
        if snapshot:
            # Pass-through optional countdown fields for the UI.
            for key in ("start_time", "end_time", "remain_seconds"):
                if snapshot.get(key) not in (None, ""):
                    data[key] = snapshot.get(key)
        remain_seconds, end_time = extract_socket_countdown(product)
        if "remain_seconds" not in data and remain_seconds is not None:
            data["remain_seconds"] = remain_seconds
        if "end_time" not in data and end_time:
            data["end_time"] = end_time
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
    status_member_id = configured_status_member_id()
    using_member_ids = configured_realtime_using_member_ids()
    using_orders: dict[tuple[str, int], dict[str, Any]] = {}
    using_orders_message = ""
    realtime_by_device: dict[str, dict[str, Any]] = {}
    serial_retry_candidates: list[dict[str, Any]] = []

    if using_member_ids:
        using_orders, using_orders_message = merge_using_orders_for_member_ids(using_member_ids)
    if status_member_id:
        realtime_candidates = [station for station in stations if optional_text(station.get("device_ck"))]
        if realtime_candidates:
            max_workers = min(REALTIME_STATUS_MAX_WORKERS, len(realtime_candidates))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_station = {
                    executor.submit(fetch_station_realtime, station, status_member_id): station
                    for station in realtime_candidates
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
                                "message": format_realtime_error(err),
                                "products": [],
                            }
                            if should_serial_retry_realtime_error(err):
                                serial_retry_candidates.append(station)
            if serial_retry_candidates:
                for station in serial_retry_candidates[:REALTIME_STATUS_SERIAL_RETRY_LIMIT]:
                    device_code = str(station["device_code"])
                    try:
                        result = fetch_station_realtime(station, status_member_id)
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
            if not status_member_id:
                station_result = {"ok": False, "message": "配置缺少 member_id", "products": []}
            elif not optional_text(station.get("device_code")):
                station_result = {"ok": False, "message": "仅录入站号，缺少 device_code / device_ck", "products": []}
            elif optional_text(station.get("device_ck")):
                station_result = {"ok": False, "message": "实时接口未返回结果", "products": []}
            elif has_using_order:
                station_result = {"ok": False, "message": "缺少 device_ck；仅能识别已配置账号充电中的插座", "products": []}
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


def build_realtime_snapshot_for_orders(
    rows: list[sqlite3.Row],
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, dict[str, Any]], str]:
    if not rows:
        return {}, {}, ""

    status_member_id = configured_status_member_id()
    using_orders, using_orders_message = merge_using_orders_for_member_ids(configured_realtime_using_member_ids())

    station_by_code = {
        str(station.get("device_code") or ""): station for station in load_stations() if station.get("device_code")
    }
    device_codes = {
        str(row["device_code"] or "").strip()
        for row in rows
        if str(row["device_code"] or "").strip()
    }
    realtime_by_device = build_realtime_by_device_from_agent_snapshot(device_codes)
    candidates = [
        station_by_code[code]
        for code in device_codes
        if (
            code in station_by_code
            and code not in realtime_by_device
            and optional_text(station_by_code[code].get("device_ck"))
        )
    ]

    if candidates and status_member_id:
        max_workers = min(REALTIME_STATUS_MAX_WORKERS, len(candidates))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_station = {
                executor.submit(fetch_station_realtime, station, status_member_id): station
                for station in candidates
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
                            "message": format_realtime_error(err),
                            "products": [],
                        }

    return using_orders, realtime_by_device, using_orders_message


def socket_snapshot_state(status: Any) -> int | None:
    normalized = str(status or "").strip()
    if normalized == "空闲":
        return 0
    if normalized in {"使用中", "充电中"}:
        return 1
    return None


def build_realtime_by_device_from_agent_snapshot(device_codes: set[str]) -> dict[str, dict[str, Any]]:
    if not device_codes:
        return {}
    allow_stale = ALLOW_STALE_AGENT_SNAPSHOT or PREFER_AGENT_SNAPSHOT
    snapshot = latest_agent_socket_overview(allow_stale=allow_stale)
    if not snapshot:
        return {}
    realtime_by_device: dict[str, dict[str, Any]] = {}
    for region in snapshot:
        if not isinstance(region, dict):
            continue
        stations = region.get("stations")
        if not isinstance(stations, list):
            continue
        for station in stations:
            if not isinstance(station, dict):
                continue
            device_code = str(station.get("device_code") or "").strip()
            if not device_code or device_code not in device_codes:
                continue
            sockets = station.get("sockets")
            products: list[dict[str, Any]] = []
            if isinstance(sockets, list):
                for socket in sockets:
                    if not isinstance(socket, dict):
                        continue
                    sid = optional_int(socket.get("socket_no"))
                    state = socket_snapshot_state(socket.get("status"))
                    if sid is None or sid <= 0 or state is None:
                        continue
                    product: dict[str, Any] = {"sid": sid, "state": state}
                    remain_seconds = socket.get("remain_seconds")
                    end_time = socket.get("end_time")
                    if remain_seconds not in (None, ""):
                        product["remain_seconds"] = remain_seconds
                    if end_time not in (None, ""):
                        product["end_time"] = end_time
                    products.append(product)
            realtime_by_device[device_code] = {
                "ok": bool(station.get("realtime_ok", True)),
                "message": optional_text(station.get("query_message")),
                "products": products,
                "source": "agent_socket_overview",
            }
    return realtime_by_device


def apply_realtime_status_for_orders(
    items: list[dict[str, Any]],
    using_orders: dict[tuple[str, int], dict[str, Any]],
    realtime_by_device: dict[str, dict[str, Any]],
    using_orders_message: str,
) -> None:
    if not items:
        return
    suppress_realtime_message = "官方实时未查询到" in str(using_orders_message or "")
    station_by_code = {
        str(station.get("device_code") or ""): station for station in load_stations() if station.get("device_code")
    }
    latest_order_id_by_socket = load_latest_order_ids_for_socket_keys(
        {
            (str(item.get("device_code") or "").strip(), int(optional_int(item.get("socket_no")) or 0))
            for item in items
            if str(item.get("device_code") or "").strip() and optional_int(item.get("socket_no"))
        }
    )
    for item in items:
        status = str(item.get("status") or "").upper()
        charge_state = str(item.get("charge_state") or "").upper()
        charge_finished_at = optional_text(item.get("charge_finished_at"))
        device_code = str(item.get("device_code") or "").strip()
        socket_no = optional_int(item.get("socket_no"))
        item.setdefault("realtime_status", "")
        item.setdefault("realtime_detail", "")
        item.setdefault("realtime_source", "")
        item.setdefault("realtime_ok", False)
        item.setdefault("realtime_message", "")
        if status == "FAILED" or (charge_state.startswith("ENDED") and charge_finished_at):
            item["realtime_status"] = ""
            item["realtime_detail"] = ""
            item["realtime_source"] = ""
            item["realtime_ok"] = False
            item["realtime_message"] = ""
            continue
        if not device_code or socket_no is None or socket_no <= 0:
            continue
        key = (device_code, socket_no)
        latest_order_id = latest_order_id_by_socket.get(key)
        using_snapshot = using_orders.get(key)
        matched_using_snapshot = using_snapshot_matches_order(item, using_snapshot, latest_order_id=latest_order_id)
        station_result = realtime_by_device.get(device_code)
        if station_result is None:
            if using_orders_message and not suppress_realtime_message:
                item["realtime_message"] = using_orders_message
            if matched_using_snapshot:
                detail = format_using_order_detail(using_snapshot)
                item["realtime_status"] = "使用中"
                item["realtime_detail"] = detail
                item["realtime_source"] = "using_orders"
                item["realtime_ok"] = True
                item["realtime_message"] = ""
                if str(item.get("status", "")).upper() == "SUCCESS" and charge_state in {
                    "CHARGING_ESTIMATED",
                    "CHARGING_LIVE",
                    "PENDING",
                    "PROCESSING",
                }:
                    item["charge_state"] = "CHARGING_LIVE"
                    item["charge_finished_at"] = ""
                if str(item.get("status", "")).upper() == "FAILED":
                    item["result_message"] = "当前插座正在使用中，请更换插座后重试"
            continue
        station = station_by_code.get(device_code) or {"device_code": device_code}
        products = station_result.get("products")
        product = None
        if isinstance(products, list):
            for raw in products:
                if not isinstance(raw, dict):
                    continue
                if optional_int(raw.get("sid")) == socket_no:
                    product = raw
                    break
        if product is not None:
            status_data = socket_status_from_product(station, socket_no, product, using_orders)
            live_status = str(status_data.get("status") or "")
            can_bind_live_status = latest_order_id == int(item.get("id") or 0)
            if live_status == "使用中" and not can_bind_live_status:
                item["realtime_status"] = ""
                item["realtime_detail"] = ""
                item["realtime_source"] = ""
                item["realtime_ok"] = False
                item["realtime_message"] = ""
                continue
            item["realtime_status"] = live_status
            item["realtime_detail"] = optional_text(status_data.get("detail"))
            item["realtime_source"] = "station_realtime"
            item["realtime_ok"] = bool(station_result.get("ok"))
            item["realtime_message"] = (
                "" if suppress_realtime_message else optional_text(station_result.get("message"))
            )
            if not item.get("charge_stop_reason"):
                item["charge_stop_reason"] = charge_stop_reason_from_text(item["realtime_detail"])
            if str(item.get("status", "")).upper() == "SUCCESS" and item["realtime_status"] == "使用中":
                if charge_state in {
                    "CHARGING_ESTIMATED",
                    "CHARGING_LIVE",
                    "PENDING",
                    "PROCESSING",
                } and (matched_using_snapshot or can_bind_live_status):
                    item["charge_state"] = "CHARGING_LIVE"
                    item["charge_finished_at"] = ""
            if str(item.get("status", "")).upper() == "FAILED" and item["realtime_status"] == "使用中":
                item["result_message"] = "当前插座正在使用中，请更换插座后重试"
            if (
                str(item.get("status", "")).upper() == "SUCCESS"
                and charge_state in {"CHARGING_ESTIMATED", "CHARGING_LIVE"}
                and item["realtime_status"] == "空闲"
            ):
                item["charge_state"] = "ENDED_LIVE"
                item["charge_finished_at"] = charge_finished_at
            continue
        if matched_using_snapshot:
            detail = format_using_order_detail(using_snapshot)
            item["realtime_status"] = "使用中"
            item["realtime_detail"] = detail
            item["realtime_source"] = "using_orders"
            item["realtime_ok"] = True
            item["realtime_message"] = ""
            if str(item.get("status", "")).upper() == "SUCCESS" and charge_state in {
                "CHARGING_ESTIMATED",
                "CHARGING_LIVE",
                "PENDING",
                "PROCESSING",
            }:
                item["charge_state"] = "CHARGING_LIVE"
                item["charge_finished_at"] = ""
            if str(item.get("status", "")).upper() == "FAILED":
                item["result_message"] = "当前插座正在使用中，请更换插座后重试"
            continue
        detail = "实时接口未返回该插座" if station_result.get("ok") else optional_text(station_result.get("message"))
        item["realtime_status"] = "未查询到"
        item["realtime_detail"] = detail
        item["realtime_source"] = "station_realtime"
        item["realtime_ok"] = bool(station_result.get("ok"))
        item["realtime_message"] = (
            "" if suppress_realtime_message else optional_text(station_result.get("message"))
        )
        if not item.get("charge_stop_reason"):
            item["charge_stop_reason"] = charge_stop_reason_from_text(item["realtime_detail"])


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
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
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
                official_order_id TEXT NOT NULL DEFAULT '',
                official_detail_json TEXT NOT NULL DEFAULT '',
                official_detail_updated_at TEXT NOT NULL DEFAULT '',
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
                service_fee REAL NOT NULL DEFAULT 0.5,
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS site_visitors (
                visitor_id TEXT PRIMARY KEY,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                first_path TEXT NOT NULL DEFAULT '',
                last_path TEXT NOT NULL DEFAULT '',
                visit_count INTEGER NOT NULL DEFAULT 1,
                ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registration_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL DEFAULT '',
                visitor_id TEXT NOT NULL DEFAULT '',
                ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
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
        "free_charge_count": "INTEGER NOT NULL DEFAULT 0",
        "user_note": "TEXT NOT NULL DEFAULT ''",
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
        "free_charge_used": "INTEGER NOT NULL DEFAULT 0",
        "official_order_id": "TEXT NOT NULL DEFAULT ''",
        "official_detail_json": "TEXT NOT NULL DEFAULT ''",
        "official_detail_updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    rows = conn.execute("PRAGMA table_info(orders)").fetchall()
    existing = {row["name"] for row in rows}
    for column_name, column_type in required_columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")


def ensure_recharge_request_columns(conn: sqlite3.Connection) -> None:
    required_columns = {
        "payment_method": "TEXT NOT NULL DEFAULT ''",
        "bonus_free_charge_count": "INTEGER NOT NULL DEFAULT 0",
        "bonus_free_charge_granted": "INTEGER NOT NULL DEFAULT 0",
    }
    rows = conn.execute("PRAGMA table_info(recharge_requests)").fetchall()
    existing = {row["name"] for row in rows}
    for column_name, column_type in required_columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE recharge_requests ADD COLUMN {column_name} {column_type}")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    created_at = str(row["created_at"] or "")
    amount_yuan = float(row["amount_yuan"] or 0)
    official_order_id = ""
    official_detail: dict[str, Any] = {}
    free_charge_used = 0
    try:
        if "free_charge_used" in row.keys():
            free_charge_used = int(row["free_charge_used"] or 0)
    except Exception:
        free_charge_used = 0
    try:
        if "official_order_id" in row.keys():
            official_order_id = str(row["official_order_id"] or "").strip()
        raw_detail = str(row["official_detail_json"] or "").strip() if "official_detail_json" in row.keys() else ""
        if raw_detail:
            parsed = json.loads(raw_detail)
            if isinstance(parsed, dict):
                official_detail = parsed
    except Exception:
        official_detail = {}
    if official_order_id and not str(official_detail.get("cid") or "").strip():
        official_detail["cid"] = official_order_id
    settlement = build_order_settlement(
        amount_yuan=amount_yuan,
        free_charge_used=free_charge_used,
        status=str(row["status"] or ""),
        balance_refunded=int(row["balance_refunded"] or 0) if "balance_refunded" in row.keys() else 0,
        official_detail=official_detail,
    )
    estimated_finish = estimated_finish_at(created_at, amount_yuan)
    charge_state, charge_finished_at = charge_state_for_order(str(row["status"] or ""), estimated_finish)
    official_ended, official_end_time = official_detail_end_markers(official_detail)
    if official_ended:
        charge_state = "ENDED_LIVE"
        parsed_official_end = parse_official_datetime(official_end_time)
        if parsed_official_end is not None:
            charge_finished_at = parsed_official_end.isoformat()
        elif official_end_time:
            charge_finished_at = official_end_time
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
        "free_charge_used": free_charge_used,
        "service_fee_yuan": order_service_fee_yuan(amount_yuan, free_charge_used),
        "total_cost_yuan": order_total_cost_yuan(amount_yuan, free_charge_used),
        "consumed_amount_yuan": settlement["consumed_amount_yuan"],
        "refund_amount_yuan": settlement["refund_amount_yuan"],
        "actual_paid_yuan": settlement["actual_paid_yuan"],
        "settlement_ready": settlement["settlement_ready"],
        "official_order_id": official_order_id,
        "official_detail": official_detail,
        "official_detail_updated_at": (
            str(row["official_detail_updated_at"] or "") if "official_detail_updated_at" in row.keys() else ""
        ),
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
    free_charge_used: int = 0
    service_fee_yuan: float = 0
    total_cost_yuan: float = 0
    consumed_amount_yuan: float = 0
    refund_amount_yuan: float = 0
    actual_paid_yuan: float = 0
    settlement_ready: bool = False
    realtime_status: str = ""
    realtime_detail: str = ""
    realtime_source: str = ""
    realtime_ok: bool = False
    realtime_message: str = ""
    official_detail: dict[str, Any] = Field(default_factory=dict)
    official_message: str = ""


class UserRegister(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class UserLogin(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class AdminLoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserView(BaseModel):
    id: int
    phone: str
    balance_yuan: float = 0
    free_charge_count: int = 0
    user_note: str = ""
    recharge_count: int = 0
    created_at: str
    last_order_at: str = ""


class AuthResponse(BaseModel):
    token: str
    user: UserView


class BalanceAdjustPayload(BaseModel):
    delta_yuan: float = Field(ge=-10000, le=10000)
    reason: str = Field(default="", max_length=200)


class BalanceSetPayload(BaseModel):
    balance_yuan: float = Field(ge=0, le=100000)
    reason: str = Field(default="", max_length=200)


class FreeChargeAdjustPayload(BaseModel):
    free_charge_count: int = Field(ge=0, le=10000)


class UserNotePayload(BaseModel):
    user_note: str = Field(default="", max_length=200)


class PasswordResetPayload(BaseModel):
    new_password: str = Field(min_length=6, max_length=64)


class UserDeletePayload(BaseModel):
    confirm_phone: str = Field(min_length=1, max_length=20)
    purge_orders: bool = False


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
    socket_remap: dict[str, int] = Field(default_factory=dict)
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
    socket_remap: dict[str, int] = Field(default_factory=dict)
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
    bonus_free_charge_count: int = 0
    bonus_free_charge_granted: int = 0
    credited_yuan: float = 0
    payment_method: str = ""
    status: str
    note: str
    created_at: str
    updated_at: str
    reviewed_at: str = ""
    review_note: str = ""
    reused_pending: bool = False


class WalletLedgerView(BaseModel):
    id: int
    delta_yuan: float
    balance_after: float
    reason: str
    created_at: str


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


def qjpay_build_out_trade_no(request_id: int) -> str:
    return f"rr_{int(request_id)}_{int(datetime.now(UTC).timestamp() * 1000)}"


def qjpay_parse_request_id(out_trade_no: str) -> int:
    match = re.match(r"^rr_(\d+)_", str(out_trade_no or ""))
    return int(match.group(1)) if match else 0


def qjpay_sign(params: dict[str, Any]) -> str:
    filtered = {
        str(k): str(v)
        for k, v in params.items()
        if k not in {"sign", "sign_type"} and v is not None and str(v) != ""
    }
    query = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered))
    raw = f"{query}{QJPAY_KEY}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def qjpay_create_order(
    *,
    pay_type: str,
    out_trade_no: str,
    amount_yuan: float,
    notify_url: str,
    return_url: str,
    title: str,
    client_ip: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "pid": QJPAY_PID,
        "type": pay_type,
        "out_trade_no": out_trade_no,
        "notify_url": notify_url,
        "return_url": return_url,
        "name": title,
        "money": f"{amount_yuan:.2f}",
        "sign_type": "MD5",
        "clientip": client_ip,
        "device": "pc",
        "param": out_trade_no,
    }
    params["sign"] = qjpay_sign(params)
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        f"{QJPAY_API}/mapi.php",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return json.loads(raw) if raw else {}


def qjpay_query_order(out_trade_no: str) -> dict[str, Any]:
    params = {
        "apiid": QJPAY_PID,
        "apikey": QJPAY_KEY,
        "out_trade_no": out_trade_no,
    }
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        f"{QJPAY_API}/qjt.php?act=query_order",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return json.loads(raw) if raw else {}


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
            "script-src 'self' 'unsafe-inline' https:; "
            "frame-src 'self' https:; "
            "connect-src 'self' https:; "
            "object-src 'none'; base-uri 'self'; form-action 'self' https:;"
        )
    return response


def create_admin_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = (now + timedelta(days=ADMIN_SESSION_EXPIRE_DAYS)).isoformat()
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO admin_sessions (token, username, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, username, now.isoformat(), expires_at),
        )
        conn.commit()
    return token


def get_admin_session(token: str) -> sqlite3.Row | None:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT token, username, created_at, expires_at
            FROM admin_sessions
            WHERE token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        expires_at = parse_iso(str(row["expires_at"] or ""))
        if expires_at is not None and expires_at <= datetime.now(UTC):
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return row


def clear_admin_session(token: str) -> None:
    if not token:
        return
    with db_connect() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
        conn.commit()


def require_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_admin_password: str | None = Header(default=None, alias="X-Admin-Password"),
    token: str | None = Query(default=None),
    password: str | None = Query(default=None),
) -> None:
    session_token = str(request.cookies.get(ADMIN_SESSION_COOKIE_NAME) or "").strip()
    if session_token and get_admin_session(session_token) is not None:
        return

    if not ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="admin login required")
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


def expire_timed_out_processing_orders(*, limit: int = PROCESSING_TIMEOUT_SCAN_LIMIT) -> int:
    now = datetime.now(UTC)
    timed_out_ids: list[int] = []
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, updated_at
            FROM orders
            WHERE status = 'PROCESSING'
            ORDER BY updated_at ASC, id ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    for row in rows:
        started_at = parse_iso(str(row["updated_at"] or row["created_at"] or ""))
        if started_at is None:
            continue
        if (now - started_at).total_seconds() >= PROCESSING_TIMEOUT_SECONDS:
            timed_out_ids.append(int(row["id"]))

    expired = 0
    for order_id in timed_out_ids:
        try:
            update_order_result(order_id, "FAILED", PROCESSING_TIMEOUT_MESSAGE)
            expired += 1
        except Exception:
            continue
    return expired


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


def resolve_station_socket_no(station: dict[str, Any], socket_no: int) -> int:
    socket_remap = station.get("socket_remap", {})
    if not isinstance(socket_remap, dict):
        return int(socket_no)
    remapped = optional_int(socket_remap.get(str(int(socket_no))))
    return int(remapped if remapped is not None else socket_no)


def check_order_submission_limits(
    conn: sqlite3.Connection,
    *,
    device_code: str,
    socket_no: int,
) -> str | None:
    if (
        ORDER_RECENT_SUBMIT_COOLDOWN_MINUTES <= 0
        and ORDER_FAILURE_WINDOW_MINUTES <= 0
        and ORDER_FAILURE_THRESHOLD <= 0
        and ORDER_EMPTY_LOAD_COOLDOWN_MINUTES <= 0
    ):
        return None

    rows = conn.execute(
        """
        SELECT status, result_message, created_at, updated_at
        FROM orders
        WHERE device_code = ? AND socket_no = ?
        ORDER BY id DESC
        LIMIT 50
        """,
        (device_code, int(socket_no)),
    ).fetchall()
    return should_block_for_recent_activity(rows, now=datetime.now(UTC))


def recharge_request_row_to_dict(
    row: sqlite3.Row,
    *,
    reused_pending: bool = False,
) -> dict[str, Any]:
    amount_yuan = float(row["amount_yuan"] or 0)
    bonus_free_charge_count = int(row["bonus_free_charge_count"] or 0)
    bonus_free_charge_granted = int(row["bonus_free_charge_granted"] or 0)
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "phone": str(row["phone"] or ""),
        "amount_yuan": amount_yuan,
        "bonus_free_charge_count": bonus_free_charge_count,
        "bonus_free_charge_granted": bonus_free_charge_granted,
        "credited_yuan": amount_yuan,
        "payment_method": str(row["payment_method"] or ""),
        "status": str(row["status"] or ""),
        "note": str(row["note"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "reviewed_at": str(row["reviewed_at"] or ""),
        "review_note": str(row["review_note"] or ""),
        "reused_pending": reused_pending,
    }


def latest_pending_recharge_request(
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM recharge_requests
        WHERE user_id = ? AND status = 'PENDING'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def approved_recharge_count(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    exclude_request_id: int | None = None,
) -> int:
    query = [
        "SELECT COUNT(*) FROM recharge_requests WHERE user_id = ? AND status = 'APPROVED'"
    ]
    params: list[Any] = [int(user_id)]
    if exclude_request_id is not None:
        query.append("AND id != ?")
        params.append(int(exclude_request_id))
    return int(conn.execute(" ".join(query), params).fetchone()[0] or 0)


def has_received_first_recharge_style_bonus(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    exclude_request_id: int | None = None,
) -> bool:
    query = [
        """
        SELECT COUNT(*)
        FROM recharge_requests
        WHERE user_id = ?
          AND status = 'APPROVED'
          AND bonus_free_charge_granted > 0
        """
    ]
    params: list[Any] = [int(user_id)]
    if exclude_request_id is not None:
        query.append("AND id != ?")
        params.append(int(exclude_request_id))
    return int(conn.execute(" ".join(query), params).fetchone()[0] or 0) > 0


def planned_recharge_bonus_free_charge_count(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    amount_yuan: float,
    exclude_request_id: int | None = None,
) -> int:
    amount_yuan = round(float(amount_yuan or 0), 2)
    regular_bonus = recharge_bonus_free_charge_count(amount_yuan)
    already_received_bonus = has_received_first_recharge_style_bonus(
        conn,
        user_id=int(user_id),
        exclude_request_id=exclude_request_id,
    )
    first_recharge_bonus = (
        FIRST_RECHARGE_FREE_CHARGE_BONUS
        if not already_received_bonus and amount_yuan + 1e-9 >= FIRST_RECHARGE_MIN_AMOUNT_YUAN
        else 0
    )
    # Do not stack first-recharge and daily recharge gifts; use the better one only.
    return max(int(regular_bonus), int(first_recharge_bonus))


def same_recharge_request(
    row: sqlite3.Row,
    *,
    amount_yuan: float,
    payment_method: str,
) -> bool:
    row_amount = round(float(row["amount_yuan"] or 0), 2)
    next_amount = round(float(amount_yuan), 2)
    row_method = str(row["payment_method"] or "").strip().lower()
    next_method = str(payment_method or "").strip().lower()
    return row_amount == next_amount and row_method == next_method


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
    allow_stale = ALLOW_STALE_AGENT_SNAPSHOT or PREFER_AGENT_SNAPSHOT
    pushed_snapshot = latest_agent_socket_overview(allow_stale=allow_stale)
    if pushed_snapshot is not None:
        return filter_socket_overview_by_region(pushed_snapshot, region_key)
    if PREFER_AGENT_SNAPSHOT:
        return []
    cached = cached_socket_overview(region_key)
    if cached is not None:
        return cached
    snapshot = compute_live_socket_state_snapshot(region_key=region_key)
    cache_socket_overview(region_key, snapshot)
    return snapshot


def create_recharge_request(
    conn: sqlite3.Connection,
    *,
    user: sqlite3.Row,
    amount_yuan: float,
    payment_method: str,
    note: str,
    dedupe_pending: bool = True,
) -> tuple[sqlite3.Row, bool]:
    amount_yuan = round(float(amount_yuan), 2)
    payment_method = payment_method.strip()
    note = note.strip()
    if dedupe_pending:
        pending = latest_pending_recharge_request(conn, user_id=int(user["id"]))
        if pending is not None:
            if same_recharge_request(
                pending,
                amount_yuan=amount_yuan,
                payment_method=payment_method,
            ):
                return pending, False
            raise HTTPException(
                status_code=409,
                detail=(
                    f"已有待审核充值申请（#{int(pending['id'])}，"
                    f"金额¥{float(pending['amount_yuan'] or 0):.2f}），"
                    "请等待审核后再提交新的充值申请。"
                ),
            )

    ts = now_iso()
    bonus_free_charge_count = planned_recharge_bonus_free_charge_count(
        conn,
        user_id=int(user["id"]),
        amount_yuan=amount_yuan,
    )
    cursor = conn.execute(
        """
        INSERT INTO recharge_requests (
            user_id, phone, amount_yuan, payment_method, status, note,
            bonus_free_charge_count, bonus_free_charge_granted, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'PENDING', ?, ?, 0, ?, ?)
        """,
        (
            int(user["id"]),
            str(user["phone"] or ""),
            amount_yuan,
            payment_method,
            note,
            bonus_free_charge_count,
            ts,
            ts,
        ),
    )
    row = conn.execute("SELECT * FROM recharge_requests WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="failed to create recharge request")
    return row, True


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
        bonus_free_charge_count = planned_recharge_bonus_free_charge_count(
            conn,
            user_id=int(row["user_id"]),
            amount_yuan=amount_yuan,
            exclude_request_id=request_id,
        )
        apply_balance_delta(
            conn,
            user_id=int(row["user_id"]),
            delta_yuan=round(amount_yuan, 2),
            reason=f"recharge_request:{request_id}",
        )
        if bonus_free_charge_count > 0:
            conn.execute(
                """
                UPDATE users
                SET free_charge_count = free_charge_count + ?, updated_at = ?
                WHERE id = ?
                """,
                (int(bonus_free_charge_count), ts, int(row["user_id"])),
            )
        conn.execute(
            """
            UPDATE recharge_requests
            SET bonus_free_charge_count = ?, bonus_free_charge_granted = ?
            WHERE id = ?
            """,
            (int(bonus_free_charge_count), int(bonus_free_charge_count), request_id),
        )
        if bonus_free_charge_count > 0:
            merged_note = review_note.strip()
            bonus_note = f"充值赠送免服务费 {int(bonus_free_charge_count)} 次"
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
            SELECT id, user_id, amount_yuan, payment_mode, balance_deducted, balance_refunded,
                   status, free_charge_used, vendor_order_id
            FROM orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return
        previous_status = str(row["status"] or "").strip().upper()
        free_charge_used = int(row["free_charge_used"] or 0)

        stored_vendor_order_id = str(row["vendor_order_id"] or "")
        next_vendor_order_id = vendor_order_id or stored_vendor_order_id

        conn.execute(
            """
            UPDATE orders
            SET status = ?, result_message = ?, vendor_order_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, message, next_vendor_order_id, now_iso(), order_id),
        )

        if (
            status == "FAILED"
            and previous_status != "FAILED"
            and free_charge_used
            and row["user_id"] is not None
        ):
            # Give back the reserved free-charge voucher when the order fails.
            conn.execute(
                "UPDATE users SET free_charge_count = free_charge_count + 1, updated_at = ? WHERE id = ?",
                (now_iso(), int(row["user_id"])),
            )

        if (
            status == "SUCCESS"
            and row["payment_mode"] == "balance"
            and int(row["balance_deducted"] or 0) == 0
        ):
            charge_amount = order_total_cost_yuan(float(row["amount_yuan"] or 0), free_charge_used)
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
            refund_amount = order_total_cost_yuan(float(row["amount_yuan"] or 0), free_charge_used)
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


def latest_agent_socket_overview(*, allow_stale: bool = False) -> list[dict[str, Any]] | None:
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
    if (
        not allow_stale
        and (datetime.now(UTC) - captured_at).total_seconds() > AGENT_SOCKET_OVERVIEW_EXPIRE_SECONDS
    ):
        return None
    try:
        snapshot = json.loads(str(row["snapshot_json"] or "[]"))
    except Exception:
        return None
    return snapshot if isinstance(snapshot, list) else None


def get_socket_service_status() -> dict[str, Any]:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT agent_name, captured_at, updated_at
            FROM agent_socket_overview
            ORDER BY captured_at DESC, updated_at DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return {
            "socket_service_online": False,
            "socket_service_last_seen_at": "",
            "socket_service_agent_name": "",
        }

    captured_at = parse_iso(str(row["captured_at"] or ""))
    online = False
    if captured_at is not None:
        online = (datetime.now(UTC) - captured_at).total_seconds() <= AGENT_SOCKET_OVERVIEW_EXPIRE_SECONDS

    return {
        "socket_service_online": online,
        "socket_service_last_seen_at": str(row["captured_at"] or ""),
        "socket_service_agent_name": str(row["agent_name"] or ""),
    }


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
    socket_status = get_socket_service_status()
    live_processor_online = worker_alive if WORKER_ENABLED else agent_status["agent_online"]
    allow_order_submission = not REQUIRE_AGENT_ONLINE_FOR_ORDERS or live_processor_online
    qr_name = "wechat_qr.png"
    qr_path = WEB_ASSETS_DIR / qr_name
    payment_qr_url = f"/assets/{qr_name}" if qr_path.exists() else ""
    group_qr_name = "wechat_group_qr.png"
    group_qr_path = WEB_ASSETS_DIR / group_qr_name
    wechat_group_qr_url = f"/assets/{group_qr_name}" if group_qr_path.exists() else ""
    manual_recharge_enabled = bool(payment_qr_url)
    return {
        "service_mode": service_mode,
        "worker_enabled": WORKER_ENABLED,
        "worker_alive": worker_alive,
        "require_agent_online_for_orders": REQUIRE_AGENT_ONLINE_FOR_ORDERS,
        "accepting_orders": live_processor_online,
        "allow_order_submission": allow_order_submission,
        "order_pay_mode": ORDER_PAY_MODE,
        "codepay_enabled": CODEPAY_ENABLED,
        "payment_mode": PAYMENT_MODE,
        "payment_bridge_url": PAYMENT_BRIDGE_URL,
        "socket_overview_bridge_url": SOCKET_OVERVIEW_BRIDGE_URL,
        "payment_token_required": PAYMENT_MODE == "token",
        "balance_enabled": PAYMENT_MODE == "balance",
        "balance_refund_on_fail": BALANCE_REFUND_ON_FAIL,
        "payment_qr_url": payment_qr_url,
        "wechat_group_qr_url": wechat_group_qr_url,
        "manual_recharge_enabled": manual_recharge_enabled,
        "manual_payment_contact": MANUAL_PAYMENT_CONTACT,
        "manual_payment_instructions": MANUAL_PAYMENT_INSTRUCTIONS or DEFAULT_RECHARGE_QR_NOTE,
        "recharge_qr_note": MANUAL_PAYMENT_INSTRUCTIONS or DEFAULT_RECHARGE_QR_NOTE,
        **agent_status,
        **socket_status,
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
def index(request: Request) -> HTMLResponse:
    if not HTML_PATH.exists():
        return HTMLResponse("<h3>mobile_order.html not found</h3>", status_code=404)
    response = HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    upsert_site_visitor(request, response, path="/")
    return response


@app.get("/assets/{name}")
def assets(name: str) -> FileResponse:
    # Basic allowlist to avoid path traversal and serving arbitrary files.
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404, detail="asset not found")
    allowlist = {"wechat_qr.png", "wechat_group_qr.png"}
    if name.lower() not in allowlist:
        raise HTTPException(status_code=404, detail="asset not found")

    file_path = WEB_ASSETS_DIR / name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path=file_path)


def render_admin_html(path: Path) -> str:
    if not path.exists():
        return f"<h3>{path.name} not found</h3>"
    return path.read_text(encoding="utf-8")


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> str:
    return render_admin_html(ADMIN_HTML_PATH)


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders_page() -> str:
    return render_admin_html(ADMIN_HTML_PATH)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page() -> str:
    return render_admin_html(ADMIN_USERS_HTML_PATH)


@app.post("/api/admin/login")
def admin_login(payload: AdminLoginPayload, response: Response) -> dict[str, Any]:
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="admin password not configured")
    if payload.username.strip() != ADMIN_USERNAME or payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="invalid admin username or password")
    token = create_admin_session(ADMIN_USERNAME)
    response.set_cookie(
        ADMIN_SESSION_COOKIE_NAME,
        token,
        max_age=ADMIN_SESSION_EXPIRE_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "username": ADMIN_USERNAME}


@app.post("/api/admin/logout")
def admin_logout(request: Request, response: Response) -> dict[str, Any]:
    token = str(request.cookies.get(ADMIN_SESSION_COOKIE_NAME) or "").strip()
    clear_admin_session(token)
    response.delete_cookie(ADMIN_SESSION_COOKIE_NAME, samesite="lax")
    return {"ok": True}


@app.get("/api/admin/me")
def admin_me(request: Request) -> dict[str, Any]:
    token = str(request.cookies.get(ADMIN_SESSION_COOKIE_NAME) or "").strip()
    session = get_admin_session(token)
    if session is None:
        raise HTTPException(status_code=401, detail="admin login required")
    return {"ok": True, "username": str(session["username"] or ADMIN_USERNAME)}


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


class AgentConsumeRecordsPayload(BaseModel):
    captured_at: str = ""
    records: list[dict[str, Any]] = Field(default_factory=list)


@app.post("/api/agent/consume-records", dependencies=[Depends(require_agent)])
def agent_consume_records(payload: AgentConsumeRecordsPayload) -> dict[str, Any]:
    set_consume_record_snapshot(payload.records or [], payload.captured_at or now_iso())
    refunded = 0
    try:
        refunded = auto_refund_no_load_orders(payload.records or [])
    except Exception:
        refunded = 0
    return {"ok": True, "count": len(payload.records or []), "auto_refunded": refunded}


@app.get("/api/realtime/using-orders", dependencies=[Depends(require_user)])
def realtime_using_orders() -> dict[str, Any]:
    member_ids = configured_realtime_using_member_ids()
    if not member_ids:
        return {"ok": False, "message": "配置缺少 member_id", "items": []}
    using_orders, using_orders_message = merge_using_orders_for_member_ids(member_ids)
    if using_orders_message:
        return {"ok": False, "message": using_orders_message, "items": []}

    items: list[dict[str, Any]] = []
    for (device_code, socket_no), data in using_orders.items():
        items.append(
            {
                "device_code": device_code,
                "socket_no": socket_no,
                "station_name": optional_text(data.get("station_name")),
                "detail": optional_text(data.get("detail")),
                "start_time": optional_text(data.get("start_time")),
                "end_time": optional_text(data.get("end_time")),
                "remain_seconds": data.get("remain_seconds"),
            }
        )
    items.sort(key=lambda item: (item.get("device_code", ""), int(item.get("socket_no") or 0)))
    return {"ok": True, "message": using_orders_message, "items": items}


@app.get("/api/realtime/station-check", dependencies=[Depends(require_user)])
def realtime_station_check(
    device_code: str = Query(min_length=1, max_length=64),
    device_ck: str | None = Query(default=None, max_length=64),
    socket_count: int = Query(default=10, ge=1, le=20),
    station_name: str | None = Query(default="", max_length=120),
) -> dict[str, Any]:
    status_member_id = configured_status_member_id()
    using_orders: dict[tuple[str, int], dict[str, Any]] = {}
    using_orders_message = ""
    using_member_ids = configured_realtime_using_member_ids()
    if using_member_ids:
        using_orders, using_orders_message = merge_using_orders_for_member_ids(using_member_ids)

    station = {
        "device_code": device_code,
        "device_ck": optional_text(device_ck),
        "socket_count": socket_count,
        "disabled_sockets": [],
    }

    if station["device_ck"]:
        try:
            station_result = fetch_station_realtime(station, status_member_id or "")
        except Exception as err:
            station_result = {"ok": False, "message": format_realtime_error(err), "products": []}
    else:
        has_using_order = any(code == str(device_code) for code, _ in using_orders)
        if not status_member_id:
            message = "配置缺少 member_id"
        elif has_using_order:
            message = "缺少 device_ck；仅能识别已配置账号充电中的插座"
        else:
            message = "缺少 device_ck"
        station_result = {"ok": False, "message": message, "products": []}

    sockets, query_message = build_station_sockets(station, station_result, using_orders)
    return {
        "ok": True,
        "device_code": device_code,
        "station_name": station_name or "",
        "realtime_ok": bool(station_result.get("ok")),
        "query_message": query_message if (not station_result.get("ok") or station_result.get("cached")) else "",
        "using_orders_message": using_orders_message,
        "sockets": sockets,
    }


@app.post("/api/auth/register", response_model=AuthResponse)
def register(payload: UserRegister, request: Request) -> AuthResponse:
    phone = normalize_phone(payload.phone)
    password_hash = hash_password(payload.password)
    ts = now_iso()

    with db_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        block_reason = validate_registration_risk(conn, request)
        if block_reason:
            log_registration_attempt(
                conn,
                phone=phone,
                request=request,
                status="BLOCKED",
                reason=block_reason,
            )
            conn.commit()
            detail = "当前网络环境注册过于频繁，请稍后再试"
            raise HTTPException(status_code=429, detail=detail)
        exists = conn.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
        if exists is not None:
            log_registration_attempt(
                conn,
                phone=phone,
                request=request,
                status="REJECTED",
                reason="phone_exists",
            )
            conn.commit()
            raise HTTPException(status_code=409, detail="phone already registered")

        cursor = conn.execute(
            """
            INSERT INTO users (phone, password_hash, free_charge_count, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?)
            """,
            (phone, password_hash, ts, ts),
        )
        log_registration_attempt(
            conn,
            phone=phone,
            request=request,
            status="SUCCESS",
            reason="registered",
        )
        conn.commit()
        user = conn.execute(
            "SELECT id, phone, balance_yuan, free_charge_count, created_at FROM users WHERE id = ?",
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
            "SELECT id, phone, password_hash, balance_yuan, free_charge_count, created_at FROM users WHERE phone = ?",
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
            free_charge_count=int(user["free_charge_count"] or 0),
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
        free_charge_count=int(user["free_charge_count"] or 0),
        created_at=user["created_at"],
    )


@app.get("/api/me/orders", response_model=list[OrderView])
def my_orders(
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(require_user),
) -> list[OrderView]:
    expire_timed_out_processing_orders()
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()
    row_by_id = {int(row["id"]): row for row in rows}
    row_by_id = {int(row["id"]): row for row in rows}
    items = [row_to_dict(row) for row in rows]
    using_orders, realtime_by_device, using_orders_message = build_realtime_snapshot_for_orders(rows)
    apply_realtime_status_for_orders(items, using_orders, realtime_by_device, using_orders_message)
    consume_message = attach_official_details_to_order_items(items, row_by_id, limit=limit)
    if consume_message:
        for item in items:
            if not item.get("official_detail"):
                item["official_message"] = consume_message
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


@app.get("/api/me/wallet-ledger", response_model=list[WalletLedgerView])
def my_wallet_ledger(
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(require_user),
) -> list[WalletLedgerView]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, delta_yuan, balance_after, reason, created_at
            FROM wallet_ledger
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user["id"], limit),
        ).fetchall()
    return [
        WalletLedgerView(
            id=row["id"],
            delta_yuan=float(row["delta_yuan"] or 0),
            balance_after=float(row["balance_after"] or 0),
            reason=str(row["reason"] or ""),
            created_at=str(row["created_at"] or ""),
        )
        for row in rows
    ]


@app.post("/api/me/recharge-requests", response_model=RechargeRequestView)
def create_my_recharge_request(
    payload: RechargeRequestCreate,
    user: sqlite3.Row = Depends(require_user),
) -> RechargeRequestView:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row, created = create_recharge_request(
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
    return RechargeRequestView(
        **recharge_request_row_to_dict(row, reused_pending=not created)
    )


@app.post("/api/recharge/create")
async def bridge_recharge_create(
    request: Request,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    payload = await request.json()
    amount_yuan = float(payload.get("amount_yuan") or 0)
    pay_type = str(payload.get("pay_type") or "wxpay").strip().lower()
    note = str(payload.get("note") or "").strip()
    if amount_yuan <= 0:
        raise HTTPException(status_code=400, detail="invalid amount_yuan")
    if pay_type not in {"wxpay", "alipay"}:
        raise HTTPException(status_code=400, detail="invalid pay_type")

    if QJPAY_ENABLED:
        payment_method = "wxpay_auto" if pay_type == "wxpay" else "alipay_auto"
        with db_connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row, _created = create_recharge_request(
                    conn,
                    user=user,
                    amount_yuan=amount_yuan,
                    payment_method=payment_method,
                    note=note or "qjpay recharge",
                    dedupe_pending=False,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        request_id = int(row["id"])
        out_trade_no = qjpay_build_out_trade_no(request_id)
        notify_url = str(request.url_for("qjpay_recharge_notify"))
        return_url = str(request.base_url)
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or "127.0.0.1"
        params: dict[str, Any] = {
            "pid": QJPAY_PID,
            "type": pay_type,
            "out_trade_no": out_trade_no,
            "notify_url": notify_url,
            "return_url": return_url,
            "name": "Recharge Topup",
            "money": f"{amount_yuan:.2f}",
            "sign_type": "MD5",
            "clientip": client_ip,
            "device": "pc",
            "param": out_trade_no,
        }
        if QJPAY_CHANNEL_ID:
            params["channel_id"] = QJPAY_CHANNEL_ID
        params["sign"] = qjpay_sign(params)

        return {
            "ok": True,
            "recharge_request_id": request_id,
            "out_trade_no": out_trade_no,
            "form_action": f"{QJPAY_API}/submit.php",
            "form_fields": params,
            "pay_url": "",
            "qrcode": "",
            "provider": {"mode": "form_post"},
        }

    upstream = payment_bridge_upstream()
    if not upstream:
        raise HTTPException(status_code=503, detail="支付中转未配置")

    body = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json"}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth

    try:
        req = urllib.request.Request(
            f"{upstream}/api/recharge/create",
            data=body,
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="ignore")
        detail = ""
        try:
            payload = json.loads(raw) if raw else {}
            detail = payload.get("detail") or payload.get("msg") or payload.get("raw") or ""
        except Exception:
            detail = raw
        raise HTTPException(status_code=err.code, detail=detail or "支付中转请求失败")
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"支付中转不可用: {err}")

    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {"raw": raw}


@app.get("/api/recharge/status")
def bridge_recharge_status(
    out_trade_no: str = Query(min_length=1),
) -> dict[str, Any]:
    if QJPAY_ENABLED:
        request_id = qjpay_parse_request_id(out_trade_no)
        return {
            "ok": True,
            "out_trade_no": out_trade_no,
            "recharge_request_id": request_id or None,
            "paid": False,
            "provider": {"mode": "notify_only"},
        }

    upstream = payment_bridge_upstream()
    if not upstream:
        raise HTTPException(status_code=503, detail="支付中转未配置")

    url = f"{upstream}/api/recharge/status?out_trade_no={urllib.parse.quote(out_trade_no)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="ignore")
        detail = ""
        try:
            payload = json.loads(raw) if raw else {}
            detail = payload.get("detail") or payload.get("msg") or payload.get("raw") or ""
        except Exception:
            detail = raw
        raise HTTPException(status_code=err.code, detail=detail or "支付中转请求失败")
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"支付中转不可用: {err}")

    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {"raw": raw}


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
    amount_yuan = float(payload.amount_yuan)
    total_cost = total_cost_yuan(amount_yuan)
    free_charge_used = 0
    station = find_station(payload.station_id, payload.device_code)
    order_socket_no = int(payload.socket_no)
    if station is not None:
        validate_station_socket(station, order_socket_no)
        order_socket_no = resolve_station_socket_no(station, order_socket_no)
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
        block_message = check_order_submission_limits(
            conn,
            device_code=device_code,
            socket_no=order_socket_no,
        )
        if block_message:
            raise HTTPException(status_code=429, detail=block_message)

        try:
            conn.execute("BEGIN IMMEDIATE")

            if payment_mode == "balance":
                balance_row = conn.execute(
                    "SELECT balance_yuan, free_charge_count FROM users WHERE id = ?",
                    (user["id"],),
                ).fetchone()
                if balance_row is None:
                    raise HTTPException(status_code=404, detail="user not found")
                current_balance = float(balance_row["balance_yuan"] or 0)
                free_charge_count = int(balance_row["free_charge_count"] or 0)
                free_charge_used = 1 if free_charge_count > 0 else 0
                total_cost = order_total_cost_yuan(amount_yuan, free_charge_used)
                if current_balance + 1e-9 < total_cost:
                    raise HTTPException(status_code=402, detail="余额不足，请先充值")
                if free_charge_used:
                    # Reserve the free-charge voucher now to prevent concurrent overuse.
                    updated = conn.execute(
                        """
                        UPDATE users
                        SET free_charge_count = free_charge_count - 1, updated_at = ?
                        WHERE id = ? AND free_charge_count > 0
                        """,
                        (ts, int(user["id"])),
                    ).rowcount
                    if updated != 1:
                        free_charge_used = 0
                        total_cost = order_total_cost_yuan(amount_yuan, free_charge_used)
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
                        free_charge_used,
                        created_at, updated_at
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', '', '',
                     ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    device_code,
                    phone,
                    0,
                    station_name,
                    device_code,
                    order_socket_no,
                    amount_yuan,
                    payload.remark,
                    payment_mode,
                    payment_token,
                    balance_deducted,
                    0,
                    free_charge_used,
                    ts,
                    ts,
                ),
            )
            order_id = int(cursor.lastrowid)

            if payment_mode == "balance" and total_cost > 0:
                apply_balance_delta(
                    conn,
                    user_id=int(user["id"]),
                    delta_yuan=-total_cost,
                    reason=f"order_reserve:{order_id}",
                )
                conn.execute(
                    "UPDATE orders SET balance_deducted = 1 WHERE id = ?",
                    (order_id,),
                )

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
    expire_timed_out_processing_orders()
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
    expire_timed_out_processing_orders()
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
    row_by_id = {int(row["id"]): row for row in rows}
    items = [row_to_dict(row) for row in rows]
    using_orders, realtime_by_device, using_orders_message = build_realtime_snapshot_for_orders(rows)
    apply_realtime_status_for_orders(items, using_orders, realtime_by_device, using_orders_message)
    consume_message = attach_official_details_to_order_items(items, row_by_id, limit=limit)
    if consume_message:
        for item in items:
            if not item.get("official_detail"):
                item["official_message"] = consume_message

    return [OrderView(**item) for item in items]


@app.get("/api/admin/users", response_model=list[UserView], dependencies=[Depends(require_admin)])
def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    q: str | None = Query(default=None, max_length=50),
    recharged_only: bool = Query(default=False),
) -> list[UserView]:
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append("phone LIKE ?")
        params.append(f"%{q.strip()}%")
    if recharged_only:
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM recharge_requests
                WHERE recharge_requests.user_id = users.id
                  AND recharge_requests.status = 'APPROVED'
            )
            """
        )
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                users.id,
                users.phone,
                users.balance_yuan,
                users.free_charge_count,
                users.user_note,
                users.created_at,
                (
                    SELECT COUNT(*)
                    FROM recharge_requests
                    WHERE recharge_requests.user_id = users.id
                      AND recharge_requests.status = 'APPROVED'
                ) AS recharge_count,
                (
                    SELECT MAX(orders.created_at)
                    FROM orders
                    WHERE orders.user_id = users.id
                       OR (
                            orders.user_id IS NULL
                            AND orders.phone = users.phone
                            AND orders.created_at >= users.created_at
                       )
                ) AS last_order_at
            FROM users
            {where_sql}
            ORDER BY users.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        UserView(
            id=row["id"],
            phone=row["phone"],
            balance_yuan=float(row["balance_yuan"] or 0),
            free_charge_count=int(row["free_charge_count"] or 0),
            user_note=str(row["user_note"] or ""),
            recharge_count=int(row["recharge_count"] or 0),
            created_at=row["created_at"],
            last_order_at=str(row["last_order_at"] or ""),
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


@app.post("/api/admin/users/{user_id}/balance/set", dependencies=[Depends(require_admin)])
def set_user_balance(user_id: int, payload: BalanceSetPayload) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT balance_yuan FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="user not found")
            current_balance = float(row["balance_yuan"] or 0)
            target_balance = round(float(payload.balance_yuan), 2)
            delta_yuan = round(target_balance - current_balance, 2)
            if abs(delta_yuan) > 1e-9:
                new_balance = apply_balance_delta(
                    conn,
                    user_id=user_id,
                    delta_yuan=delta_yuan,
                    reason=payload.reason or "admin_set_balance",
                )
            else:
                new_balance = current_balance
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "ok": True,
        "user_id": user_id,
        "balance_yuan": new_balance,
        "delta_yuan": delta_yuan,
    }


@app.post("/api/admin/users/{user_id}/free-charge", dependencies=[Depends(require_admin)])
def adjust_user_free_charge(user_id: int, payload: FreeChargeAdjustPayload) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT id FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            conn.execute(
                "UPDATE users SET free_charge_count = ?, updated_at = ? WHERE id = ?",
                (int(payload.free_charge_count), now_iso(), user_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "ok": True,
        "user_id": user_id,
        "free_charge_count": int(payload.free_charge_count),
    }


@app.post("/api/admin/users/{user_id}/note", dependencies=[Depends(require_admin)])
def update_user_note(user_id: int, payload: UserNotePayload) -> dict[str, Any]:
    note = payload.user_note.strip()
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT id FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            conn.execute(
                "UPDATE users SET user_note = ?, updated_at = ? WHERE id = ?",
                (note, now_iso(), user_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "ok": True,
        "user_id": user_id,
        "user_note": note,
    }


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


@app.post("/api/admin/users/{user_id}/delete", dependencies=[Depends(require_admin)])
def delete_user_account(user_id: int, payload: UserDeletePayload) -> dict[str, Any]:
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT id, phone FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")

            confirm_phone = normalize_phone(payload.confirm_phone)
            if str(user["phone"] or "") != confirm_phone:
                raise HTTPException(status_code=400, detail="phone confirmation mismatch")

            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM payment_tokens WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM wallet_ledger WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM pending_payments WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM recharge_requests WHERE user_id = ?", (user_id,))

            orders_deleted = 0
            orders_anonymized = 0
            if payload.purge_orders:
                orders_deleted = conn.execute(
                    "DELETE FROM orders WHERE user_id = ?",
                    (user_id,),
                ).rowcount
            else:
                orders_anonymized = conn.execute(
                    "UPDATE orders SET user_id = NULL WHERE user_id = ?",
                    (user_id,),
                ).rowcount

            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "ok": True,
        "user_id": user_id,
        "phone": str(user["phone"] or ""),
        "orders_deleted": orders_deleted,
        "orders_anonymized": orders_anonymized,
    }


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


def metrics_repeat_within_days(conn: sqlite3.Connection, days: int = 7) -> int:
    rows = conn.execute(
        """
        SELECT user_id, created_at
        FROM orders
        WHERE user_id IS NOT NULL
        ORDER BY user_id ASC, created_at ASC, id ASC
        """
    ).fetchall()
    first_order_at: dict[int, datetime] = {}
    repeated_users: set[int] = set()
    for row in rows:
        user_id = int(row["user_id"] or 0)
        if user_id <= 0:
            continue
        created_at = parse_iso(str(row["created_at"] or ""))
        if created_at is None:
            continue
        first_seen = first_order_at.get(user_id)
        if first_seen is None:
            first_order_at[user_id] = created_at
            continue
        if created_at <= first_seen:
            continue
        if created_at - first_seen <= timedelta(days=days):
            repeated_users.add(user_id)
    return len(repeated_users)


@app.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats() -> dict[str, Any]:
    auto_failed_processing = expire_timed_out_processing_orders()
    with db_connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'PENDING'").fetchone()[0]
        processing = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'PROCESSING'").fetchone()[0]
        success = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'SUCCESS'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'FAILED'").fetchone()[0]
        recharge_pending = conn.execute(
            "SELECT COUNT(*) FROM recharge_requests WHERE status = 'PENDING'"
        ).fetchone()[0]
        visit_count = conn.execute("SELECT COUNT(*) FROM site_visitors").fetchone()[0]
        register_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        first_order_count = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM orders WHERE user_id IS NOT NULL"
        ).fetchone()[0]
        recharge_user_count = conn.execute(
            """
            SELECT COUNT(DISTINCT user_id)
            FROM recharge_requests
            WHERE status = 'APPROVED'
            """
        ).fetchone()[0]
        repeat_7d_count = metrics_repeat_within_days(conn, days=7)
    return {
        "ok": True,
        "gateway_mode": gateway.mode,
        "total": total,
        "pending": pending,
        "processing": processing,
        "success": success,
        "failed": failed,
        "recharge_pending": recharge_pending,
        "visit_count": visit_count,
        "register_count": register_count,
        "first_order_count": first_order_count,
        "recharge_user_count": recharge_user_count,
        "repeat_7d_count": repeat_7d_count,
        "processing_timeout_seconds": PROCESSING_TIMEOUT_SECONDS,
        "auto_failed_processing": auto_failed_processing,
        **get_service_status(),
    }


@app.get("/api/admin/realtime-snapshot-config", dependencies=[Depends(require_admin)])
def admin_realtime_snapshot_config() -> dict[str, Any]:
    stations = load_stations()
    return {
        "ok": True,
        "time": now_iso(),
        "member_id": configured_charge_member_id(),
        "member_id_status": configured_status_member_id(),
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
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, user_id, status, free_charge_used, amount_yuan,
                       payment_mode, balance_deducted, balance_refunded
                FROM orders
                WHERE id = ?
                """,
                (order_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="order not found")

            previous_status = str(row["status"] or "").strip().upper()
            if previous_status not in {"FAILED", "PROCESSING"}:
                raise HTTPException(status_code=409, detail="only FAILED or PROCESSING orders can be retried")
            free_charge_used = int(row["free_charge_used"] or 0)
            amount_yuan = float(row["amount_yuan"] or 0)
            payment_mode = str(row["payment_mode"] or "").strip().lower()
            balance_deducted = int(row["balance_deducted"] or 0)
            balance_refunded = int(row["balance_refunded"] or 0)
            user_id = row["user_id"]
            if previous_status == "FAILED" and free_charge_used and user_id is not None:
                # The failure handler returns the voucher. Reserve it again for this retry if possible.
                updated = conn.execute(
                    """
                    UPDATE users
                    SET free_charge_count = free_charge_count - 1, updated_at = ?
                    WHERE id = ? AND free_charge_count > 0
                    """,
                    (now_iso(), int(user_id)),
                ).rowcount
                if updated != 1:
                    # No voucher left anymore, disable it for this order to avoid undercharging.
                    conn.execute(
                        "UPDATE orders SET free_charge_used = 0, updated_at = ? WHERE id = ?",
                        (now_iso(), order_id),
                    )
                    free_charge_used = 0

            if (
                previous_status == "FAILED"
                and payment_mode == "balance"
                and user_id is not None
                and balance_deducted == 1
                and balance_refunded == 1
            ):
                retry_charge_amount = order_total_cost_yuan(amount_yuan, free_charge_used)
                apply_balance_delta(
                    conn,
                    user_id=int(user_id),
                    delta_yuan=-retry_charge_amount,
                    reason=f"order_retry_reserve:{order_id}",
                )
                conn.execute(
                    "UPDATE orders SET balance_refunded = 0, updated_at = ? WHERE id = ?",
                    (now_iso(), order_id),
                )

            conn.execute(
                """
                UPDATE orders
                SET status = 'PENDING', result_message = '', vendor_order_id = '',
                    official_order_id = '', official_detail_json = '', official_detail_updated_at = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso(), order_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
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

    actual_socket_no = int(payload.socket_no)
    station = find_station("", payload.device_code)
    if station is not None:
        validate_station_socket(station, actual_socket_no)
        actual_socket_no = resolve_station_socket_no(station, actual_socket_no)

    pay_id = secrets.token_urlsafe(16)
    ts = now_iso()
    expires_at = datetime.fromtimestamp(
        datetime.now(UTC).timestamp() + 600, UTC
    ).isoformat()
    service_fee = service_fee_yuan(payload.amount_yuan)

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
                actual_socket_no, payload.amount_yuan, payload.remark,
                service_fee, payload.pay_type, ts, expires_at,
            ),
        )
        conn.commit()

    notify_url = f"https://icenorth.pythonanywhere.com/api/payment/notify"
    return_url = f"https://icenorth.pythonanywhere.com/"

    try:
        result = codepay_create(
            out_trade_no=pay_id,
            money=f"{service_fee:.2f}",
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
        "amount": service_fee,
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


@app.post("/api/recharge/notify")
async def qjpay_recharge_notify(request: Request) -> str:
    if not QJPAY_ENABLED:
        return "success"
    body = await request.body()
    params = dict(urllib.parse.parse_qsl(body.decode("utf-8", errors="ignore")))
    append_qjpay_log(f"notify params: {json.dumps(params, ensure_ascii=False)}")
    if not params:
        return "fail"
    received_sign = str(params.get("sign") or "")
    expected = qjpay_sign(params)
    if received_sign.lower() != expected.lower():
        append_qjpay_log("notify sign verify failed")
        return "fail"
    if str(params.get("trade_status") or "") != "TRADE_SUCCESS":
        return "success"
    out_trade_no = str(params.get("out_trade_no") or "")
    request_id = qjpay_parse_request_id(out_trade_no)
    if not request_id:
        append_qjpay_log(f"notify invalid out_trade_no: {out_trade_no}")
        return "fail"
    with db_connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            review_recharge_request(
                conn,
                request_id=request_id,
                approve=True,
                review_note="qjpay auto notify",
            )
            conn.commit()
        except HTTPException as err:
            conn.rollback()
            if err.status_code not in {409, 404}:
                raise
        except Exception:
            conn.rollback()
            raise
    append_qjpay_log(f"notify approved recharge_request_id={request_id}")
    return "success"


@app.get("/api/recharge/notify")
def qjpay_recharge_notify_probe() -> dict[str, Any]:
    return {"ok": True, "method": "POST required"}


@app.get("/api/admin/qjpay/notify-log", dependencies=[Depends(require_admin)])
def admin_qjpay_notify_log(
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    log_path = RUNTIME_DIR / "qjpay_notify.log"
    if not log_path.exists():
        return {"ok": True, "lines": []}
    content = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return {"ok": True, "lines": content[-limit:]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
