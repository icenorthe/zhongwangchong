from __future__ import annotations

import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.cloud_agent import (
    SOCKET_STATUS_AGENT_PID_PATH,
    load_config,
    maybe_push_socket_overview,
    register_pid_file,
    write_log,
)


def main() -> int:
    config = load_config()
    register_pid_file(SOCKET_STATUS_AGENT_PID_PATH)
    interval_seconds = max(10, int(config.get("socket_overview_push_seconds", 20)))

    write_log("socket status agent started")
    maybe_push_socket_overview(config, force=True)

    try:
        while True:
            time.sleep(interval_seconds)
            maybe_push_socket_overview(config, force=True)
    except KeyboardInterrupt:
        write_log("socket status agent stopped by keyboard interrupt")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
