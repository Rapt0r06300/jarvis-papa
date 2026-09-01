from fastapi.testclient import TestClient

from jarvis_papa.app import app

client = TestClient(app)


def test_readiness_endpoint_reports_structured_diagnostics() -> None:
    response = client.get("/ready")
    assert response.status_code in {200, 503}
    payload = response.json()
    assert payload["status"] in {"ok", "degraded", "error"}
    assert isinstance(payload["ready"], bool)
    assert isinstance(payload["checks"], list)
    assert any(item["id"] == "runtime_storage" for item in payload["checks"])


def test_diagnostics_endpoint_is_read_only_and_structured() -> None:
    response = client.get("/api/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert 0 <= payload["score"] <= 100
    assert isinstance(payload["warnings"], int)
    assert isinstance(payload["errors"], int)


def test_thunderbird_bridge_heartbeat_marks_connection_alive() -> None:
    response = client.post(
        "/api/thunderbird/bridge/heartbeat",
        json={"source": "test-native-host", "pid": 1234},
    )
    assert response.status_code == 200
    assert response.json()["connected"] is True

    status = client.get("/api/thunderbird/bridge/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["connected"] is True
    assert payload["source"] == "test-native-host"
