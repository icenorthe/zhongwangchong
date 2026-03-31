from __future__ import annotations

import importlib
import json

from fastapi.testclient import TestClient


def test_local_bridge_rejects_missing_or_invalid_token(monkeypatch):
    monkeypatch.setenv("LOCAL_BRIDGE_TOKEN", "bridge-test-token")

    import services.local_bridge_api as local_bridge_api

    local_bridge_api = importlib.reload(local_bridge_api)
    monkeypatch.setattr(
        local_bridge_api,
        "run_local_command",
        lambda order: (True, "ok", f"local-{order['client_order_id']}"),
    )

    payload = {
        "station_name": "test-station",
        "device_code": "dev-01",
        "socket_no": 1,
        "amount_yuan": 1.0,
        "remark": "",
        "client_order_id": 123,
        "pile_no": "dev-01",
    }

    with TestClient(local_bridge_api.app) as client:
        missing = client.post("/api/start-charge", json=payload)
        assert missing.status_code == 401, missing.text

        wrong = client.post(
            "/api/start-charge",
            headers={"Authorization": "Bearer wrong-token"},
            json=payload,
        )
        assert wrong.status_code == 401, wrong.text


def test_local_bridge_accepts_valid_bearer_token(monkeypatch):
    monkeypatch.setenv("LOCAL_BRIDGE_TOKEN", "bridge-test-token")

    import services.local_bridge_api as local_bridge_api

    local_bridge_api = importlib.reload(local_bridge_api)
    monkeypatch.setattr(
        local_bridge_api,
        "run_local_command",
        lambda order: (True, f"accepted {order['device_code']}", "local-456"),
    )

    payload = {
        "station_name": "test-station",
        "device_code": "dev-02",
        "socket_no": 2,
        "amount_yuan": 2.0,
        "remark": "",
        "client_order_id": 456,
        "pile_no": "dev-02",
    }

    with TestClient(local_bridge_api.app) as client:
        response = client.post(
            "/api/start-charge",
            headers={"Authorization": "Bearer bridge-test-token"},
            json=payload,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "success": True,
            "message": "accepted dev-02",
            "order_id": "local-456",
        }


def test_cloud_agent_bridge_runner_sends_authorization_header(monkeypatch):
    import services.cloud_agent as cloud_agent

    cloud_agent = importlib.reload(cloud_agent)
    captured: dict[str, str] = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"success": True, "message": "bridge success", "order_id": "bridge-1"}
            ).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        headers = dict(request.header_items())
        captured["authorization"] = headers.get("Authorization", "")
        captured["content_type"] = headers.get("Content-type", "")
        captured["timeout"] = str(timeout)
        return DummyResponse()

    monkeypatch.setattr(cloud_agent.urllib.request, "urlopen", fake_urlopen)

    ok, message, order_id = cloud_agent.run_bridge_runner(
        "http://127.0.0.1:9000/api/start-charge",
        15,
        {
            "id": 77,
            "station_name": "test-station",
            "device_code": "dev-77",
            "socket_no": 1,
            "amount_yuan": 1.0,
            "remark": "",
        },
        "bridge-test-token",
    )

    assert ok is True
    assert message == "bridge success"
    assert order_id == "bridge-1"
    assert captured["authorization"] == "Bearer bridge-test-token"
    assert captured["content_type"] == "application/json"
    assert captured["timeout"] == "15"
