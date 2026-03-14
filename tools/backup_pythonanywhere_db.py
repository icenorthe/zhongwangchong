from __future__ import annotations

import csv
import json
import sqlite3
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
MAX_BACKUP_FILES = 5


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


def prune_old_backups() -> None:
    backups = sorted(
        BACKUP_DIR.glob("orders-*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old_file in backups[MAX_BACKUP_FILES:]:
        old_file.unlink(missing_ok=True)


def export_refund_reports(db_path: Path) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = BACKUP_DIR / f"refund-users-{stamp}.json"
    csv_path = BACKUP_DIR / f"refund-users-{stamp}.csv"
    latest_json = BACKUP_DIR / "refund-users-latest.json"
    latest_csv = BACKUP_DIR / "refund-users-latest.csv"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                phone,
                balance_yuan,
                created_at,
                updated_at
            FROM users
            ORDER BY balance_yuan DESC, id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "user_id": int(row["id"]),
            "phone": str(row["phone"] or ""),
            "balance_yuan": round(float(row["balance_yuan"] or 0), 2),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
        for row in rows
    ]

    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["user_id", "phone", "balance_yuan", "created_at", "updated_at"],
        )
        writer.writeheader()
        writer.writerows(items)

    shutil.copyfile(json_path, latest_json)
    shutil.copyfile(csv_path, latest_csv)
    return latest_json, latest_csv


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
    prune_old_backups()
    refund_json, refund_csv = export_refund_reports(latest)

    print(f"Saved backup: {target}")
    print(f"Updated latest: {latest}")
    print(f"Updated refund JSON: {refund_json}")
    print(f"Updated refund CSV : {refund_csv}")
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
