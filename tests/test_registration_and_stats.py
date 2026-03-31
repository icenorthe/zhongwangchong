from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

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
        "REGISTER_VISITOR_SUCCESS_LIMIT": "0",
        "REGISTER_VISITOR_WINDOW_HOURS": "168",
        "REGISTER_IP_SUCCESS_LIMIT": "20",
        "REGISTER_IP_WINDOW_HOURS": "24",
        "REGISTER_IP_ATTEMPT_LIMIT": "20",
        "REGISTER_IP_ATTEMPT_WINDOW_MINUTES": "60",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import services.mobile_charge_server as mobile_charge_server

    mobile_charge_server = importlib.reload(mobile_charge_server)
    mobile_charge_server.DB_PATH = tmp_path / "orders.db"
    mobile_charge_server.append_qjpay_log = lambda _message: None

    with TestClient(mobile_charge_server.app) as client:
        yield mobile_charge_server, client


def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "admin-test", "X-Admin-Password": "admin-secret"}


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_login_cookie_allows_admin_api_without_token_header(server):
    module, client = server

    login = client.post(
        "/api/admin/login",
        json={"username": module.ADMIN_USERNAME, "password": "admin-secret"},
    )
    assert login.status_code == 200
    assert login.json()["ok"] is True
    assert login.cookies.get(module.ADMIN_SESSION_COOKIE_NAME)

    stats = client.get("/api/admin/stats")
    assert stats.status_code == 200
    assert stats.json()["ok"] is True


