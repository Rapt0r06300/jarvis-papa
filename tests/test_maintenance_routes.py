from fastapi.testclient import TestClient

from jarvis_papa.app import app

client = TestClient(app)


def _authorization_token(action_key: str, binding: dict[str, object]) -> str:
    started = client.post(
        "/api/confirmations/start",
        json={
            "action_key": action_key,
            "description": "Action de maintenance de test",
            "binding": binding,
        },
    )
    challenge_id = started.json()["challenge_id"]
    client.post(f"/api/confirmations/{challenge_id}/confirm", json={})
    finished = client.post(f"/api/confirmations/{challenge_id}/confirm", json={})
    token = finished.json()["authorization_token"]
    assert isinstance(token, str) and token
    return token


def test_maintenance_status_is_registered() -> None:
    response = client.get("/api/maintenance/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "startup" in payload
    assert "updates" in payload
    assert "recovery" in payload


def test_startup_binding_mismatch_is_rejected_before_mutation() -> None:
    token = _authorization_token("system.startup.configure", {"enabled": True})

    response = client.post(
        "/api/maintenance/startup",
        json={"enabled": False, "authorization_token": token},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "autorisations exactes" in response.json()["detail"]


def test_restore_plan_rejects_unmanaged_archive() -> None:
    response = client.post(
        "/api/maintenance/restore/plan",
        json={"backup_path": "not-a-managed-backup.zip"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_update_check_rejects_plain_http_without_network_call() -> None:
    response = client.post(
        "/api/maintenance/updates/check",
        json={"manifest_url": "http://updates.example.test/manifest.json"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "HTTPS" in response.json()["detail"]


def test_update_install_requires_a_staged_update() -> None:
    response = client.get("/api/maintenance/updates/install-plan")

    assert response.status_code == 200
    assert response.json()["ok"] is False
