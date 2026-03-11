from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any

import pyautogui
import pygetwindow
import pyperclip

try:
    from services.project_paths import CONFIG_DIR, LOG_DIR, SCREENSHOT_DIR, WECHAT_ASSETS_DIR
except ImportError:
    from project_paths import CONFIG_DIR, LOG_DIR, SCREENSHOT_DIR, WECHAT_ASSETS_DIR


LOG_PATH = LOG_DIR / "local_charge_runner.log"
CONFIG_PATH = CONFIG_DIR / "wechat_rpa_config.json"
ASSETS_DIR = WECHAT_ASSETS_DIR
STATIONS_PATH = CONFIG_DIR / "stations.json"
pyautogui.FAILSAFE = True


def write_log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_message = message.encode("utf-8", errors="replace").decode("utf-8")
    with LOG_PATH.open("a", encoding="utf-8", errors="replace") as file:
        file.write(f"[{ts}] {safe_message}\n")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            "Missing config/wechat_rpa_config.json. Copy "
            "config/wechat_rpa_config.example.json to "
            "config/wechat_rpa_config.json and fill coordinates first."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def load_stations() -> list[dict[str, Any]]:
    if not STATIONS_PATH.exists():
        return []
    try:
        data = json.loads(STATIONS_PATH.read_text(encoding="utf-8-sig"))
    except Exception as err:
        write_log(f"failed to load stations.json: {err}")
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def render_text(value: str, context: dict[str, Any]) -> str:
    return Template(value).safe_substitute({key: str(val) for key, val in context.items()})


def save_failure_screenshot(order_id: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = SCREENSHOT_DIR / f"order_{order_id}_{int(time.time())}.png"
    pyautogui.screenshot(str(file_path))
    return str(file_path)


def get_required_point(config: dict[str, Any], key: str) -> tuple[int, int]:
    point = config.get(key)
    if not isinstance(point, dict) or "x" not in point or "y" not in point:
        raise RuntimeError(f"Missing point config: {key}")
    return int(point["x"]), int(point["y"])


def maybe_wait(seconds: float, reason: str) -> None:
    if seconds <= 0:
        return
    write_log(f"wait {seconds}s for {reason}")
    time.sleep(seconds)


def normalize_region(region: dict[str, Any] | None) -> tuple[int, int, int, int] | None:
    if not isinstance(region, dict):
        return None
    keys = {"left", "top", "width", "height"}
    if not keys.issubset(region):
        return None
    return (
        int(region["left"]),
        int(region["top"]),
        int(region["width"]),
        int(region["height"]),
    )


def resolve_template_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = ASSETS_DIR / path
    return path if path.exists() else None


def locate_template_center(
    template_path: Path,
    grayscale: bool = True,
    confidence: float | None = None,
    region: tuple[int, int, int, int] | None = None,
) -> tuple[int, int] | None:
    kwargs: dict[str, Any] = {"grayscale": grayscale}
    if region:
        kwargs["region"] = region
    if confidence is not None:
        kwargs["confidence"] = confidence
    try:
        point = pyautogui.locateCenterOnScreen(str(template_path), **kwargs)
    except TypeError:
        kwargs.pop("confidence", None)
        point = pyautogui.locateCenterOnScreen(str(template_path), **kwargs)
    if point is None:
        return None
    return int(point.x), int(point.y)


def wait_for_template(
    config: dict[str, Any],
    template_name: str,
    timeout_seconds: float | None = None,
    region_name: str | None = None,
) -> tuple[int, int] | None:
    template_path = resolve_template_path(str(config.get(template_name, "")).strip())
    if template_path is None:
        return None

    confidence = config.get("template_confidence")
    timeout_seconds = timeout_seconds or float(config.get("template_wait_timeout_seconds", 5))
    region = normalize_region(config.get(region_name)) if region_name else None
    started = time.time()
    while time.time() - started <= timeout_seconds:
        point = locate_template_center(
            template_path=template_path,
            grayscale=bool(config.get("template_grayscale", True)),
            confidence=float(confidence) if confidence is not None else None,
            region=region,
        )
        if point is not None:
            write_log(f"found template {template_name} at {point}")
            return point
        time.sleep(0.2)
    return None


def click_target(
    config: dict[str, Any],
    *,
    name: str,
    point_key: str | None = None,
    template_key: str | None = None,
    region_key: str | None = None,
    delay_seconds: float,
    timeout_seconds: float | None = None,
    required: bool = True,
) -> bool:
    point: tuple[int, int] | None = None
    if template_key:
        point = wait_for_template(
            config,
            template_key,
            timeout_seconds=timeout_seconds,
            region_name=region_key,
        )
    if point is None and point_key and config.get(point_key):
        point = get_required_point(config, point_key)
    if point is None:
        if required:
            raise RuntimeError(f"Missing target for {name}")
        write_log(f"skip optional target {name}")
        return False
    click_point(name, point, delay_seconds)
    return True


def activate_wechat_window(title_keywords: list[str], delay_seconds: float) -> None:
    import win32gui
    import win32con

    found_hwnd = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and any(kw in title for kw in title_keywords):
                found_hwnd.append(hwnd)
    win32gui.EnumWindows(callback, None)

    if not found_hwnd:
        raise RuntimeError(f"WeChat window not found for keywords: {title_keywords}")

    hwnd = found_hwnd[0]
    rect = win32gui.GetWindowRect(hwnd)
    # 强制前台
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    # 点击顶部标题栏（安全区域，不触发小程序内容点击）
    cx = (rect[0] + rect[2]) // 2
    cy = rect[1] + 15
    pyautogui.click(cx, cy)
    time.sleep(delay_seconds)
    write_log(f"activated hwnd={hwnd} rect={rect} clicked=({cx},{cy})")


def click_point(name: str, point: tuple[int, int], delay_seconds: float, clicks: int = 1) -> None:
    write_log(f"click {name} at {point}")
    pyautogui.click(point[0], point[1], clicks=clicks, interval=0.15)
    time.sleep(delay_seconds)


def paste_text(text: str, delay_seconds: float) -> None:
    # 先清空输入框
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.2)
    # 逐字符粘贴，每次触发一次input事件，让微信小程序感知到输入
    for char in text:
        pyperclip.copy(char)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.06)
    time.sleep(delay_seconds)