def test_admin_password_falls_back_to_default_when_env_is_blank(monkeypatch, tmp_path):
    env = {
        "WORKER_ENABLED": "0",
        "PAYMENT_MODE": "balance",
        "ORDER_PAY_MODE": "balance",
        "ADMIN_TOKEN": "admin-test",
        "ADMIN_USERNAME": "icenorthe",
        "ADMIN_PASSWORD": "",
        "AGENT_TOKEN": "agent-test",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import services.mobile_charge_server as mobile_charge_server

    module = importlib.reload(mobile_charge_server)
    module.DB_PATH = tmp_path / "orders.db"
    module.append_qjpay_log = lambda _message: None

    with TestClient(module.app) as client:
        login = client.post(
            "/api/admin/login",
            json={"username": "icenorthe", "password": "www2003."},
        )
        assert login.status_code == 200, login.text


def insert_user(module, *, phone: str, created_at: str) -> int:
    with module.db_connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users
                (phone, password_hash, created_at, updated_at, balance_yuan, free_charge_count)
            VALUES
                (?, ?, ?, ?, 0, 0)
            """,
            (phone, module.hash_password("secret123"), created_at, created_at),
        )
        conn.commit()
        return int(cursor.lastrowid)


def insert_order(
    module,
    *,
    user_id: int,
    phone: str,
    created_at: str,
    status: str = "SUCCESS",
    amount_yuan: float = 1.0,
) -> None:
    with module.db_connect() as conn:
        conn.execute(
            """
            INSERT INTO orders
                (
                    user_id, pile_no, phone, minutes, remark, status, result_message,
                    vendor_order_id, created_at, updated_at, station_name, device_code,
                    socket_no, amount_yuan, payment_mode, payment_token,
                    balance_deducted, balance_refunded, free_charge_used
                )
            VALUES
                (?, ?, ?, 0, '', ?, '', '', ?, ?, 'test-station', ?, 1, ?, 'balance', '', 0, 0, 0)
            """,
            (user_id, "dev-test", phone, status, created_at, created_at, "dev-test", amount_yuan),
        )
        conn.commit()


def insert_recharge_request(
    module,
    *,
    user_id: int,
    phone: str,
    amount_yuan: float,
    status: str,
    created_at: str,
) -> None:
    with module.db_connect() as conn:
        conn.execute(
            """
            INSERT INTO recharge_requests
                (user_id, phone, amount_yuan, status, payment_method, note, created_at, updated_at)
            VALUES
                (?, ?, ?, ?, 'manual_transfer', '', ?, ?)
            """,
            (user_id, phone, amount_yuan, status, created_at, created_at),
        )
        conn.commit()


def insert_site_visitor(module, *, visitor_id: str, seen_at: str) -> None:
    with module.db_connect() as conn:
        conn.execute(
            """
            INSERT INTO site_visitors
                (visitor_id, first_seen_at, last_seen_at, first_path, last_path, visit_count, ip, user_agent)
            VALUES
                (?, ?, ?, '/', '/', 1, '127.0.0.1', 'pytest')
            """,
            (visitor_id, seen_at, seen_at),
        )
        conn.commit()


def test_register_starts_without_free_charge_bonus(server):
    module, client = server

    register = client.post(
        "/api/auth/register",
        json={"phone": "13800000100", "password": "secret123"},
    )

    assert register.status_code == 200, register.text
    assert int(register.json()["user"]["free_charge_count"]) == 0

    with module.db_connect() as conn:
        user = conn.execute(
            "SELECT free_charge_count FROM users WHERE phone = ?",
            ("13800000100",),
        ).fetchone()

    assert user is not None
    assert int(user["free_charge_count"] or 0) == 0


def test_registration_risk_blocks_repeat_registration_from_same_ip(server):
    module, client = server
    module.REGISTER_IP_SUCCESS_LIMIT = 1
    module.REGISTER_IP_WINDOW_HOURS = 168

    landing = client.get("/")
    assert landing.status_code == 200
    assert module.VISITOR_COOKIE_NAME in client.cookies

    first = client.post(
        "/api/auth/register",
        json={"phone": "13800000101", "password": "secret123"},
    )
    second = client.post(
        "/api/auth/register",
        json={"phone": "13800000102", "password": "secret123"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 429, second.text
    assert "\u5f53\u524d\u7f51\u7edc\u73af\u5883\u6ce8\u518c\u8fc7\u4e8e\u9891\u7e41" in second.json()["detail"]

    with module.db_connect() as conn:
        users_total = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        success_attempts = int(
            conn.execute(
                "SELECT COUNT(*) FROM registration_attempts WHERE status = 'SUCCESS'"
            ).fetchone()[0]
        )
        blocked_attempts = int(
            conn.execute(
                "SELECT COUNT(*) FROM registration_attempts WHERE status = 'BLOCKED'"
            ).fetchone()[0]
        )

    assert users_total == 1
    assert success_attempts == 1
    assert blocked_attempts == 1


def test_admin_stats_returns_growth_metrics(server):
    module, client = server
    now = datetime.now(UTC)
    user1_phone = "13800000201"
    user2_phone = "13800000202"
    user1 = insert_user(module, phone=user1_phone, created_at=(now - timedelta(days=6)).isoformat())
    user2 = insert_user(module, phone=user2_phone, created_at=(now - timedelta(days=2)).isoformat())

    insert_site_visitor(module, visitor_id="visitor-a", seen_at=(now - timedelta(days=6)).isoformat())
    insert_site_visitor(module, visitor_id="visitor-b", seen_at=(now - timedelta(days=3)).isoformat())
    insert_site_visitor(module, visitor_id="visitor-c", seen_at=(now - timedelta(days=1)).isoformat())

    insert_order(
        module,
        user_id=user1,
        phone=user1_phone,
        created_at=(now - timedelta(days=6)).isoformat(),
        status="SUCCESS",
    )
    insert_order(
        module,
        user_id=user1,
        phone=user1_phone,
        created_at=(now - timedelta(days=2)).isoformat(),
        status="SUCCESS",
    )
    insert_order(
        module,
        user_id=user2,
        phone=user2_phone,
        created_at=(now - timedelta(days=1)).isoformat(),
        status="SUCCESS",
    )

    insert_recharge_request(
        module,
        user_id=user2,
        phone=user2_phone,
        amount_yuan=10,
        status="APPROVED",
        created_at=(now - timedelta(days=1)).isoformat(),
    )

    response = client.get("/api/admin/stats", headers=admin_headers())
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["visit_count"] == 3
    assert data["register_count"] == 2
    assert data["first_order_count"] == 2
    assert data["recharge_user_count"] == 1
    assert data["repeat_7d_count"] == 1


def test_admin_can_update_user_note_and_list_it(server):
    module, client = server
    user_id = insert_user(
        module,
        phone="13800000210",
        created_at=datetime.now(UTC).isoformat(),
    )

    updated = client.post(
        f"/api/admin/users/{user_id}/note",
        headers=admin_headers(),
        json={"user_note": "老客户，线下确认过"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["user_note"] == "老客户，线下确认过"

    listed = client.get("/api/admin/users?limit=20", headers=admin_headers())
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json() if int(item["id"]) == user_id)
    assert row["user_note"] == "老客户，线下确认过"
    assert int(row["recharge_count"]) == 0


def test_admin_user_list_includes_last_order_at(server):
    module, client = server
    now = datetime.now(UTC)
    created_at = (now - timedelta(days=3)).isoformat()
    last_order_at = (now - timedelta(hours=6)).isoformat()
    user_id = insert_user(
        module,
        phone="13800000215",
        created_at=created_at,
    )
    insert_order(
        module,
        user_id=user_id,
        phone="13800000215",
        created_at=(now - timedelta(days=2)).isoformat(),
        status="SUCCESS",
        amount_yuan=1.0,
    )
    insert_order(
        module,
        user_id=user_id,
        phone="13800000215",
        created_at=last_order_at,
        status="SUCCESS",
        amount_yuan=2.0,
    )

    listed = client.get("/api/admin/users?limit=20", headers=admin_headers())
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json() if int(item["id"]) == user_id)
    assert row["created_at"] == created_at
    assert row["last_order_at"] == last_order_at


def test_admin_user_list_last_order_at_falls_back_to_phone_for_legacy_orders(server):
    module, client = server
    now = datetime.now(UTC)
    created_at = (now - timedelta(days=3)).isoformat()
    before_register = (now - timedelta(days=4)).isoformat()
    after_register = (now - timedelta(hours=8)).isoformat()
    user_id = insert_user(
        module,
        phone="13800000216",
        created_at=created_at,
    )

    with module.db_connect() as conn:
        conn.execute(
            """
            INSERT INTO orders
                (
                    user_id, pile_no, phone, minutes, remark, status, result_message,
                    vendor_order_id, created_at, updated_at, station_name, device_code,
                    socket_no, amount_yuan, payment_mode, payment_token,
                    balance_deducted, balance_refunded, free_charge_used
                )
            VALUES
                (NULL, 'dev-test', ?, 0, '', 'SUCCESS', '', '', ?, ?, 'test-station', 'dev-test', 1, 1.0, 'balance', '', 0, 0, 0)
            """,
            ("13800000216", before_register, before_register),
        )
        conn.execute(
            """
            INSERT INTO orders
                (
                    user_id, pile_no, phone, minutes, remark, status, result_message,
                    vendor_order_id, created_at, updated_at, station_name, device_code,
                    socket_no, amount_yuan, payment_mode, payment_token,
                    balance_deducted, balance_refunded, free_charge_used
                )
            VALUES
                (NULL, 'dev-test', ?, 0, '', 'SUCCESS', '', '', ?, ?, 'test-station', 'dev-test', 1, 1.0, 'balance', '', 0, 0, 0)
            """,
            ("13800000216", after_register, after_register),
        )
        conn.commit()

    listed = client.get("/api/admin/users?limit=20", headers=admin_headers())
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json() if int(item["id"]) == user_id)
    assert row["last_order_at"] == after_register


def test_admin_can_filter_only_users_with_approved_recharges(server):
    module, client = server
    now = datetime.now(UTC).isoformat()
    approved_user = insert_user(module, phone="13800000211", created_at=now)
    pending_user = insert_user(module, phone="13800000212", created_at=now)
    plain_user = insert_user(module, phone="13800000213", created_at=now)

    insert_recharge_request(
        module,
        user_id=approved_user,
        phone="13800000211",
        amount_yuan=10,
        status="APPROVED",
        created_at=now,
    )
    insert_recharge_request(
        module,
        user_id=pending_user,
        phone="13800000212",
        amount_yuan=10,
        status="PENDING",
        created_at=now,
    )

    listed = client.get(
        "/api/admin/users?limit=20&recharged_only=true",
        headers=admin_headers(),
    )
    assert listed.status_code == 200, listed.text
    ids = {int(item["id"]) for item in listed.json()}
    assert approved_user in ids
    assert pending_user not in ids
    assert plain_user not in ids

    row = next(item for item in listed.json() if int(item["id"]) == approved_user)
    assert int(row["recharge_count"]) == 1


def test_first_recharge_gives_single_bonus_without_stacking(server):
    module, client = server
    register = client.post(
        "/api/auth/register",
        json={"phone": "13800000501", "password": "secret123"},
    )
    assert register.status_code == 200, register.text
    assert int(register.json()["user"]["free_charge_count"]) == 0
    token = register.json()["token"]
    user_id = int(register.json()["user"]["id"])

    created = client.post(
        "/api/me/recharge-requests",
        headers=auth_headers(token),
        json={"amount_yuan": 20, "payment_method": "manual_transfer", "note": "first"},
    )
    assert created.status_code == 200, created.text
    request_id = int(created.json()["id"])

    approved = client.post(
        f"/api/admin/recharge-requests/{request_id}/approve",
        headers=admin_headers(),
        json={"review_note": "ok"},
    )
    assert approved.status_code == 200, approved.text

    with module.db_connect() as conn:
        recharge = conn.execute(
            "SELECT bonus_free_charge_count, bonus_free_charge_granted FROM recharge_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        user = conn.execute(
            "SELECT balance_yuan, free_charge_count FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    assert int(recharge["bonus_free_charge_count"] or 0) == 3
    assert int(recharge["bonus_free_charge_granted"] or 0) == 3
    assert float(user["balance_yuan"] or 0) == pytest.approx(20.0)
    assert int(user["free_charge_count"] or 0) == 3


def test_recharge_bonus_is_calculated_per_single_order_only(server):
    module, client = server
    register = client.post(
        "/api/auth/register",
        json={"phone": "13800000502", "password": "secret123"},
    )
    assert register.status_code == 200, register.text
    token = register.json()["token"]
    user_id = int(register.json()["user"]["id"])

    request_ids = []
    for amount in (10, 10):
        created = client.post(
            "/api/me/recharge-requests",
            headers=auth_headers(token),
            json={"amount_yuan": amount, "payment_method": "manual_transfer", "note": f"r{amount}"},
        )
        assert created.status_code == 200, created.text
        request_id = int(created.json()["id"])
        request_ids.append(request_id)
        approved = client.post(
            f"/api/admin/recharge-requests/{request_id}/approve",
            headers=admin_headers(),
            json={"review_note": "ok"},
        )
        assert approved.status_code == 200, approved.text

    with module.db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, bonus_free_charge_granted
            FROM recharge_requests
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        ).fetchall()
        user = conn.execute(
            "SELECT balance_yuan, free_charge_count FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    assert [int(row["bonus_free_charge_granted"] or 0) for row in rows] == [1, 1]
    assert float(user["balance_yuan"] or 0) == pytest.approx(20.0)
    assert int(user["free_charge_count"] or 0) == 2


def test_five_yuan_bonus_can_be_received_on_later_recharge_once(server):
    module, client = server
    register = client.post(
        "/api/auth/register",
        json={"phone": "13800000503", "password": "secret123"},
    )
    assert register.status_code == 200, register.text
    token = register.json()["token"]
    user_id = int(register.json()["user"]["id"])

    request_ids = []
    for amount in (1, 5, 5, 10):
        created = client.post(
            "/api/me/recharge-requests",
            headers=auth_headers(token),
            json={"amount_yuan": amount, "payment_method": "manual_transfer", "note": f"r{amount}"},
        )
        assert created.status_code == 200, created.text
        request_id = int(created.json()["id"])
        request_ids.append(request_id)
        approved = client.post(
            f"/api/admin/recharge-requests/{request_id}/approve",
            headers=admin_headers(),
            json={"review_note": "ok"},
        )
        assert approved.status_code == 200, approved.text

    with module.db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, amount_yuan, bonus_free_charge_granted
            FROM recharge_requests
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        ).fetchall()
        user = conn.execute(
            "SELECT balance_yuan, free_charge_count FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    assert [int(row["bonus_free_charge_granted"] or 0) for row in rows] == [0, 1, 0, 1]
    assert float(user["balance_yuan"] or 0) == pytest.approx(21.0)
    assert int(user["free_charge_count"] or 0) == 2
