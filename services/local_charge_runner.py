from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from services.project_paths import CONFIG_DIR, LOG_DIR
    from services.socket_snapshot import load_stations   # 用于获取 device_ck
except ImportError:
    from project_paths import CONFIG_DIR, LOG_DIR
    from socket_snapshot import load_stations

try:
    from services.realtime_http import post_form_json as realtime_post_form_json
except ImportError:
    from realtime_http import post_form_json as realtime_post_form_json


LOG_PATH = LOG_DIR / "local_charge_runner.log"
CONFIG_PATH = CONFIG_DIR / "charge_api_config.json"

CHARGE_API_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_balancePay.action"
KEEP_ALIVE_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_pileUsingOrders.action"
PARSECK_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_parseCk.action"   # 详情页请求

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1780(0x6700143A) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 MicroMessenger/7.0.19.1781(0x67001439) NetType/4G MiniProgramEnv/Windows WindowsWechat/WMPF",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x18005000) NetType/WIFI Language/zh_CN MiniProgramEnv/iOS",
]

CHARGE_API_BASE_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://wx.jwnzn.com/mini_jwnzn/miniapp/index.html",
    "Origin": "https://wx.jwnzn.com",
    "Connection": "close",
}


def write_log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", errors="replace") as file:
        file.write(f"[{ts}] {message}\n")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        old_path = CONFIG_DIR / "wechat_rpa_config.json"
        if old_path.exists():
            return json.loads(old_path.read_text(encoding="utf-8-sig"))
        raise RuntimeError("Missing config/charge_api_config.json")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def save_config(config: dict[str, Any]) -> None:
    backup_path = CONFIG_PATH.with_suffix(".json.bak")
    if CONFIG_PATH.exists():
        CONFIG_PATH.rename(backup_path)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    write_log("✅ charge_api_config.json 已自动更新（Cookie 已刷新）")


def get_random_ua() -> str:
    if random.random() < 0.35:
        return random.choice(UA_POOL)
    return UA_POOL[0]


def build_charge_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = dict(CHARGE_API_BASE_HEADERS)
    headers["User-Agent"] = get_random_ua()
    if auth := str(config.get("authorization") or "").strip():
        headers["Authorization"] = auth
    if cookie := str(config.get("cookie") or "").strip():
        headers["Cookie"] = cookie
    extra = config.get("headers")
    if isinstance(extra, dict):
        headers.update({str(k): str(v) for k, v in extra.items() if k and v is not None})
    return headers


def keep_alive_refresh_cookie(member_id: str, headers: dict[str, str]) -> None:
    try:
        payload = {"memberId": member_id, "miniAppType": "1"}
        write_log("🔄 执行 Cookie 自刷新（keep-alive）...")
        result, resp_headers = realtime_post_form_json(
            KEEP_ALIVE_URL, payload, headers, timeout=8.0, return_headers=True
        )
        new_set_cookie = resp_headers.get("set-cookie") or resp_headers.get("Set-Cookie")
        if new_set_cookie:
            config = load_config()
            if new_set_cookie != str(config.get("cookie") or "").strip():
                config["cookie"] = new_set_cookie
                save_config(config)
            else:
                write_log("Cookie 无变化")
    except Exception as e:
        write_log(f"Cookie 自刷新失败（不影响下单）: {e}")


def simulate_browse_station_detail(sn: str, member_id: str, headers: dict[str, str]) -> None:
    """模拟真实用户：打开插座详情页（触发 mp_parseCk.action）"""
    try:
        stations = load_stations()
        station = next((s for s in stations if str(s.get("device_code", "")).strip() == sn), None)
        if not station or not station.get("device_ck"):
            write_log(f"未找到 {sn} 的 device_ck，跳过详情页模拟")
            return

        device_ck = str(station["device_ck"])
        payload = {"ck": device_ck, "memberId": member_id, "miniAppType": "1"}

        write_log(f"📱 模拟浏览插座详情页 → {station.get('name', sn)}")
        realtime_post_form_json(PARSECK_URL, payload, headers, timeout=6.0)
        write_log("✅ 详情页浏览完成")
    except Exception as e:
        write_log(f"浏览详情页失败（不影响下单）: {e}")


def call_charge_api(sn: str, sid: int, amount_yuan: float, member_id: str, headers: dict[str, str], timeout: int = 15) -> dict[str, Any]:
    moneys = int(round(amount_yuan * 100))
    payload = OrderedDict([
        ("isSafeServer", "0"), ("safeServerMoney", "0"), ("sn", sn), ("sid", str(sid)),
        ("moneys", str(moneys)), ("payMoney", str(moneys)),
        ("memberId", member_id), ("miniAppType", "1"),
    ])

    delay = random.uniform(2.0, 4.5)
    write_log(f"🕒 模拟真人操作延时 {delay:.2f} 秒...")
    time.sleep(delay)

    return realtime_post_form_json(CHARGE_API_URL, payload, headers, timeout=float(timeout))


def run_charge(order: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str, str]:
    member_id = str(config.get("member_id", "")).strip()
    if not member_id:
        raise RuntimeError("配置缺少 member_id（充电用）")

    sn = str(order.get("device_code") or order.get("sn") or "").strip()
    if not sn:
        raise RuntimeError("订单缺少 device_code")

    sid = int(order.get("socket_no", 1))
    amount_yuan = float(order.get("amount_yuan", 1))
    order_id = str(order.get("id", order.get("client_order_id", "")))

    headers = build_charge_headers(config)

    # === 真实用户流程 ===
    keep_alive_refresh_cookie(member_id, headers)          # 1. 检查使用中订单
    simulate_browse_station_detail(sn, member_id, headers) # 2. 浏览插座详情页
    # =========================

    write_log(f"开始下单（模拟小程序完整流程） sn={sn} sid={sid} amount={amount_yuan}元")
    result = call_charge_api(sn, sid, amount_yuan, member_id, headers)

    write_log(f"API response: {json.dumps(result, ensure_ascii=False)}")

    msg = str(result.get("msg", "")).strip()
    normal = int(result.get("normal", 0) or 0)
    if normal == 1:
        return True, msg or "充电提交成功", f"api-{order_id}"
    return False, msg or "充电接口返回失败", f"api-{order_id}"


# 下面三个函数保持不变
def process_order(order: dict[str, Any]) -> dict[str, Any]:
    write_log(f"received order: {json.dumps(order, ensure_ascii=False)}")
    try:
        config = load_config()
        success, message, order_id = run_charge(order, config)
        return {"success": success, "message": message, "order_id": order_id}
    except Exception as err:
        write_log(f"error: {err}")
        return {"success": False, "message": str(err), "order_id": ""}


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
    return process_order(order)


def main() -> None:
    parser = argparse.ArgumentParser(description="中网充 执行器 - 真实小程序完整流程模拟（浏览详情页 + 自动Cookie + 随机UA + 真人延时）")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        order = {"id": "test001", "device_code": "13061856473", "socket_no": 1, "amount_yuan": 1}
        result = process_order(order)
    else:
        result = run_from_stdin()

    write_log(f"result: {json.dumps(result, ensure_ascii=False)}")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()