def press_key(key: str, delay_seconds: float) -> None:
    pyautogui.press(key)
    time.sleep(delay_seconds)


def socket_point(config: dict[str, Any], socket_no: int) -> tuple[int, int]:
    mapping = config.get("socket_points", {})
    point = mapping.get(str(socket_no))
    if not point:
        raise RuntimeError(f"Missing socket coordinate for socket {socket_no}")
    return int(point["x"]), int(point["y"])


def socket_template_key(socket_no: int) -> str:
    return f"socket_{socket_no}_image"


def amount_point(config: dict[str, Any], amount_yuan: float) -> tuple[int, int]:
    mapping = config.get("amount_points", {})
    normalized = str(int(amount_yuan)) if float(amount_yuan).is_integer() else str(amount_yuan)
    point = mapping.get(normalized)
    if not point:
        raise RuntimeError(f"Missing amount coordinate for amount {amount_yuan}")
    return int(point["x"]), int(point["y"])


def amount_template_key(amount_yuan: float) -> str:
    normalized = str(int(amount_yuan)) if float(amount_yuan).is_integer() else str(amount_yuan)
    return f"amount_{normalized}_image"


def resolve_station_metadata(order: dict[str, Any]) -> tuple[str, str]:
    station_name = str(order.get("station_name", "")).strip()
    device_code = str(order.get("device_code") or order.get("pile_no") or "").strip()
    if station_name and device_code:
        return station_name, device_code

    for station in load_stations():
        current_name = str(station.get("name", "")).strip()
        current_code = str(station.get("device_code") or station.get("sn") or "").strip()
        if device_code and current_code == device_code:
            return station_name or current_name, device_code
        if station_name and current_name == station_name and current_code:
            return station_name, current_code
    return station_name, device_code


