from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "services"
CONFIG_DIR = PROJECT_ROOT / "config"
ASSETS_DIR = PROJECT_ROOT / "assets"
WEB_ASSETS_DIR = ASSETS_DIR / "web"
WECHAT_ASSETS_DIR = ASSETS_DIR / "wechat_rpa"
DOCS_DIR = PROJECT_ROOT / "docs"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
LOG_DIR = RUNTIME_DIR / "logs"
SCREENSHOT_DIR = RUNTIME_DIR / "runner_screenshots"
DEPLOY_DIR = PROJECT_ROOT / "deploy"


def ensure_runtime_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
