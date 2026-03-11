"""
ASGI entrypoint for PythonAnywhere.

This disables the background worker on the hosted web app so orders stay in
PENDING status until a local agent claims them later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from services.project_paths import CONFIG_DIR
except ImportError:
    from project_paths import CONFIG_DIR

os.environ.setdefault("WORKER_ENABLED", "0")

SECRETS_PATH = CONFIG_DIR / "pythonanywhere_secrets.json"

if SECRETS_PATH.exists():
    data = json.loads(SECRETS_PATH.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        for env_name in (
            "ADMIN_TOKEN",
            "AGENT_TOKEN",
            "WORKER_ENABLED",
            "REQUIRE_AGENT_ONLINE_FOR_ORDERS",
            "AGENT_HEARTBEAT_EXPIRE_SECONDS",
            "PAYMENT_MODE",
            "PAYMENT_TOKEN_SECRET",
            "PAYMENT_TOKEN_TTL_SECONDS",
            "BALANCE_REFUND_ON_FAIL",
        ):
            value = data.get(env_name.lower()) or data.get(env_name)
            if isinstance(value, str) and value.strip():
                os.environ.setdefault(env_name, value.strip())

try:
    from services.mobile_charge_server import app  # noqa: E402
except ImportError:
    from mobile_charge_server import app  # noqa: E402



