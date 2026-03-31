from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def server(monkeypatch, tmp_path):
    env = {
        "WORKER_ENABLED": "0",
        "PAYMENT_MODE": "balance",
        "ORDER_PAY_MODE": "balance",
        "ADMIN_TOKEN": "admin-test",
        "ADMIN_PASSWORD": "admin-secret",
        "AGENT_TOKEN": "agent-test",
        "REQUIRE_AGENT_ONLINE_FOR_ORDERS": "0",
        "NO_LOAD_AUTO_REFUND_ENABLED": "0",
        "ORDER_RECENT_SUBMIT_COOLDOWN_MINUTES": "0",
        "ORDER_FAILURE_WINDOW_MINUTES": "0",
        "ORDER_FAILURE_THRESHOLD": "0",
        "ORDER_EMPTY_LOAD_COOLDOWN_MINUTES": "0",
        "PAYMENT_TOKEN_SECRET": "test-secret",
        "QJPAY_PID": "",
        "QJPAY_KEY": "",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import services.mobile_charge_server as mobile_charge_server

    mobile_charge_server = importlib.reload(mobile_charge_server)
    mobile_charge_server.DB_PATH = tmp_path / "orders.db"
    mobile_charge_server.append_qjpay_log = lambda _message: None

    with TestClient(mobile_charge_server.app) as client:
        yield mobile_charge_server, client


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "admin-test", "X-Admin-Password": "admin-secret"}


def agent_headers() -> dict[str, str]:
    return {"X-Agent-Token": "agent-test"}


def register_user(client: TestClient, phone: str) -> tuple[int, str]:
    response = client.post(
        "/api/auth/register",
        json={"phone": phone, "password": "secret123"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return int(data["user"]["id"]), str(data["token"])


def set_wallet(module, user_id: int, *, balance_yuan: float, free_charge_count: int) -> None:
    with module.db_connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET balance_yuan = ?, free_charge_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (balance_yuan, free_charge_count, module.now_iso(), user_id),
        )
        conn.commit()


def fetch_user(module, user_id: int):
    with module.db_connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def fetch_order(module, order_id: int):
    with module.db_connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def wallet_ledger_count(module, user_id: int) -> int:
    with module.db_connect() as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM wallet_ledger WHERE user_id = ?", (user_id,)).fetchone()[0]
        )


def recharge_request_count(module, user_id: int) -> int:
    with module.db_connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM recharge_requests WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )


def create_order(client: TestClient, token: str, *, device_code: str = "dev-01", amount_yuan: float = 1.0):
    return client.post(
        "/api/orders",
        headers=auth_headers(token),
        json={
            "station_id": "",
            "station_name": "test-station",
            "device_code": device_code,
            "socket_no": 1,
            "amount_yuan": amount_yuan,
            "remark": "",
            "payment_token": "",
        },
    )


def expected_order_total(module, amount_yuan: float, *, free_charge_used: int = 0) -> float:
    return float(module.order_total_cost_yuan(amount_yuan, free_charge_used))


def test_order_success_reserves_balance_up_front(server):
    module, client = server
    user_id, token = register_user(client, "13800000001")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    response = create_order(client, token)
    assert response.status_code == 200, response.text
    order_id = int(response.json()["id"])

    user = fetch_user(module, user_id)

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-1"},
    )
    assert complete.status_code == 200, complete.text

    order = fetch_order(module, order_id)
    user = fetch_user(module, user_id)
    assert str(order["status"]) == "SUCCESS"
    assert int(order["balance_deducted"]) == 1
    assert int(order["balance_refunded"]) == 0


def test_order_failure_refunds_reserved_balance(server):
    module, client = server
    user_id, token = register_user(client, "13800000002")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    response = create_order(client, token, device_code="dev-02")
    assert response.status_code == 200, response.text
    order_id = int(response.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": False, "message": "fail", "vendor_order_id": "vendor-2"},
    )
    assert complete.status_code == 200, complete.text

    order = fetch_order(module, order_id)
    user = fetch_user(module, user_id)
    assert str(order["status"]) == "FAILED"
    assert int(order["balance_deducted"]) == 1
    assert int(order["balance_refunded"]) == 1
    assert float(user["balance_yuan"]) == pytest.approx(2.0)


def test_order_rejects_when_balance_is_insufficient(server):
    module, client = server
    user_id, token = register_user(client, "13800000003")
    insufficient_balance = expected_order_total(module, 1.0) - 0.01
    set_wallet(module, user_id, balance_yuan=insufficient_balance, free_charge_count=0)

    response = create_order(client, token, device_code="dev-03")
    assert response.status_code == 402, response.text

    user = fetch_user(module, user_id)
    assert float(user["balance_yuan"]) == pytest.approx(insufficient_balance)


