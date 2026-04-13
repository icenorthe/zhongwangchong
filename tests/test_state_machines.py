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


def test_estimated_finish_at_keeps_same_day_when_not_crossing_pause(server):
    module, _client = server
    local_start = module.datetime(2026, 4, 2, 18, 0, tzinfo=module.OFFICIAL_TIMEZONE)

    estimated_finish = module.parse_iso(module.estimated_finish_at(local_start.astimezone(module.UTC).isoformat(), 1.0))

    assert estimated_finish is not None
    assert estimated_finish.astimezone(module.OFFICIAL_TIMEZONE) == module.datetime(
        2026, 4, 2, 21, 27, tzinfo=module.OFFICIAL_TIMEZONE
    )


def test_estimated_finish_at_skips_overnight_pause_window(server):
    module, _client = server
    local_start = module.datetime(2026, 4, 2, 22, 30, tzinfo=module.OFFICIAL_TIMEZONE)

    estimated_finish = module.parse_iso(module.estimated_finish_at(local_start.astimezone(module.UTC).isoformat(), 1.0))

    assert estimated_finish is not None
    assert estimated_finish.astimezone(module.OFFICIAL_TIMEZONE) == module.datetime(
        2026, 4, 3, 8, 57, tzinfo=module.OFFICIAL_TIMEZONE
    )


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


def test_admin_can_retry_processing_order(server):
    module, client = server
    user_id, token = register_user(client, "13800000013")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    response = create_order(client, token, device_code="dev-13")
    assert response.status_code == 200, response.text
    order_id = int(response.json()["id"])

    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'PROCESSING', result_message = '设备执行指令出错', updated_at = ? WHERE id = ?",
            (module.now_iso(), order_id),
        )
        conn.commit()

    retried = client.post(f"/api/admin/orders/{order_id}/retry", headers=admin_headers())
    assert retried.status_code == 200, retried.text

    order = fetch_order(module, order_id)
    assert str(order["status"]) == "PENDING"
    assert str(order["result_message"] or "") == ""


def test_admin_retry_rejects_success_order(server):
    module, client = server
    user_id, token = register_user(client, "13800000014")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    response = create_order(client, token, device_code="dev-14")
    assert response.status_code == 200, response.text
    order_id = int(response.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-14"},
    )
    assert complete.status_code == 200, complete.text

    retried = client.post(f"/api/admin/orders/{order_id}/retry", headers=admin_headers())
    assert retried.status_code == 409, retried.text


def test_admin_stats_auto_fails_timed_out_processing_order(server):
    module, client = server
    user_id, token = register_user(client, "13800000015")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    response = create_order(client, token, device_code="dev-15")
    assert response.status_code == 200, response.text
    order_id = int(response.json()["id"])

    timed_out_at = (module.datetime.now(module.UTC) - module.timedelta(seconds=module.PROCESSING_TIMEOUT_SECONDS + 5)).isoformat()
    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'PROCESSING', result_message = '', updated_at = ? WHERE id = ?",
            (timed_out_at, order_id),
        )
        conn.commit()

    stats = client.get("/api/admin/stats", headers=admin_headers())
    assert stats.status_code == 200, stats.text
    assert int(stats.json()["auto_failed_processing"] or 0) >= 1

    order = fetch_order(module, order_id)
    user = fetch_user(module, user_id)
    assert str(order["status"]) == "FAILED"
    assert str(order["result_message"]) == module.PROCESSING_TIMEOUT_MESSAGE
    assert int(order["balance_refunded"] or 0) == 1
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


