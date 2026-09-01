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
