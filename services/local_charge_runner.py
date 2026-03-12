from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

try:
    from services.project_paths import CONFIG_DIR, LOG_DIR
except ImportError:
    from project_paths import CONFIG_DIR, LOG_DIR


LOG_PATH = LOG_DIR / "local_charge_runner.log"
CONFIG_PATH = CONFIG_DIR / "charge_api_config.json"

CHARGE_API_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_balancePay.action"
CHARGE_API_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
        "MiniProgramEnv/Windows WindowsWechat/WMPF"
    ),
    "Authorization": "",
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


def call_charge_api(sn: str, sid: int, amount_yuan: float, member_id: str, timeout: int = 15) -> dict[str, Any]:
    moneys = int(round(amount_yuan * 100))
    body = urllib.parse.urlencode(
        {
            "isSafeServer": "0",
            "safeServerMoney": "0",
            "sn": sn,
            "sid": str(sid),
            "moneys": str(moneys),
            "payMoney": str(moneys),
            "memberId": member_id,
            "miniAppType": "1",
        }
    ).encode("utf-8")
    req = urllib.request.Request(CHARGE_API_URL, data=body, method="POST", headers=CHARGE_API_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw = raw_bytes.decode("gb18030", errors="replace")
    return json.loads(raw)


def run_charge(order: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str, str]:
    member_id = str(config.get("member_id", "")).strip()
    if not member_id:
        raise RuntimeError("配置缺少 member_id")

    sn = str(order.get("device_code") or order.get("sn") or "").strip()
    if not sn:
        raise RuntimeError("订单缺少 device_code")

    sid = int(order.get("socket_no", 1))
    amount_yuan = float(order.get("amount_yuan", 1))
    order_id = str(order.get("id", order.get("client_order_id", "")))

    write_log(f"calling charge API: sn={sn} sid={sid} amount={amount_yuan}元 member={member_id}")
    result = call_charge_api(sn, sid, amount_yuan, member_id)
    write_log(f"API response: {json.dumps(result, ensure_ascii=False)}")

    msg = str(result.get("msg", "")).strip()
    normal = int(result.get("normal", 0) or 0)

    if normal == 1:
        return True, msg or "充电提交成功", f"api-{order_id}"
    return False, msg or "充电接口返回失败", f"api-{order_id}"


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
    parser = argparse.ArgumentParser(description="中网充 HTTP API 充电执行器")
    parser.add_argument("--test", action="store_true", help="用测试订单跑一次")
    args = parser.parse_args()

    if args.test:
        order = {
            "id": "test001",
            "device_code": "13061856473",
            "socket_no": 1,
            "amount_yuan": 1,
        }
        result = process_order(order)
    else:
        result = run_from_stdin()

    write_log(f"result: {json.dumps(result, ensure_ascii=False)}")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