def test_build_consume_match_candidate_allows_delayed_official_start(server):
    module, _client = server
    order = {
        "id": 17,
        "device_code": "15071177319",
        "socket_no": 9,
        "amount_yuan": 3.0,
        "created_at": "2026-04-02T11:41:01.916359+00:00",
    }
    record = {
        "cid": "1507117731909020526040220071473",
        "sn": "15071177319",
        "sid": 9,
        "startTime": "2026-04-02 20:07:17",
        "endTime": "2026-04-03 08:32:45",
        "totalFee": 1.57,
        "refund": 1.43,
    }

    candidate = module.build_consume_match_candidate(order, record)

    assert candidate is not None
    assert candidate["cid"] == "1507117731909020526040220071473"


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
    assert float(order["consumed_amount_yuan"]) == pytest.approx(1.0)
    assert float(order["refund_amount_yuan"]) == pytest.approx(0.0)
    assert float(order["actual_paid_yuan"]) == pytest.approx(1.5)
    assert bool(order["settlement_ready"]) is True


def test_my_orders_keeps_charging_when_consume_record_only_has_live_end_time(server):
    module, client = server
    user_id, token = register_user(client, "13800000012")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-12", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-12"},
    )
    assert complete.status_code == 200, complete.text

    created_at = module.parse_iso(str(fetch_order(module, order_id)["created_at"]))
    assert created_at is not None
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)

    module.set_consume_record_snapshot(
        [
            {
                "cid": "official-live-12",
                "sn": "dev-12",
                "sid": 1,
                "startTime": official_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": (official_created_at + module.timedelta(minutes=90)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "workTime": 15,
                "totalFee": 0.3,
                "refund": 0.7,
                "payWay": "wxpay",
                "orderEndMessage": "",
                "orderEndCode": 0,
                "orderEndPower": 0,
            }
        ],
        module.now_iso(),
    )
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    assert order["official_detail"]["cid"] == "official-live-12"
    assert order["official_detail"]["end_time"] != ""
    assert order["charge_state"] == "CHARGING_ESTIMATED"
    assert order["charge_finished_at"] == ""


def test_my_orders_keeps_charging_when_consume_record_has_ambiguous_end_markers(server):
    module, client = server
    user_id, token = register_user(client, "13800000025")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-25", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-25"},
    )
    assert complete.status_code == 200, complete.text

    created_at = module.parse_iso(str(fetch_order(module, order_id)["created_at"]))
    assert created_at is not None
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)

    module.set_consume_record_snapshot(
        [
            {
                "cid": "official-live-25",
                "sn": "dev-25",
                "sid": 1,
                "startTime": official_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": "",
                "workTime": 18,
                "totalFee": 0.36,
                "refund": 0.64,
                "payWay": "wxpay",
                "orderEndMessage": "",
                "orderEndCode": 14,
                "orderEndPower": 280,
            }
        ],
        module.now_iso(),
    )
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")

    first = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    second = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_order = first.json()[0]
    second_order = second.json()[0]

    assert first_order["official_detail"]["cid"] == "official-live-25"
    assert first_order["official_detail"]["order_end_code"] == 14
    assert first_order["official_detail"]["order_end_power"] == 280
    assert first_order["charge_state"] == "CHARGING_ESTIMATED"
    assert first_order["charge_finished_at"] == ""
    assert second_order["charge_state"] == "CHARGING_ESTIMATED"
    assert second_order["charge_finished_at"] == ""


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


