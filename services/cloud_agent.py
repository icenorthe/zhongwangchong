from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

try:
    from services.project_paths import CONFIG_DIR, LOG_DIR
except ImportError:
    from project_paths import CONFIG_DIR, LOG_DIR


CONFIG_PATH = CONFIG_DIR / "cloud_agent_config.json"
LOG_PATH = LOG_DIR / "cloud_agent.log"


def write_log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"[{ts}] {message}\n")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            "Missing config/cloud_agent_config.json. Copy "
            "config/cloud_agent_config.example.json to "
            "config/cloud_agent_config.json and fill it first."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


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


def process_once(config: dict[str, Any]) -> bool:
    base_url = str(config["base_url"]).rstrip("/")
    agent_token = str(config["agent_token"]).strip()
    runner_command = runner_command_from_config(config)
    timeout_seconds = int(config.get("runner_timeout_seconds", 120))

    if not base_url or not agent_token:
        raise SystemExit("cloud_agent_config.json must contain base_url and agent_token")

    safe_send_heartbeat(config, status="IDLE")

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
    poll_seconds = max(2, int(config.get("poll_seconds", 5)))

    write_log("cloud agent started")
    safe_send_heartbeat(config, status="IDLE")
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



