from __future__ import annotations

import atexit
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from services.project_paths import CONFIG_DIR, LOG_DIR, RUNTIME_DIR
except ImportError:
    from project_paths import CONFIG_DIR, LOG_DIR, RUNTIME_DIR


CONFIG_PATH = CONFIG_DIR / "cloud_agent_config.json"
CHARGE_API_CONFIG_PATH = CONFIG_DIR / "charge_api_config.json"
GATEWAY_CONFIG_PATH = CONFIG_DIR / "gateway_config.json"
LOG_PATH = LOG_DIR / "cloud_agent.log"
FALLBACK_LOG_PATH = LOG_DIR / "cloud_agent_fallback.log"
CLOUD_AGENT_PID_PATH = RUNTIME_DIR / "cloud_agent.pid"
SOCKET_STATUS_AGENT_PID_PATH = RUNTIME_DIR / "socket_status_agent.pid"
LAST_SOCKET_PUSH_AT = 0.0
LAST_CONSUME_PUSH_AT = 0.0


def write_log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{ts}] {message}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(line)
        return
    except OSError:
        try:
            with FALLBACK_LOG_PATH.open("a", encoding="utf-8") as file:
                file.write(line)
            return
        except OSError:
            sys.stderr.write(line)


def register_pid_file(path: Path) -> None:
    pid = str(os.getpid())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pid, encoding="ascii")

    def _cleanup() -> None:
        try:
            if path.exists() and path.read_text(encoding="ascii").strip() == pid:
                path.unlink()
        except OSError:
            return

    atexit.register(_cleanup)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            "Missing config/cloud_agent_config.json. Copy "
            "config/cloud_agent_config.example.json to "
            "config/cloud_agent_config.json and fill it first."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def load_charge_api_config() -> dict[str, Any]:
    if not CHARGE_API_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CHARGE_API_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_gateway_config() -> dict[str, Any]:
    if not GATEWAY_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(GATEWAY_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def request_json(method: str, url: str, agent_token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers = {"X-Agent-Token": agent_token}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read().decode("utf-8")
    return json.loads(text) if text else {}


def runner_command_from_config(config: dict[str, Any]) -> str:
    return str(config.get("runner_command", "python services\\local_charge_runner.py")).strip()


def local_bridge_url_from_config(config: dict[str, Any]) -> str:
    return str(config.get("local_bridge_url", "")).strip()


def local_bridge_token_from_config(config: dict[str, Any]) -> str:
    explicit = str(config.get("local_bridge_token", "")).strip()
    if explicit:
        return explicit

    env_token = os.getenv("LOCAL_BRIDGE_TOKEN", "").strip()
    if env_token:
        return env_token

    gateway_config = load_gateway_config()
    base_url = str(gateway_config.get("base_url", "")).strip()
    if not base_url:
        return ""
    hostname = (urllib.parse.urlparse(base_url).hostname or "").strip().lower()
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        return ""
    return str(gateway_config.get("token", "")).strip()


def agent_identity(config: dict[str, Any]) -> tuple[str, str]:
    machine_name = socket.gethostname().strip() or "local-pc"
    agent_name = str(config.get("agent_name", machine_name)).strip() or machine_name
    return agent_name, machine_name


def send_heartbeat(config: dict[str, Any], *, status: str, current_order_id: int | None = None) -> None:
    base_url = str(config["base_url"]).rstrip("/")
    agent_token = str(config["agent_token"]).strip()
    agent_name, machine_name = agent_identity(config)
    heartbeat_url = f"{base_url}/api/agent/heartbeat"
    request_json(
        "POST",
        heartbeat_url,
        agent_token,
        {
            "agent_name": agent_name,
            "machine_name": machine_name,
            "runner_command": runner_command_from_config(config),
            "status": status,
            "current_order_id": current_order_id,
        },
    )


def safe_send_heartbeat(config: dict[str, Any], *, status: str, current_order_id: int | None = None) -> None:
    try:
        send_heartbeat(config, status=status, current_order_id=current_order_id)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        write_log(f"heartbeat http error {err.code}: {detail}")
    except Exception as err:
        write_log(f"heartbeat failed: {err}")


def compute_local_socket_snapshot() -> list[dict[str, Any]]:
    try:
        from services.socket_snapshot import compute_live_socket_state_snapshot
    except ImportError:
        from socket_snapshot import compute_live_socket_state_snapshot
    return compute_live_socket_state_snapshot()


def fetch_consume_records(page_index: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
    config = load_charge_api_config()
    member_id = str(config.get("member_id", "")).strip()
    if not member_id:
        return []
    payload = urllib.parse.urlencode(
        {
            "memberId": member_id,
            "pageIndex": str(max(1, int(page_index))),
            "pageSize": str(max(1, min(int(page_size), 100))),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_consumeRecord.action",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        text = response.read().decode("utf-8", errors="ignore")
    data = json.loads(text) if text else {}
    records = data.get("list")
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict)]


def push_socket_overview(config: dict[str, Any]) -> None:
    base_url = str(config["base_url"]).rstrip("/")
    agent_token = str(config["agent_token"]).strip()
    agent_name, _ = agent_identity(config)
    overview_url = f"{base_url}/api/agent/socket-overview"
    snapshot = compute_local_socket_snapshot()
    request_json(
        "POST",
        overview_url,
        agent_token,
        {
            "agent_name": agent_name,
            "captured_at": datetime.now(UTC).isoformat(),
            "snapshot": snapshot,
        },
    )
    write_log(f"pushed socket overview: regions={len(snapshot)}")


def push_consume_records(config: dict[str, Any]) -> None:
    base_url = str(config["base_url"]).rstrip("/")
    agent_token = str(config["agent_token"]).strip()
    records_url = f"{base_url}/api/agent/consume-records"
    records = fetch_consume_records()
    request_json(
        "POST",
        records_url,
        agent_token,
        {
            "captured_at": datetime.now(UTC).isoformat(),
            "records": records,
        },
    )
    write_log(f"pushed consume records: count={len(records)}")


def maybe_push_socket_overview(config: dict[str, Any], *, force: bool = False) -> None:
    global LAST_SOCKET_PUSH_AT
    enabled = str(config.get("push_socket_overview", "1")).strip().lower() not in {"0", "false", "no"}
    if not enabled:
        return
    interval_seconds = max(30, int(config.get("socket_overview_push_seconds", 90)))
    now_monotonic = time.monotonic()
    if not force and LAST_SOCKET_PUSH_AT and (now_monotonic - LAST_SOCKET_PUSH_AT) < interval_seconds:
        return
    try:
        push_socket_overview(config)
        LAST_SOCKET_PUSH_AT = now_monotonic
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        write_log(f"push socket overview http error {err.code}: {detail}")
    except Exception as err:
        write_log(f"push socket overview failed: {err}")


def maybe_push_consume_records(config: dict[str, Any], *, force: bool = False) -> None:
    global LAST_CONSUME_PUSH_AT
    enabled = str(config.get("push_consume_records", "1")).strip().lower() not in {"0", "false", "no"}
    if not enabled:
        return
    interval_seconds = max(30, int(config.get("consume_records_push_seconds", 120)))
    now_monotonic = time.monotonic()
    if not force and LAST_CONSUME_PUSH_AT and (now_monotonic - LAST_CONSUME_PUSH_AT) < interval_seconds:
        return
    try:
        push_consume_records(config)
        LAST_CONSUME_PUSH_AT = now_monotonic
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        write_log(f"push consume records http error {err.code}: {detail}")
    except Exception as err:
        write_log(f"push consume records failed: {err}")


def run_local_runner(command: str, timeout_seconds: int, order: dict[str, Any]) -> tuple[bool, str, str]:
    raw_input = json.dumps(order, ensure_ascii=False)
    try:
        result = subprocess.run(
            command,
            input=raw_input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=True,
        )
    except subprocess.TimeoutExpired:
        return False, f"runner timeout ({timeout_seconds}s)", ""
    except Exception as err:
        return False, f"runner error: {err}", ""

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        return False, f"runner exit={result.returncode}: {stderr or stdout}", ""

    if not stdout:
        return False, "runner returned empty output", ""

    try:
        data = json.loads(stdout)
    except Exception:
        return True, stdout, f"local-{order.get('id', 'na')}"

    success = bool(data.get("success", False))
    message = str(data.get("message", ""))
    vendor_order_id = str(data.get("order_id", f"local-{order.get('id', 'na')}"))
    if not success:
        return False, message or "runner reported failure", vendor_order_id
    return True, message or "runner success", vendor_order_id


def run_bridge_runner(
    bridge_url: str,
    timeout_seconds: int,
    order: dict[str, Any],
    bridge_token: str,
) -> tuple[bool, str, str]:
    payload = {
        "station_name": str(order.get("station_name") or ""),
        "device_code": str(order.get("device_code") or ""),
        "socket_no": int(order.get("socket_no") or 1),
        "amount_yuan": float(order.get("amount_yuan") or 0),
        "remark": str(order.get("remark") or ""),
        "client_order_id": int(order.get("id") or 0),
        "pile_no": str(order.get("pile_no") or order.get("device_code") or ""),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if bridge_token:
        headers["Authorization"] = f"Bearer {bridge_token}"
    request = urllib.request.Request(
        url=bridge_url,
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        return False, f"bridge http error {err.code}: {detail}", ""
    except Exception as err:
        return False, f"bridge error: {err}", ""

    if not text.strip():
        return False, "bridge returned empty output", ""

    try:
        data = json.loads(text)
    except Exception:
        return False, f"bridge returned invalid json: {text}", ""

    success = bool(data.get("success", False))
    message = str(data.get("message", ""))
    vendor_order_id = str(data.get("order_id", f"local-{order.get('id', 'na')}"))
    if not success:
        return False, message or "bridge reported failure", vendor_order_id
    return True, message or "bridge success", vendor_order_id


def process_once(config: dict[str, Any]) -> bool:
    base_url = str(config["base_url"]).rstrip("/")
    agent_token = str(config["agent_token"]).strip()
    runner_command = runner_command_from_config(config)
    bridge_url = local_bridge_url_from_config(config)
    bridge_token = local_bridge_token_from_config(config)
    timeout_seconds = int(config.get("runner_timeout_seconds", 120))

    if not base_url or not agent_token:
        raise SystemExit("cloud_agent_config.json must contain base_url and agent_token")

    safe_send_heartbeat(config, status="IDLE")
    maybe_push_socket_overview(config)
    maybe_push_consume_records(config)

    claim_url = f"{base_url}/api/agent/orders/claim"
    write_log(f"claiming order from {claim_url}")

    try:
        claim = request_json("POST", claim_url, agent_token)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        write_log(f"claim http error {err.code}: {detail}")
        safe_send_heartbeat(config, status="ERROR")
        return False
    except Exception as err:
        write_log(f"claim failed: {err}")
        safe_send_heartbeat(config, status="ERROR")
        return False

    order = claim.get("order")
    if not order:
        write_log("no pending order")
        return False

    order_id = order["id"]
    write_log(f"claimed order #{order_id} for device {order.get('device_code')}")
    safe_send_heartbeat(config, status="PROCESSING", current_order_id=order_id)
    if bridge_url:
        if not bridge_token:
            write_log("local bridge token not configured")
            success, message, vendor_order_id = False, "local bridge token not configured", ""
        else:
            write_log(f"dispatching order #{order_id} to local bridge: {bridge_url}")
            success, message, vendor_order_id = run_bridge_runner(
                bridge_url,
                timeout_seconds,
                order,
                bridge_token,
            )
    else:
        success, message, vendor_order_id = run_local_runner(runner_command, timeout_seconds, order)

    complete_payload = {
        "success": success,
        "message": message,
        "vendor_order_id": vendor_order_id,
    }
    complete_url = f"{base_url}/api/agent/orders/{order_id}/complete"
    try:
        request_json("POST", complete_url, agent_token, complete_payload)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        write_log(f"complete http error {err.code}: {detail}")
        safe_send_heartbeat(config, status="ERROR", current_order_id=order_id)
        return False
    except Exception as err:
        write_log(f"complete failed: {err}")
        safe_send_heartbeat(config, status="ERROR", current_order_id=order_id)
        return False

    write_log(f"completed order #{order_id}: success={success}, message={message}")
    safe_send_heartbeat(config, status="IDLE")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll PythonAnywhere orders and run local automation.")
    parser.add_argument("--once", action="store_true", help="Process at most one order and exit.")
    args = parser.parse_args()

    config = load_config()
    register_pid_file(CLOUD_AGENT_PID_PATH)
    poll_seconds = max(5, int(config.get("poll_seconds", 10)))

    write_log("cloud agent started")
    safe_send_heartbeat(config, status="IDLE")
    maybe_push_socket_overview(config, force=True)
    maybe_push_consume_records(config, force=True)
    if args.once:
        process_once(config)
        return 0

    while True:
        try:
            processed = process_once(config)
            if processed:
                time.sleep(1)
            else:
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            write_log("cloud agent stopped by keyboard interrupt")
            return 0
        except Exception as err:
            write_log(f"unexpected error: {err}")
            safe_send_heartbeat(config, status="ERROR")
            time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
