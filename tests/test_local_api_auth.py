from fastapi.testclient import TestClient
from jarvis_papa.app import app


client = TestClient(app)


def test_health_stays_available_when_local_auth_is_enabled(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_LOCAL_API_TOKEN", "local-test-secret")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_private_local_api_rejects_missing_and_wrong_tokens(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_LOCAL_API_TOKEN", "local-test-secret")

    missing = client.get("/api/actions")
    wrong = client.get(
        "/api/actions",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"


def test_private_local_api_accepts_authenticated_jarvis_client(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_LOCAL_API_TOKEN", "local-test-secret")

    response = client.get(
        "/api/actions",
        headers={"Authorization": "Bearer local-test-secret"},
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_confirmation_challenge_cannot_be_minted_by_unauthenticated_local_process(
    monkeypatch,
) -> None:
    monkeypatch.setenv("JARVIS_LOCAL_API_TOKEN", "local-test-secret")
    payload = {
        "action_key": "mail.send_reply",
        "description": "Envoyer un message de test.",
        "binding": {"card_id": "card-1"},
    }

    blocked = client.post("/api/confirmations/start", json=payload)
    allowed = client.post(
        "/api/confirmations/start",
        json=payload,
        headers={"Authorization": "Bearer local-test-secret"},
    )

    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["ok"] is True


def test_thunderbird_account_probe_route_is_mounted() -> None:
    paths = app.openapi()["paths"]

    assert "/api/advanced/thunderbird/account-probe" in paths
    assert "/api/advanced/thunderbird/account-probe/{command_id}" in paths
