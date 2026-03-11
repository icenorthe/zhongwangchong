"""
ASGI entrypoint for PythonAnywhere.

This disables the background worker on the hosted web app so orders stay in
PENDING status until a local agent claims them later.
"""

from __future__ import annotations

import os

os.environ.setdefault("WORKER_ENABLED", "0")

from mobile_charge_server import app  # noqa: E402