def build_context(order: dict[str, Any]) -> dict[str, Any]:
    amount_value = float(order.get("amount_yuan", 1))
    station_name, device_code = resolve_station_metadata(order)
    order_id = order.get("id", order.get("client_order_id", ""))
    return {
        "id": order_id,
        "client_order_id": order.get("client_order_id", order_id),
        "station_name": station_name,
        "device_code": device_code,
        "socket_no": order.get("socket_no", 1),
        "amount_yuan": int(amount_value) if amount_value.is_integer() else amount_value,
        "remark": order.get("remark", ""),
    }


def run_rpa(order: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str, str]:
    if not bool(config.get("enabled", False)):
        raise RuntimeError("wechat_rpa_config.json has enabled=false")

    context = build_context(order)
    delay = float(config.get("step_delay_seconds", 0.8))
    after_submit_wait = float(config.get("after_submit_wait_seconds", 3))
    raw_keywords = config.get("wechat_window_title_keywords", ["微信"])
    # 修复从GBK环境读取JSON导致的关键字乱码问题，强制使用正确的微信窗口标题
    title_keywords = []
    for kw in raw_keywords:
        try:
            fixed = kw.encode("latin-1").decode("gbk")
            title_keywords.append(fixed)
        except Exception:
            title_keywords.append(kw)
    if not title_keywords:
        title_keywords = ["微信"]
    search_text_template = str(config.get("station_search_text_template", "$station_name"))
    pay_message = str(config.get("success_message", "wechat desktop flow executed"))
    manual_confirm_seconds = float(config.get("manual_payment_confirm_seconds", 0))
    launch_ad_wait = float(config.get("launch_ad_wait_seconds", 0))
    post_ad_wait = float(config.get("post_ad_wait_seconds", 0))

    activate_wechat_window(title_keywords, delay)
    maybe_wait(launch_ad_wait, "launch ad countdown")

    click_target(
        config,
        name="launch_ad_skip",
        point_key="launch_ad_skip_point",
        template_key="launch_ad_skip_image",
        region_key="launch_ad_region",
        delay_seconds=delay,
        timeout_seconds=float(config.get("launch_ad_timeout_seconds", 2)),
        required=False,
    )
    maybe_wait(post_ad_wait, "post ad transition")

    ready_template = wait_for_template(config, "ready_state_image", region_name="ready_state_region")
    if config.get("ready_state_image") and ready_template is None:
        raise RuntimeError("target mini-program page not detected")

    click_target(
        config,
        name="vehicle_tab",
        point_key="vehicle_tab_point",
        template_key="vehicle_tab_image",
        region_key="vehicle_tab_region",
        delay_seconds=delay,
        timeout_seconds=float(config.get("vehicle_tab_timeout_seconds", 2)),
        required=False,
    )

    if config.get("search_station_image") or config.get("search_station_point"):
        click_target(
            config,
            name="search_station",
            point_key="search_station_point",
            template_key="search_station_image",
            region_key="search_station_region",
            delay_seconds=delay,
            timeout_seconds=float(config.get("search_station_timeout_seconds", 5)),
        )
        search_text = render_text(search_text_template, context).strip()
        if not search_text:
            search_text = str(context.get("device_code", "")).strip()
        paste_text(search_text, delay)
        # 等待小程序内部input事件处理完毕，再点击搜索按钮
        time.sleep(0.8)
        search_btn_clicked = click_target(
            config,
            name="search_btn",
            point_key="search_btn_point",
            template_key="search_btn_image",
            region_key="search_btn_region",
            delay_seconds=delay,
            timeout_seconds=float(config.get("search_btn_timeout_seconds", 5)),
            required=False,
        )
        if not search_btn_clicked and config.get("search_submit_key"):
            press_key(str(config.get("search_submit_key")), delay)

    if config.get("station_result_image") or config.get("station_result_point"):
        click_target(
            config,
            name="station_result",
            point_key="station_result_point",
            template_key="station_result_image",
            region_key="station_result_region",
            delay_seconds=delay,
            timeout_seconds=float(config.get("station_result_timeout_seconds", 5)),
        )

    socket_clicked = click_target(
        config,
        name="socket",
        point_key=None,
        template_key=socket_template_key(int(context["socket_no"])),
        region_key="socket_region",
        delay_seconds=delay,
        required=False,
    )
    if not socket_clicked:
        click_point("socket_point", socket_point(config, int(context["socket_no"])), delay)

    click_target(
        config,
        name="go_charge",
        point_key="go_charge_point",
        template_key="go_charge_image",
        region_key="go_charge_region",
        delay_seconds=delay,
        timeout_seconds=float(config.get("go_charge_timeout_seconds", 3)),
        required=False,
    )

    amount_clicked = click_target(
        config,
        name="amount",
        point_key=None,
        template_key=amount_template_key(float(context["amount_yuan"])),
        region_key="amount_region",
        delay_seconds=delay,
        required=False,
    )
    if not amount_clicked:
        click_point("amount_point", amount_point(config, float(context["amount_yuan"])), delay)

    click_target(
        config,
        name="submit_order",
        point_key="submit_order_point",
        template_key="submit_order_image",
        region_key="submit_order_region",
        delay_seconds=delay,
    )

    payment_method = str(config.get("payment_method", "")).strip().lower()
    if payment_method == "wechat" or config.get("wechat_pay_image") or config.get("wechat_pay_point"):
        click_target(
            config,
            name="wechat_pay",
            point_key="wechat_pay_point",
            template_key="wechat_pay_image",
            region_key="wechat_pay_region",
            delay_seconds=delay,
            timeout_seconds=float(config.get("wechat_pay_timeout_seconds", 3)),
            required=False,
        )

    click_target(
        config,
        name="pay_confirm",
        point_key="pay_confirm_point",
        template_key="pay_confirm_image",
        region_key="pay_confirm_region",
        delay_seconds=delay,
        required=False,
    )

    if manual_confirm_seconds > 0:
        write_log(f"waiting {manual_confirm_seconds}s for manual payment confirmation")
        time.sleep(manual_confirm_seconds)

    time.sleep(after_submit_wait)
    done_template = wait_for_template(config, "success_state_image", timeout_seconds=2, region_name="success_state_region")
    if config.get("success_state_image") and done_template is None:
        write_log("success_state_image not detected; continue using submit result timeout flow")
    return True, pay_message, f"wechat-{context['id']}"


