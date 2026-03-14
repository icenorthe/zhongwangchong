from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "pythonanywhere_sync_config.json"
BACKUP_DIR = PROJECT_ROOT / "archive" / "pythonanywhere_db"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            "Missing config/pythonanywhere_sync_config.json. Copy "
            "config/pythonanywhere_sync_config.example.json and fill it first."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def build_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Token {api_token}"}


def download_remote_file(
    *,
    api_host: str,
    username: str,
    api_token: str,
    remote_file: str,
) -> bytes:
    url = (
        f"https://{api_host}/api/v0/user/{username}/files/path"
        f"{urllib.parse.quote(remote_file)}"
    )
    request = urllib.request.Request(url=url, method="GET", headers=build_headers(api_token))
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main() -> int:
    config = load_config()
    username = str(config["username"]).strip()
    api_token = str(config["api_token"]).strip()
    api_host = str(config.get("api_host", "www.pythonanywhere.com")).strip()
    remote_project_path = str(config["remote_project_path"]).rstrip("/")
    remote_db_path = f"{remote_project_path}/runtime/orders.db"

    if not username or not api_token or not remote_project_path:
        raise SystemExit("Config contains empty required fields.")

    print(f"Downloading cloud database: {remote_db_path}")
    raw = download_remote_file(
        api_host=api_host,
        username=username,
        api_token=api_token,
        remote_file=remote_db_path,
    )

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"orders-{stamp}.db"
    latest = BACKUP_DIR / "orders-latest.db"
    target.write_bytes(raw)
    shutil.copyfile(target, latest)

    print(f"Saved backup: {target}")
    print(f"Updated latest: {latest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        print(f"HTTP {err.code}: {detail}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as err:
        print(f"Network error: {err}", file=sys.stderr)
        raise SystemExit(1)
