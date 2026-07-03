from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_service_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "omarmassfih.no-backend"
    assert "started_at" in body


def test_root_returns_service_links() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "omarmassfih.no-backend",
        "links": {
            "health": "/health",
            "docs": "/docs",
        },
    }