def test_my_orders_preserves_official_end_time_for_finished_history_order(server):
    module, client = server
    user_a_id, token_a = register_user(client, "13800000020")
    user_b_id, token_b = register_user(client, "13800000021")
    set_wallet(module, user_a_id, balance_yuan=5.0, free_charge_count=0)
    set_wallet(module, user_b_id, balance_yuan=5.0, free_charge_count=0)

    created_a = create_order(client, token_a, device_code="dev-20-a", amount_yuan=1.0)
    assert created_a.status_code == 200, created_a.text
    order_a_id = int(created_a.json()["id"])

    created_b = create_order(client, token_b, device_code="dev-20-b", amount_yuan=1.0)
    assert created_b.status_code == 200, created_b.text

    official_detail = {
        "cid": "official-keep-20",
        "device_code": "dev-20-a",
        "station_name": "test-station",
        "socket_no": 1,
        "start_time": "2026-04-02 08:00:00",
        "end_time": "2026-04-02 10:15:00",
        "work_time_minutes": 135,
        "refund": 0.0,
        "total_fee": 1.0,
        "pay_way": "wxpay",
        "order_end_message": "达到预定时长",
        "order_end_code": 1,
        "order_end_power": 0,
    }
    created_at = module.datetime(2026, 4, 2, 8, 0, tzinfo=module.UTC).isoformat()
    with module.db_connect() as conn:
        conn.execute(
            """
            UPDATE orders
            SET status = 'SUCCESS',
                created_at = ?,
                updated_at = ?,
                official_order_id = ?,
                official_detail_json = ?,
                official_detail_updated_at = ?
            WHERE id = ?
            """,
            (
                created_at,
                module.now_iso(),
                "official-keep-20",
                module.json.dumps(official_detail, ensure_ascii=False),
                module.now_iso(),
                order_a_id,
            ),
        )
        conn.commit()

    module.build_realtime_snapshot_for_orders = lambda rows: (
        {
            ("dev-20-a", 1): {
                "start_time": "2026-04-06 09:00:00",
                "end_time": "2026-04-06 12:00:00",
                "remain_seconds": 3600,
            },
            ("dev-20-b", 1): {
                "start_time": "2026-04-06 09:00:00",
                "end_time": "2026-04-06 12:00:00",
                "remain_seconds": 3600,
            },
        },
        {},
        "",
    )
    module.set_consume_record_snapshot([], "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token_a))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    expected_end = module.parse_official_datetime("2026-04-02 10:15:00")
    assert expected_end is not None
    assert order["official_detail"]["cid"] == "official-keep-20"
    assert order["charge_state"] == "ENDED_LIVE"
    assert order["charge_finished_at"] == expected_end.isoformat()
    assert order["realtime_status"] == ""


def test_my_orders_prefers_station_realtime_over_stale_using_order_snapshot(server):
    module, client = server
    user_id, token = register_user(client, "13800000016")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-16", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-16"},
    )
    assert complete.status_code == 200, complete.text

    module.set_consume_record_snapshot([], "")
    module.build_realtime_snapshot_for_orders = lambda rows: (
        {
            ("dev-16", 1): {
                "start_time": "2026-04-03 07:00:00",
                "end_time": "2026-04-03 10:00:00",
                "remain_seconds": 3600,
            }
        },
        {
            "dev-16": {
                "ok": True,
                "message": "",
                "products": [{"sid": 1, "state": 0}],
            }
        },
        "",
    )

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    assert order["realtime_status"] == "空闲"
    assert order["realtime_source"] == "station_realtime"
    assert order["charge_state"] == "ENDED_LIVE"
    assert order["charge_finished_at"] == ""