def test_concurrent_balance_orders_only_allow_one_success(server):
    module, client = server
    user_id, token = register_user(client, "13800000004")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    def submit(device_code: str):
        user = module.get_user_by_session_token(token)
        payload = module.OrderCreate(
            station_id="",
            station_name="concurrent-station",
            device_code=device_code,
            socket_no=1,
            amount_yuan=1.0,
            remark="",
            payment_token="",
        )
        try:
            order = module.create_order(payload, user)
            return ("ok", order.id)
        except module.HTTPException as err:
            return ("err", err.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, ("dev-04-a", "dev-04-b")))

    assert sorted(result[0] for result in results) == ["err", "ok"]
    assert [result for result in results if result[0] == "err"][0][1] == 402

    user = fetch_user(module, user_id)
    with module.db_connect() as conn:
        order_count = int(conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0])

    assert order_count == 1


def test_normalize_stop_reason_keeps_real_interrupt_reason(server):
    module, _client = server

    assert module.normalize_stop_reason("充电中断") == "充电中断"
    assert module.normalize_stop_reason("工作完成(达到预定时间)") == "达到预定时长"


def test_build_official_detail_preserves_unknown_stop_reason(server):
    module, _client = server

    detail = module.build_official_detail(
        {
            "orderEndMessage": "设备离线自动结束",
            "orderEndCode": 99,
            "sn": "dev-01",
            "sid": 1,
        }
    )

    assert detail["order_end_message"] == "设备离线自动结束"
    assert detail["order_end_code"] == 99


def test_manual_recharge_reject_path_keeps_balance_unchanged(server):
    module, client = server
    user_id, token = register_user(client, "13800000005")
    set_wallet(module, user_id, balance_yuan=0.0, free_charge_count=0)

    created = client.post(
        "/api/me/recharge-requests",
        headers=auth_headers(token),
        json={"amount_yuan": 5, "payment_method": "manual_transfer", "note": "manual"},
    )
    assert created.status_code == 200, created.text
    request_id = int(created.json()["id"])

    rejected = client.post(
        f"/api/admin/recharge-requests/{request_id}/reject",
        headers=admin_headers(),
        json={"review_note": "not paid"},
    )
    assert rejected.status_code == 200, rejected.text

    user = fetch_user(module, user_id)
    with module.db_connect() as conn:
        row = conn.execute("SELECT status FROM recharge_requests WHERE id = ?", (request_id,)).fetchone()

    assert str(row["status"]) == "REJECTED"
    assert float(user["balance_yuan"]) == pytest.approx(0.0)


