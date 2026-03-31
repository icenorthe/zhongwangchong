"""
ASGI entrypoint for PythonAnywhere.

This disables the background worker on the hosted web app so orders stay in
PENDING status until a local agent claims them later.
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, '/home/icenorth/zhongwang-charge')

try:
    from services.project_paths import CONFIG_DIR
except ImportError:
    from project_paths import CONFIG_DIR

os.environ.setdefault("WORKER_ENABLED", "0")

SECRETS_PATH = CONFIG_DIR / "pythonanywhere_secrets.json"


def set_env_if_blank(name: str, value: str) -> None:
    current = str(os.environ.get(name, "")).strip()
    if not current and value.strip():
        os.environ[name] = value.strip()

if SECRETS_PATH.exists():
    data = json.loads(SECRETS_PATH.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        for env_name in (
            "ADMIN_USERNAME",
            "ADMIN_TOKEN",
            "ADMIN_PASSWORD",
            "AGENT_TOKEN",
            "WORKER_ENABLED",
            "REQUIRE_AGENT_ONLINE_FOR_ORDERS",
            "AGENT_HEARTBEAT_EXPIRE_SECONDS",
            "PAYMENT_MODE",
            "PAYMENT_BRIDGE_URL",
            "PAYMENT_BRIDGE_UPSTREAM",
            "SOCKET_OVERVIEW_BRIDGE_URL",
            "QJPAY_API",
            "QJPAY_PID",
            "QJPAY_KEY",
            "QJPAY_CHANNEL_ID",
            "MANUAL_PAYMENT_CONTACT",
            "MANUAL_PAYMENT_INSTRUCTIONS",
            "PAYMENT_TOKEN_SECRET",
            "PAYMENT_TOKEN_TTL_SECONDS",
            "BALANCE_REFUND_ON_FAIL",
            "PREFER_AGENT_SNAPSHOT",
            "ALLOW_STALE_AGENT_SNAPSHOT",
            "REALTIME_STATUS_RETRY_COUNT",
            "REALTIME_STATUS_RETRY_BACKOFF_SECONDS",
            "REALTIME_STATUS_RETRY_JITTER_SECONDS",
            "REALTIME_STATUS_MAX_WORKERS",
            "REALTIME_STATUS_SERIAL_RETRY_LIMIT",
            "REALTIME_STATUS_SERIAL_RETRY_SECONDS",
            "REALTIME_STATION_CACHE_SECONDS",
            "SOCKET_OVERVIEW_CACHE_SECONDS",
        ):
            value = data.get(env_name.lower()) or data.get(env_name)
            if isinstance(value, str) and value.strip():
                set_env_if_blank(env_name, value)

try:
    from services.mobile_charge_server import app  # noqa: E402
except ImportError:
    from mobile_charge_server import app  # noqa: E402