def test_my_orders_uses_agent_socket_overview_when_live_realtime_is_unavailable(server):
    module, client = server
    user_id, token = register_user(client, "13800000017")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-17", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-17"},
    )
    assert complete.status_code == 200, complete.text

    module.PREFER_AGENT_SNAPSHOT = True
    module.ALLOW_STALE_AGENT_SNAPSHOT = True
    module.load_stations = lambda: [
        {
            "id": "station-17",
            "name": "test-station",
            "region": "test-region",
            "device_code": "dev-17",
            "device_ck": "test-ck",
            "socket_count": 10,
            "disabled_sockets": [],
        }
    ]
    module.latest_agent_socket_overview = lambda allow_stale=False: [
        {
            "region": "test-region",
            "stations": [
                {
                    "device_code": "dev-17",
                    "realtime_ok": True,
                    "query_message": "",
                    "sockets": [{"socket_no": 1, "status": "空闲", "detail": ""}],
                }
            ],
        }
    ]
    module.fetch_using_orders = lambda member_id: (
        {
            ("dev-17", 1): {
                "start_time": "2026-04-03 07:00:00",
                "end_time": "2026-04-03 10:00:00",
                "remain_seconds": 3600,
            }
        },
        "",
    )

    def fail_fetch_station_realtime(*_args, **_kwargs):
        raise AssertionError("live realtime should not be queried when agent snapshot exists")

    module.fetch_station_realtime = fail_fetch_station_realtime
    module.set_consume_record_snapshot([], "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    assert order["realtime_status"] == "空闲"
    assert order["charge_state"] == "ENDED_LIVE"
    assert order["charge_finished_at"] == ""


def test_my_orders_keeps_order_charging_when_socket_is_busy_but_using_snapshot_misses(server):
    module, client = server
    user_id, token = register_user(client, "13800000018")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-18", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-18"},
    )
    assert complete.status_code == 200, complete.text

    module.PREFER_AGENT_SNAPSHOT = True
    module.ALLOW_STALE_AGENT_SNAPSHOT = True
    module.load_stations = lambda: [
        {
            "id": "station-18",
            "name": "test-station",
            "region": "test-region",
            "device_code": "dev-18",
            "device_ck": "test-ck",
            "socket_count": 10,
            "disabled_sockets": [],
        }
    ]
    module.latest_agent_socket_overview = lambda allow_stale=False: [
        {
            "region": "test-region",
            "stations": [
                {
                    "device_code": "dev-18",
                    "realtime_ok": True,
                    "query_message": "",
                    "sockets": [{"socket_no": 1, "status": "充电中", "detail": ""}],
                }
            ],
        }
    ]
    module.fetch_using_orders = lambda member_id: ({}, "")
    module.fetch_station_realtime = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("live realtime should not be queried when agent snapshot exists")
    )
    module.set_consume_record_snapshot([], "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    assert order["realtime_status"] == "使用中"
    assert order["charge_state"] == "CHARGING_LIVE"
    assert order["charge_finished_at"] == ""


def test_admin_orders_does_not_tick_end_time_for_active_busy_order_without_using_snapshot(server):
    module, client = server
    user_id, token = register_user(client, "13800000022")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-22", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-22"},
    )
    assert complete.status_code == 200, complete.text

    module.PREFER_AGENT_SNAPSHOT = True
    module.ALLOW_STALE_AGENT_SNAPSHOT = True
    module.load_stations = lambda: [
        {
            "id": "station-22",
            "name": "test-station",
            "region": "test-region",
            "device_code": "dev-22",
            "device_ck": "test-ck",
            "socket_count": 10,
            "disabled_sockets": [],
        }
    ]
    module.latest_agent_socket_overview = lambda allow_stale=False: [
        {
            "region": "test-region",
            "stations": [
                {
                    "device_code": "dev-22",
                    "realtime_ok": True,
                    "query_message": "",
                    "sockets": [{"socket_no": 1, "status": "充电中", "detail": ""}],
                }
            ],
        }
    ]
    module.fetch_using_orders = lambda member_id: ({}, "")
    module.fetch_station_realtime = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("live realtime should not be queried when agent snapshot exists")
    )
    module.set_consume_record_snapshot([], "")

    response = client.get("/api/orders?limit=20", headers=admin_headers())
    assert response.status_code == 200, response.text
    order = response.json()[0]

    assert order["id"] == order_id
    assert order["realtime_status"] == "使用中"
    assert order["charge_state"] == "CHARGING_LIVE"
    assert order["charge_finished_at"] == ""