def test_manual_recharge_reuses_existing_pending_request(server):
    module, client = server
    user_id, token = register_user(client, "13800000007")

    first = client.post(
        "/api/me/recharge-requests",
        headers=auth_headers(token),
        json={"amount_yuan": 5, "payment_method": "manual_transfer", "note": "manual"},
    )
    second = client.post(
        "/api/me/recharge-requests",
        headers=auth_headers(token),
        json={"amount_yuan": 5, "payment_method": "manual_transfer", "note": "manual"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["reused_pending"] is False
    assert second.json()["reused_pending"] is True
    assert int(second.json()["id"]) == int(first.json()["id"])
    assert recharge_request_count(module, user_id) == 1


def test_manual_recharge_blocks_second_pending_request_with_different_amount(server):
    module, client = server
    user_id, token = register_user(client, "13800000008")

    first = client.post(
        "/api/me/recharge-requests",
        headers=auth_headers(token),
        json={"amount_yuan": 5, "payment_method": "manual_transfer", "note": "manual"},
    )
    second = client.post(
        "/api/me/recharge-requests",
        headers=auth_headers(token),
        json={"amount_yuan": 8, "payment_method": "manual_transfer", "note": "manual"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert "已有待审核充值申请" in second.json()["detail"]
    assert recharge_request_count(module, user_id) == 1


def test_concurrent_manual_recharge_only_creates_one_pending_request(server):
    module, client = server
    user_id, token = register_user(client, "13800000009")

    def submit():
        user = module.get_user_by_session_token(token)
        assert user is not None
        with module.db_connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row, created = module.create_recharge_request(
                    conn,
                    user=user,
                    amount_yuan=5,
                    payment_method="manual_transfer",
                    note="manual",
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return int(row["id"]), created

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result() for future in (executor.submit(submit), executor.submit(submit))]

    assert {item[0] for item in results} == {results[0][0]}
    assert sorted(item[1] for item in results) == [False, True]
    assert recharge_request_count(module, user_id) == 1


def test_qjpay_recharge_notify_is_idempotent(server):
    module, client = server
    module.QJPAY_KEY = "qjpay-test-key"
    module.QJPAY_PID = "qjpay-test-pid"
    module.QJPAY_ENABLED = True

    user_id, token = register_user(client, "13800000006")
    set_wallet(module, user_id, balance_yuan=0.0, free_charge_count=0)

    created = client.post(
        "/api/me/recharge-requests",
        headers=auth_headers(token),
        json={"amount_yuan": 5, "payment_method": "manual_transfer", "note": "manual"},
    )
    assert created.status_code == 200, created.text
    request_id = int(created.json()["id"])

    params = {
        "out_trade_no": module.qjpay_build_out_trade_no(request_id),
        "trade_status": "TRADE_SUCCESS",
        "money": "5.00",
        "type": "wxpay",
        "sign_type": "MD5",
    }
    params["sign"] = module.qjpay_sign(params)

    first = client.post("/api/recharge/notify", data=params)
    second = client.post("/api/recharge/notify", data=params)

    assert first.json() == "success"
    assert second.json() == "success"

    user = fetch_user(module, user_id)
    with module.db_connect() as conn:
        request_row = conn.execute(
            "SELECT status FROM recharge_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

    assert str(request_row["status"]) == "APPROVED"
    assert float(user["balance_yuan"]) == pytest.approx(5.0)
    assert wallet_ledger_count(module, user_id) == 1


def test_my_orders_reconciles_processing_order_from_consume_record(server):
    module, client = server
    user_id, token = register_user(client, "13800000010")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-10", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])
    created_at = module.parse_iso(str(fetch_order(module, order_id)["created_at"]))
    assert created_at is not None
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)

    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'PROCESSING', updated_at = ? WHERE id = ?",
            (module.now_iso(), order_id),
        )
        conn.commit()

    module.set_consume_record_snapshot(
        [
            {
                "cid": "official-1001",
                "sn": "dev-10",
                "sid": 1,
                "startTime": official_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": (official_created_at + module.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "workTime": 1,
                "totalFee": 1.0,
                "refund": 0.0,
                "orderEndMessage": "达到预定时间",
                "orderEndPower": 0,
            }
        ],
        module.now_iso(),
    )
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    saved = fetch_order(module, order_id)
    assert str(saved["status"]) == "SUCCESS"
    assert str(saved["vendor_order_id"]) == "official-1001"
    assert str(saved["official_order_id"]) == "official-1001"
    assert str(order["status"]) == "SUCCESS"
    assert order["official_detail"]["cid"] == "official-1001"
    assert order["charge_state"] == "ENDED_LIVE"


def test_my_orders_keeps_persisted_official_detail_without_live_snapshot(server):
    module, client = server
    user_id, token = register_user(client, "13800000013")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-13", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])
    created_at = str(fetch_order(module, order_id)["created_at"])

    detail = {
        "cid": "official-keep-13",
        "device_code": "dev-13",
        "station_name": "test-station",
        "socket_no": 1,
        "start_time": created_at,
        "end_time": created_at,
        "work_time_minutes": 1,
        "refund": 0.0,
        "total_fee": 1.0,
        "pay_way": "wxpay",
        "order_end_message": "达到预定时长",
        "order_end_code": 1,
        "order_end_power": 0,
    }
    with module.db_connect() as conn:
        conn.execute(
            """
            UPDATE orders
            SET status = 'SUCCESS',
                official_order_id = ?,
                official_detail_json = ?,
                official_detail_updated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                "official-keep-13",
                module.json.dumps(detail, ensure_ascii=False),
                module.now_iso(),
                module.now_iso(),
                order_id,
            ),
        )
        conn.commit()

    module.set_consume_record_snapshot([], "")
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    assert order["official_detail"]["cid"] == "official-keep-13"
    assert order["official_detail"]["pay_way"] == "wxpay"


def test_my_orders_avoids_binding_same_official_record_to_wrong_order(server):
    module, client = server
    user_id, token = register_user(client, "13800000014")
    set_wallet(module, user_id, balance_yuan=5.0, free_charge_count=0)

    first = create_order(client, token, device_code="dev-14", amount_yuan=1.0)
    second = create_order(client, token, device_code="dev-14", amount_yuan=1.0)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_order_id = int(first.json()["id"])
    second_order_id = int(second.json()["id"])

    base = module.datetime.now(module.UTC)
    first_created_at = base.isoformat()
    second_created_at = (base + module.timedelta(minutes=5)).isoformat()
    official_created_at = (base + module.timedelta(minutes=5, seconds=10)).astimezone(
        module.OFFICIAL_TIMEZONE
    )

    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'SUCCESS', created_at = ?, updated_at = ? WHERE id = ?",
            (first_created_at, first_created_at, first_order_id),
        )
        conn.execute(
            "UPDATE orders SET status = 'SUCCESS', created_at = ?, updated_at = ? WHERE id = ?",
            (second_created_at, second_created_at, second_order_id),
        )
        conn.commit()

    module.set_consume_record_snapshot(
        [
            {
                "cid": "official-2002",
                "sn": "dev-14",
                "sid": 1,
                "startTime": official_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": (official_created_at + module.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "workTime": 1,
                "totalFee": 1.0,
                "refund": 0.0,
                "orderEndMessage": "达到预定时长",
                "orderEndPower": 0,
            }
        ],
        module.now_iso(),
    )
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    rows = {int(item["id"]): item for item in response.json()}

    first_saved = fetch_order(module, first_order_id)
    second_saved = fetch_order(module, second_order_id)

    assert rows[second_order_id]["official_detail"]["cid"] == "official-2002"
    assert rows[first_order_id]["official_detail"] == {}
    assert str(second_saved["official_order_id"]) == "official-2002"
    assert str(first_saved["official_order_id"] or "") == ""


def test_my_orders_auto_refunds_no_load_processing_order_from_consume_record(server):
    module, client = server
    module.NO_LOAD_AUTO_REFUND_ENABLED = True
    user_id, token = register_user(client, "13800000011")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-11", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])
    created_at = module.parse_iso(str(fetch_order(module, order_id)["created_at"]))
    assert created_at is not None
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)

    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'PROCESSING', updated_at = ? WHERE id = ?",
            (module.now_iso(), order_id),
        )
        conn.commit()

    module.set_consume_record_snapshot(
        [
            {
                "cid": "official-1002",
                "sn": "dev-11",
                "sid": 1,
                "startTime": official_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": (official_created_at + module.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "workTime": 1,
                "totalFee": 0.0,
                "refund": 1.0,
                "orderEndMessage": "\u7a7a\u8f7d",
                "orderEndPower": 0,
            }
        ],
        module.now_iso(),
    )
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    saved = fetch_order(module, order_id)
    user = fetch_user(module, user_id)
    assert str(saved["status"]) == "FAILED"
    assert int(saved["balance_refunded"] or 0) == 1
    assert float(user["balance_yuan"]) == pytest.approx(2.0)
    assert str(order["status"]) == "FAILED"
    assert order["result_message"] == module.NO_LOAD_AUTO_REFUND_MESSAGE


def test_my_orders_auto_refunds_no_load_and_returns_free_charge_count(server):
    module, client = server
    module.NO_LOAD_AUTO_REFUND_ENABLED = True
    user_id, token = register_user(client, "13800000012")
    set_wallet(module, user_id, balance_yuan=1.0, free_charge_count=1)

    created = create_order(client, token, device_code="dev-12", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    created_order = created.json()
    order_id = int(created_order["id"])
    assert int(created_order["free_charge_used"] or 0) == 1
    assert float(created_order["service_fee_yuan"]) == pytest.approx(0.0)

    created_at = module.parse_iso(str(fetch_order(module, order_id)["created_at"]))
    assert created_at is not None
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)

    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'PROCESSING', updated_at = ? WHERE id = ?",
            (module.now_iso(), order_id),
        )
        conn.commit()

    module.set_consume_record_snapshot(
        [
            {
                "cid": "official-1003",
                "sn": "dev-12",
                "sid": 1,
                "startTime": official_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": (official_created_at + module.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "workTime": 1,
                "totalFee": 0.0,
                "refund": 1.0,
                "orderEndMessage": "\u7a7a\u8f7d",
                "orderEndPower": 0,
            }
        ],
        module.now_iso(),
    )
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    saved = fetch_order(module, order_id)
    user = fetch_user(module, user_id)
    assert str(saved["status"]) == "FAILED"
    assert int(saved["balance_refunded"] or 0) == 1
    assert int(saved["free_charge_used"] or 0) == 1
    assert float(user["balance_yuan"]) == pytest.approx(1.0)
    assert int(user["free_charge_count"] or 0) == 1
    assert str(order["status"]) == "FAILED"
    assert int(order["free_charge_used"] or 0) == 1
    assert float(order["service_fee_yuan"]) == pytest.approx(0.0)
    assert order["result_message"] == module.NO_LOAD_AUTO_REFUND_MESSAGE
