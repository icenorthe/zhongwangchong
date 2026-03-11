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
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "orders.db"
HTML_PATH = APP_DIR / "mobile_order.html"
ADMIN_HTML_PATH = APP_DIR / "admin_orders.html"
GATEWAY_CONFIG_PATH = APP_DIR / "gateway_config.json"
POLL_INTERVAL_SECONDS = float(os.getenv("ORDER_POLL_INTERVAL_SECONDS", "2"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "1").lower() not in {"0", "false", "no"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_nested_value(data: Any, path: str, default: Any = None) -> Any:
    if not path:
        return default
    current = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        ensure_order_columns(conn)
        conn.commit()


def ensure_order_columns(conn: sqlite3.Connection) -> None:
    required_columns = {
        "station_name": "TEXT NOT NULL DEFAULT ''",
        "device_code": "TEXT NOT NULL DEFAULT ''",
        "socket_no": "INTEGER NOT NULL DEFAULT 1",
        "amount_yuan": "REAL NOT NULL DEFAULT 1",
    }
    rows = conn.execute("PRAGMA table_info(orders)").fetchall()
    existing = {row["name"] for row in rows}
    for column_name, column_type in required_columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
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


class OrderView(BaseModel):
    id: int
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


class AgentCompletePayload(BaseModel):
    success: bool
    message: str = Field(default="", max_length=500)
    vendor_order_id: str = Field(default="", max_length=120)


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
        return
    candidate = x_admin_token or token
    if candidate != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")


def require_agent(
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
    token: str | None = Query(default=None),
) -> None:
    if not AGENT_TOKEN:
        return
    candidate = x_agent_token or token
    if candidate != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="invalid agent token")


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


def update_order_result(order_id: int, status: str, message: str, vendor_order_id: str = "") -> None:
    with db_connect() as conn:
        conn.execute(
            """
            UPDATE orders
            SET status = ?, result_message = ?, vendor_order_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, message, vendor_order_id, now_iso(), order_id),
        )
        conn.commit()


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


@app.get("/admin", response_class=HTMLResponse)
def admin_page(token: str | None = Query(default=None)) -> str:
    if not ADMIN_HTML_PATH.exists():
        return "<h3>admin_orders.html not found</h3>"
    content = ADMIN_HTML_PATH.read_text(encoding="utf-8")
    token_json = json.dumps(token or "", ensure_ascii=False)
    return content.replace('"__ADMIN_TOKEN__"', token_json)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "worker_enabled": WORKER_ENABLED,
        "worker_alive": bool(worker_thread and worker_thread.is_alive()),
        "gateway_mode": gateway.mode,
        "time": now_iso(),
    }


@app.post("/api/orders", response_model=OrderView)
def create_order(payload: OrderCreate) -> OrderView:
    ts = now_iso()
    with db_connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO orders
                (
                    pile_no, phone, minutes,
                    station_name, device_code, socket_no, amount_yuan,
                    remark, status, result_message, vendor_order_id, created_at, updated_at
                )
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', '', '', ?, ?)
            """,
            (
                payload.device_code,
                "",
                0,
                payload.station_name,
                payload.device_code,
                payload.socket_no,
                payload.amount_yuan,
                payload.remark,
                ts,
                ts,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (cursor.lastrowid,)).fetchone()

    if row is None:
        raise HTTPException(status_code=500, detail="failed to create order")
    return OrderView(**row_to_dict(row))


@app.get("/api/orders/{order_id}", response_model=OrderView)
def get_order(order_id: int) -> OrderView:
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
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

    uvicorn.run(
        "mobile_charge_server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