def test_shared_member_id_does_not_leak_latest_busy_status_across_accounts(server):
    module, client = server
    user_a_id, token_a = register_user(client, "13800000023")
    user_b_id, token_b = register_user(client, "13800000024")
    set_wallet(module, user_a_id, balance_yuan=5.0, free_charge_count=0)
    set_wallet(module, user_b_id, balance_yuan=5.0, free_charge_count=0)

    first = create_order(client, token_a, device_code="dev-23", amount_yuan=1.0)
    second = create_order(client, token_b, device_code="dev-23", amount_yuan=1.0)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_order_id = int(first.json()["id"])
    second_order_id = int(second.json()["id"])

    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'SUCCESS', updated_at = ? WHERE id IN (?, ?)",
            (module.now_iso(), first_order_id, second_order_id),
        )
        conn.commit()

    base = module.datetime(2026, 4, 6, 9, 0, tzinfo=module.UTC)
    first_created_at = (base - module.timedelta(hours=2)).isoformat()
    second_created_at = base.isoformat()
    with module.db_connect() as conn:
        conn.execute("UPDATE orders SET created_at = ?, updated_at = ? WHERE id = ?", (first_created_at, first_created_at, first_order_id))
        conn.execute("UPDATE orders SET created_at = ?, updated_at = ? WHERE id = ?", (second_created_at, second_created_at, second_order_id))
        conn.commit()

    module.PREFER_AGENT_SNAPSHOT = True
    module.ALLOW_STALE_AGENT_SNAPSHOT = True
    module.load_stations = lambda: [
        {
            "id": "station-23",
            "name": "test-station",
            "region": "test-region",
            "device_code": "dev-23",
            "device_ck": "test-ck",
            "socket_count": 10,
            "disabled_sockets": [],
        }
    ]
    module.latest_agent_socket_overview = lambda allow_stale=False: [
        {
            "region": "test-region",
            "stations": [
                {
                    "device_code": "dev-23",
                    "realtime_ok": True,
                    "query_message": "",
                    "sockets": [{"socket_no": 1, "status": "充电中", "detail": ""}],
                }
            ],
        }
    ]
    module.fetch_using_orders = lambda member_id: (
        {
            ("dev-23", 1): {
                "start_time": "2026-04-06 17:00:00",
                "end_time": "2026-04-06 20:00:00",
                "remain_seconds": 3600,
            }
        },
        "",
    )
    module.fetch_station_realtime = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("live realtime should not be queried when agent snapshot exists")
    )
    module.set_consume_record_snapshot([], "")

    response_a = client.get("/api/me/orders?limit=20", headers=auth_headers(token_a))
    response_b = client.get("/api/me/orders?limit=20", headers=auth_headers(token_b))
    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text

    order_a = response_a.json()[0]
    order_b = response_b.json()[0]

    assert order_a["id"] == first_order_id
    assert order_a["realtime_status"] == ""
    assert order_a["charge_state"] == "CHARGING_ESTIMATED"
    assert order_b["id"] == second_order_id
    assert order_b["realtime_status"] == "使用中"
    assert order_b["charge_state"] == "CHARGING_LIVE"
    assert order_b["charge_finished_at"] == ""


def test_order_lists_merge_using_orders_across_charge_and_status_member_ids(server):
    module, client = server
    user_id, token = register_user(client, "13800000020")
    set_wallet(module, user_id, balance_yuan=2.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-20", amount_yuan=1.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    complete = client.post(
        f"/api/agent/orders/{order_id}/complete",
        headers=agent_headers(),
        json={"success": True, "message": "ok", "vendor_order_id": "vendor-20"},
    )
    assert complete.status_code == 200, complete.text

    module.configured_status_member_id = lambda: "status-member"
    module.configured_charge_member_id = lambda: "charge-member"
    module.load_stations = lambda: [
        {
            "id": "station-20",
            "name": "test-station",
            "region": "test-region",
            "device_code": "dev-20",
            "device_ck": "test-ck",
            "socket_count": 10,
            "disabled_sockets": [],
        }
    ]
    requested_member_ids: list[str] = []

    def fake_fetch_using_orders(member_id: str):
        requested_member_ids.append(member_id)
        if member_id == "status-member":
            return {}, ""
        if member_id == "charge-member":
            return {
                ("dev-20", 1): {
                    "status": "using",
                    "detail": "",
                    "station_name": "test-station",
                    "start_time": "2026-04-03 07:00:00",
                    "end_time": "2026-04-03 10:00:00",
                    "remain_seconds": 3600,
                }
            }, ""
        raise AssertionError(f"unexpected member id: {member_id}")

    module.fetch_using_orders = fake_fetch_using_orders
    module.build_realtime_by_device_from_agent_snapshot = lambda _device_codes: {
        "dev-20": {
            "ok": True,
            "message": "",
            "products": [{"sid": 1, "state": 1}],
        }
    }
    module.set_consume_record_snapshot([], "")

    admin_response = client.get("/api/orders?limit=20", headers=admin_headers())
    assert admin_response.status_code == 200, admin_response.text
    user_response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert user_response.status_code == 200, user_response.text

    for payload in (admin_response.json()[0], user_response.json()[0]):
        assert payload["realtime_status"] == "\u4f7f\u7528\u4e2d"
        assert payload["charge_state"] == "CHARGING_LIVE"
        assert payload["charge_finished_at"] == ""

    assert "status-member" in requested_member_ids
    assert "charge-member" in requested_member_ids


