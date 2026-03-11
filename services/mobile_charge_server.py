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
import urllib.request
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

try:
    from services.project_paths import CONFIG_DIR, RUNTIME_DIR, WEB_ASSETS_DIR
except ImportError:
    from project_paths import CONFIG_DIR, RUNTIME_DIR, WEB_ASSETS_DIR

DB_PATH = RUNTIME_DIR / "orders.db"
HTML_PATH = WEB_ASSETS_DIR / "mobile_order.html"
ADMIN_HTML_PATH = WEB_ASSETS_DIR / "admin_orders.html"
GATEWAY_CONFIG_PATH = CONFIG_DIR / "gateway_config.json"
STATIONS_PATH = CONFIG_DIR / "stations.json"
POLL_INTERVAL_SECONDS = float(os.getenv("ORDER_POLL_INTERVAL_SECONDS", "2"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "1").lower() not in {"0", "false", "no"}
SESSION_EXPIRE_DAYS = int(os.getenv("SESSION_EXPIRE_DAYS", "30"))
AGENT_HEARTBEAT_EXPIRE_SECONDS = max(15, int(os.getenv("AGENT_HEARTBEAT_EXPIRE_SECONDS", "45")))
REQUIRE_AGENT_ONLINE_FOR_ORDERS = os.getenv("REQUIRE_AGENT_ONLINE_FOR_ORDERS", "0").lower() in {
    "1",
    "true",
    "yes",
}
PAYMENT_MODE = os.getenv("PAYMENT_MODE", "disabled").strip().lower()
PAYMENT_TOKEN_SECRET = os.getenv("PAYMENT_TOKEN_SECRET", "").strip()
PAYMENT_TOKEN_TTL_SECONDS = int(os.getenv("PAYMENT_TOKEN_TTL_SECONDS", "900"))
BALANCE_REFUND_ON_FAIL = os.getenv("BALANCE_REFUND_ON_FAIL", "1").lower() in {"1", "true", "yes"}
if PAYMENT_MODE not in {"disabled", "balance", "token"}:
    PAYMENT_MODE = "disabled"


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


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", phone)
    if len(digits) < 6 or len(digits) > 20:
        raise HTTPException(status_code=422, detail="invalid phone number")
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
    if not STATIONS_PATH.exists():
        return []
    raw = STATIONS_PATH.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    stations: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        device_code = str(item.get("device_code", item.get("sn", ""))).strip()
        if not name or not device_code:
            continue
        station_id = str(item.get("id", device_code)).strip()
        socket_count = int(item.get("socket_count", item.get("total", 10)) or 10)
        address = str(item.get("address", "")).strip()
        stations.append(
            {
                "id": station_id,
                "name": name,
                "device_code": device_code,
                "socket_count": max(1, min(socket_count, 20)),
                "address": address,
            }
        )
    return stations


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
        ensure_user_columns(conn)
        ensure_order_columns(conn)
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


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "phone": row["phone"],
        "station_name": row["station_name"],
        "device_code": row["device_code"],
        "socket_no": row["socket_no"],
        "amount_yuan": row["amount_yuan"],
        "remark": row["remark"],
        "status": row["status"],
        "result_message": row["result_message"],
        "vendor_order_id": row["vendor_order_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class OrderCreate(BaseModel):
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


class StationView(BaseModel):
    id: str
    name: str
    device_code: str
    socket_count: int = 10
    address: str = ""


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


def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    token: str | None = Query(default=None),
) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="admin token not configured")
    candidate = x_admin_token or token
    if candidate != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")


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


def update_order_result(order_id: int, status: str, message: str, vendor_order_id: str = "") -> None:
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
            status == "FAILED"
            and BALANCE_REFUND_ON_FAIL
            and row["payment_mode"] == "balance"
            and int(row["balance_deducted"] or 0) == 1
            and int(row["balance_refunded"] or 0) == 0
        ):
            apply_balance_delta(
                conn,
                user_id=int(row["user_id"]),
                delta_yuan=float(row["amount_yuan"]),
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
    return {
        "service_mode": service_mode,
        "worker_enabled": WORKER_ENABLED,
        "worker_alive": worker_alive,
        "require_agent_online_for_orders": REQUIRE_AGENT_ONLINE_FOR_ORDERS,
        "accepting_orders": live_processor_online,
        "allow_order_submission": allow_order_submission,
        "payment_mode": PAYMENT_MODE,
        "payment_token_required": PAYMENT_MODE == "token",
        "balance_enabled": PAYMENT_MODE == "balance",
        "balance_refund_on_fail": BALANCE_REFUND_ON_FAIL,
        "payment_qr_url": payment_qr_url,
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


@app.get("/api/stations", response_model=list[StationView])
def list_stations(q: str | None = Query(default=None, max_length=100)) -> list[StationView]:
    stations = load_stations()
    if q:
        query = q.strip().lower()
        stations = [
            station
            for station in stations
            if query in station["name"].lower() or query in station["device_code"].lower()
        ]
    return [StationView(**station) for station in stations[:200]]


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
    return [OrderView(**row_to_dict(row)) for row in rows]


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
                if current_balance + 1e-9 < float(payload.amount_yuan):
                    raise HTTPException(status_code=402, detail="余额不足，请先充值")
                apply_balance_delta(
                    conn,
                    user_id=int(user["id"]),
                    delta_yuan=-float(payload.amount_yuan),
                    reason=f"order_payment:{user['id']}",
                )
                balance_deducted = 1
            elif payment_mode == "token":
                if not payment_token:
                    raise HTTPException(status_code=400, detail="支付码不能为空")
                validate_payment_token(
                    conn,
                    user_id=int(user["id"]),
                    amount_yuan=float(payload.amount_yuan),
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
                    payload.device_code,
                    phone,
                    0,
                    payload.station_name,
                    payload.device_code,
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
    return {
        "ok": True,
        "gateway_mode": gateway.mode,
        "total": total,
        "pending": pending,
        "processing": processing,
        "success": success,
        "failed": failed,
        **get_service_status(),
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)

