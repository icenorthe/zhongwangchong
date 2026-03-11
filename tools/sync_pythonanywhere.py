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


def upload_file(api_host: str, username: str, api_token: str, local_file: Path, remote_file: str) -> None:
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
    payload.write(local_file.read_bytes())
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


def main() -> int:
    config = load_config()
    username = config["username"].strip()
    api_token = config["api_token"].strip()
    api_host = config.get("api_host", "www.pythonanywhere.com").strip()
    domain = config["domain"].strip()
    remote_project_path = config["remote_project_path"].rstrip("/")
    files = config["files"]

    if not username or not api_token or not domain or not remote_project_path:
        raise SystemExit("Config contains empty required fields.")

    print(f"Syncing to PythonAnywhere project: {remote_project_path}")
    for relative_path in files:
        local_file = PROJECT_ROOT / relative_path
        if not local_file.exists():
            raise SystemExit(f"Missing local file: {local_file}")
        remote_file = f"{remote_project_path}/{relative_path}"
        print(f"Uploading {relative_path} -> {remote_file}")
        upload_file(api_host, username, api_token, local_file, remote_file)

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



