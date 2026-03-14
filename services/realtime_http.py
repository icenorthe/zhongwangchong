from __future__ import annotations

import json
import os
import random
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


REALTIME_RETRY_COUNT = max(1, int(os.getenv("REALTIME_STATUS_RETRY_COUNT", "3")))
REALTIME_RETRY_BACKOFF_SECONDS = max(
    0.05, float(os.getenv("REALTIME_STATUS_RETRY_BACKOFF_SECONDS", "0.25"))
)
REALTIME_RETRY_JITTER_SECONDS = max(
    0.0, float(os.getenv("REALTIME_STATUS_RETRY_JITTER_SECONDS", "0.12"))
)
REALTIME_FORCE_TLS12 = os.getenv("REALTIME_STATUS_FORCE_TLS12", "1").lower() not in {
    "0",
    "false",
    "no",
}


def decode_remote_text(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("gb18030", errors="replace")


def build_realtime_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if hasattr(ssl, "TLSVersion"):
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if REALTIME_FORCE_TLS12:
            # The upstream charger service intermittently drops newer TLS handshakes.
            context.maximum_version = ssl.TLSVersion.TLSv1_2
    if hasattr(ssl, "OP_NO_TICKET"):
        context.options |= ssl.OP_NO_TICKET
    return context


REALTIME_SSL_CONTEXT = build_realtime_ssl_context()


def unwrap_error_reason(err: BaseException) -> BaseException:
    reason = getattr(err, "reason", None)
    return reason if isinstance(reason, BaseException) else err


def format_error_message(err: BaseException) -> str:
    reason = getattr(err, "reason", None)
    if isinstance(reason, BaseException):
        return str(reason)
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return str(err)


def is_retryable_realtime_error(err: BaseException) -> bool:
    reason = unwrap_error_reason(err)
    if isinstance(reason, (ssl.SSLError, socket.timeout, TimeoutError, ConnectionResetError)):
        return True
    message = " ".join(
        part.strip()
        for part in (format_error_message(err), str(reason))
        if isinstance(part, str) and part.strip()
    ).lower()
    retry_markers = (
        "unexpected eof while reading",
        "eof occurred in violation of protocol",
        "timed out",
        "connection reset by peer",
        "remote end closed connection",
        "tlsv1 alert internal error",
        "handshake operation timed out",
    )
    return any(marker in message for marker in retry_markers)


def post_form_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout: float,
    retry_count: int = REALTIME_RETRY_COUNT,
    backoff_seconds: float = REALTIME_RETRY_BACKOFF_SECONDS,
    jitter_seconds: float = REALTIME_RETRY_JITTER_SECONDS,
) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {key: str(value) for key, value in payload.items() if value not in (None, "")}
    ).encode("utf-8")
    request_headers = dict(headers)
    request_headers.setdefault("Accept", "application/json, text/plain, */*")
    request_headers.setdefault("Connection", "close")

    for attempt in range(1, retry_count + 1):
        request = urllib.request.Request(url, data=body, method="POST", headers=request_headers)
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=REALTIME_SSL_CONTEXT,
            ) as response:
                raw_bytes = response.read()
            return json.loads(decode_remote_text(raw_bytes))
        except urllib.error.HTTPError as err:
            raw_bytes = err.read()
            detail = decode_remote_text(raw_bytes).strip()
            if attempt >= retry_count or err.code < 500:
                raise RuntimeError(f"HTTP {err.code}: {detail or err.reason}") from err
        except Exception as err:
            if attempt >= retry_count or not is_retryable_realtime_error(err):
                raise RuntimeError(format_error_message(err)) from err
        if attempt < retry_count:
            time.sleep(backoff_seconds * attempt + random.uniform(0.0, jitter_seconds))

    raise RuntimeError("实时接口请求失败")
