from __future__ import annotations

import io
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "pythonanywhere_sync_config.json"
STATIONS_PATH = PROJECT_ROOT / "config" / "stations.json"
STATIONS_PUBLIC_PATH = PROJECT_ROOT / "config" / "stations.public.json"
STATIONS_LOCAL_PATH = PROJECT_ROOT / "config" / "stations.local.json"
STATION_PLACEHOLDERS_PATH = PROJECT_ROOT / "config" / "station_placeholders.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            "Missing config/pythonanywhere_sync_config.json. Copy "
            "config/pythonanywhere_sync_config.example.json and fill it first."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def build_headers(api_token: str, content_type: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Token {api_token}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def expand_number_spec(spec: str) -> list[int]:
    values: set[int] = set()
    for chunk in str(spec or "").split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            try:
                start = int(left.strip())
                end = int(right.strip())
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                values.add(number)
            continue
        try:
            values.add(int(part))
        except ValueError:
            continue
    return sorted(values)


def build_generated_uploads() -> dict[str, bytes]:
    source_path = STATIONS_LOCAL_PATH if STATIONS_LOCAL_PATH.exists() else STATIONS_PATH
    if not source_path.exists() or not STATION_PLACEHOLDERS_PATH.exists():
        return {}
    try:
        stations = json.loads(source_path.read_text(encoding="utf-8-sig"))
        placeholders = json.loads(STATION_PLACEHOLDERS_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(stations, list) or not isinstance(placeholders, list):
        return {}

    merged = [dict(item) for item in stations if isinstance(item, dict)]
    seen_numbers = {
        int(item.get("sort_order"))
        for item in merged
        if isinstance(item, dict) and str(item.get("sort_order", "")).isdigit()
    }
    seen_ids = {
        str(item.get("id")).strip()
        for item in merged
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }

    default_address = "四川省成都市龙泉驿区十陵街道成都大学"
    for item in placeholders:
        if not isinstance(item, dict):
            continue
        region = str(item.get("region", "")).strip()
        name_template = str(item.get("name_template", "")).strip()
        station_numbers = str(item.get("station_numbers", "")).strip()
        if not region or not name_template or not station_numbers:
            continue
        address = str(item.get("address", "")).strip() or default_address
        socket_count = int(item.get("socket_count", 10) or 10)
        socket_count = max(1, min(socket_count, 20))
        source = str(item.get("source", "user-provided-list")).strip() or "user-provided-list"
        for number in expand_number_spec(station_numbers):
            station_id = f"cd-{number}"
            if number in seen_numbers or station_id in seen_ids:
                continue
            merged.append(
                {
                    "id": station_id,
                    "region": region,
                    "sort_order": number,
                    "name": name_template.replace("{n}", str(number)),
                    "device_code": "",
                    "socket_count": socket_count,
                    "disabled_sockets": [],
                    "address": address,
                    "source": source,
                }
            )
            seen_numbers.add(number)
            seen_ids.add(station_id)

    region_sort = {"综合楼": 1, "学术交流中心": 2, "东盟一号": 3, "19栋": 4, "19栋女生宿舍": 4}
    merged.sort(
        key=lambda item: (
            region_sort.get(str(item.get("region", "")).strip(), 99),
            int(item.get("sort_order", 9999) or 9999),
            str(item.get("name", "")),
        )
    )
    content = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return {"config/stations.json": content}


def upload_file(
    api_host: str,
    username: str,
    api_token: str,
    local_file: Path,
    remote_file: str,
    content_override: bytes | None = None,
) -> None:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(local_file.name)[0] or "application/octet-stream"
    payload = io.BytesIO()

    payload.write(f"--{boundary}\r\n".encode("utf-8"))
    payload.write(
        (
            f'Content-Disposition: form-data; name="content"; filename="{local_file.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    payload.write(content_override if content_override is not None else local_file.read_bytes())
    payload.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = (
        f"https://{api_host}/api/v0/user/{username}/files/path"
        f"{urllib.parse.quote(remote_file)}"
    )
    request = urllib.request.Request(
        url=url,
        data=payload.getvalue(),
        method="POST",
        headers=build_headers(api_token, f"multipart/form-data; boundary={boundary}"),
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()


def reload_webapp(api_host: str, username: str, api_token: str, domain: str) -> None:
    url = f"https://{api_host}/api/v0/user/{username}/webapps/{urllib.parse.quote(domain)}/reload/"
    request = urllib.request.Request(
        url=url,
        data=b"",
        method="POST",
        headers=build_headers(api_token),
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()


def wsgi_path_for_domain(username: str, domain: str) -> str:
    safe_domain = domain.replace(".", "_")
    return f"/var/www/{username}_{safe_domain}_wsgi.py"


def build_wsgi_content(remote_project_path: str) -> bytes:
    project_path = remote_project_path.rstrip("/")
    content = (
        "import sys\n"
        "import os\n\n"
        f'project_path = "{project_path}"\n'
        "if project_path not in sys.path:\n"
        "    sys.path.insert(0, project_path)\n\n"
        "from pythonanywhere_app import app as application\n"
    )
    return content.encode("utf-8")


def main() -> int:
    config = load_config()
    username = config["username"].strip()
    api_token = config["api_token"].strip()
    api_host = config.get("api_host", "www.pythonanywhere.com").strip()
    domain = config["domain"].strip()
    remote_project_path = config["remote_project_path"].rstrip("/")
    files = config["files"]
    wsgi_path = config.get("wsgi_path", "").strip()
    update_wsgi = str(config.get("update_wsgi", "1")).strip().lower() not in {"0", "false", "no"}

    if not username or not api_token or not domain or not remote_project_path:
        raise SystemExit("Config contains empty required fields.")

    generated_uploads = build_generated_uploads()
    print(f"Syncing to PythonAnywhere project: {remote_project_path}")
    for relative_path in files:
        local_file = PROJECT_ROOT / relative_path
        content_override = generated_uploads.get(relative_path)
        if not local_file.exists():
            if content_override is None:
                raise SystemExit(f"Missing local file: {local_file}")
            remote_file = f"{remote_project_path}/{relative_path}"
            print(f"Uploading {relative_path} -> {remote_file} (generated)")
            upload_file(
                api_host,
                username,
                api_token,
                local_file,
                remote_file,
                content_override=content_override,
            )
            continue
        remote_file = f"{remote_project_path}/{relative_path}"
        print(f"Uploading {relative_path} -> {remote_file}")
        upload_file(
            api_host,
            username,
            api_token,
            local_file,
            remote_file,
            content_override=content_override,
        )

    if update_wsgi:
        wsgi_target = wsgi_path or wsgi_path_for_domain(username, domain)
        print(f"Updating WSGI config: {wsgi_target}")
        upload_file(
            api_host,
            username,
            api_token,
            local_file=Path("wsgi.py"),
            remote_file=wsgi_target,
            content_override=build_wsgi_content(remote_project_path),
        )

    print(f"Reloading webapp: {domain}")
    try:
        reload_webapp(api_host, username, api_token, domain)
        print("Done.")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        if err.code == 403:
            print("Upload finished, but automatic reload was denied by PythonAnywhere API.")
            print(f"Reload manually in Web tab for {domain}.")
            print(f"API detail: {detail}")
            return 0
        raise
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