def smoke_test() -> dict[str, Any]:
    config = load_config()
    delay = float(config.get("step_delay_seconds", 0.8))
    raw_keywords = config.get("wechat_window_title_keywords", ["微信"])
    # 修复从GBK环境读取JSON导致的关键字乱码问题，强制使用正确的微信窗口标题
    title_keywords = []
    for kw in raw_keywords:
        try:
            fixed = kw.encode("latin-1").decode("gbk")
            title_keywords.append(fixed)
        except Exception:
            title_keywords.append(kw)
    if not title_keywords:
        title_keywords = ["微信"]
    activate_wechat_window(title_keywords, delay)
    return {"success": True, "message": "wechat window activated", "order_id": "smoke"}

def run_from_stdin() -> dict[str, Any]:
    import io
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    raw = sys.stdin.read().replace("\x00", "").lstrip("\ufeff").strip()
    if not raw:
        return {"success": False, "message": "empty stdin", "order_id": ""}

    try:
        order = json.loads(raw)
    except Exception as err:
        return {"success": False, "message": f"invalid json: {err}", "order_id": ""}

    write_log(f"received order: {json.dumps(order, ensure_ascii=False)}")

    try:
        config = load_config()
        success, message, order_id = run_rpa(order, config)
        return {"success": success, "message": message, "order_id": order_id}
    except Exception as err:
        screenshot = save_failure_screenshot(str(order.get("id", "na")))
        return {"success": False, "message": f"{err} | screenshot={screenshot}", "order_id": ""}

def main() -> None:
    parser = argparse.ArgumentParser(description="WeChat desktop RPA runner (stdin JSON).")
    parser.add_argument("--smoke-test", action="store_true", help="Only activate WeChat window and exit.")
    args = parser.parse_args()

    if args.smoke_test:
        result = smoke_test()
    else:
        result = run_from_stdin()

    write_log(f"result: {json.dumps(result, ensure_ascii=False)}")
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()



