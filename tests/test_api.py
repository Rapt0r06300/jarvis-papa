from fastapi.testclient import TestClient

from jarvis_papa.app import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_is_available() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Jarvis est prêt" in response.text
    assert "Bonjour Robert" in response.text


def test_write_permission_requires_confirmation() -> None:
    response = client.post(
        "/api/security/check",
        json={"risk": "write", "confirmed": False},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False


def test_write_permission_can_be_confirmed() -> None:
    response = client.post(
        "/api/security/check",
        json={"risk": "write", "confirmed": True},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_background_information_stays_silent() -> None:
    response = client.post(
        "/api/speech/event",
        json={
            "text": "La synchronisation est terminée.",
            "importance": "normal",
            "dedupe_key": "sync-finished",
        },
    )
    assert response.status_code == 200
    assert response.json()["should_speak"] is False


def test_direct_response_to_robert_should_be_spoken() -> None:
    response = client.post(
        "/api/speech/event",
        json={
            "text": "Robert, tu as deux messages importants.",
            "importance": "normal",
            "user_initiated": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["should_speak"] is True
    assert response.json()["reason"] == "direct_response_to_robert"


def test_action_required_should_be_spoken() -> None:
    response = client.post(
        "/api/speech/event",
        json={
            "text": "Robert, veux-tu envoyer cette réponse ?",
            "importance": "normal",
            "action_required": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["should_speak"] is True
