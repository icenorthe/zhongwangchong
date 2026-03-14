from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.cloud_agent import load_config, maybe_push_socket_overview


def main() -> int:
    config = load_config()
    maybe_push_socket_overview(config, force=True)
    print("socket overview pushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