def test_my_orders_loads_official_detail_from_charge_member_id_when_status_member_id_misses(server):
    module, client = server
    user_id, token = register_user(client, "13800000019")
    set_wallet(module, user_id, balance_yuan=5.0, free_charge_count=0)

    created = create_order(client, token, device_code="dev-19", amount_yuan=3.0)
    assert created.status_code == 200, created.text
    order_id = int(created.json()["id"])

    with module.db_connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'SUCCESS', result_message = '支付成功', vendor_order_id = ?, updated_at = ? WHERE id = ?",
            ("api-19", module.now_iso(), order_id),
        )
        conn.commit()

    created_at = module.parse_iso(str(fetch_order(module, order_id)["created_at"]))
    assert created_at is not None
    official_created_at = created_at.astimezone(module.OFFICIAL_TIMEZONE)

    charge_member_records = [
        {
            "cid": "official-19",
            "sn": "dev-19",
            "sid": 1,
            "startTime": official_created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": (official_created_at + module.timedelta(minutes=325)).strftime("%Y-%m-%d %H:%M:%S"),
            "workTime": 325,
            "totalFee": 1.57,
            "refund": 1.43,
            "payWay": "余额支付",
            "orderEndMessage": "充电中断",
            "orderEndCode": 14,
            "orderEndPower": 0,
        }
    ]

    def fake_fetch_consume_records_for_items(member_id, items, **kwargs):
        if member_id == "charge-member":
            return charge_member_records, "获取成功"
        return [], "获取成功"

    module.fetch_consume_records_for_items = fake_fetch_consume_records_for_items
    module.configured_official_record_member_ids = lambda: ["charge-member", "status-member"]
    module.build_realtime_snapshot_for_orders = lambda rows: ({}, {}, "")
    module.set_consume_record_snapshot([], "")

    response = client.get("/api/me/orders?limit=20", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    order = response.json()[0]

    assert order["official_detail"]["cid"] == "official-19"
    assert order["official_detail"]["total_fee"] == pytest.approx(1.57)
    assert order["official_detail"]["refund"] == pytest.approx(1.43)
    assert order["charge_state"] == "ENDED_LIVE"


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
    assert float(order["consumed_amount_yuan"]) == pytest.approx(0.0)
    assert float(order["refund_amount_yuan"]) == pytest.approx(1.5)
    assert float(order["actual_paid_yuan"]) == pytest.approx(0.0)
    assert bool(order["settlement_ready"]) is True


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
    assert float(order["consumed_amount_yuan"]) == pytest.approx(0.0)
    assert float(order["refund_amount_yuan"]) == pytest.approx(1.0)
    assert float(order["actual_paid_yuan"]) == pytest.approx(0.0)
    assert bool(order["settlement_ready"]) is True
