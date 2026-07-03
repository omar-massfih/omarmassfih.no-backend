from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
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
            "database": "/db-health",
            "docs": "/docs",
        },
    }


def test_db_health_returns_503_without_turso_config() -> None:
    response = client.get("/db-health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Turso is not configured"}


def test_db_health_returns_turso_status(monkeypatch) -> None:
    class FakeClient:
        async def execute(self, query: str):
            assert query == "select 1 as ok"
            return SimpleNamespace(rows=[{"ok": 1}])

    @asynccontextmanager
    async def fake_turso_client():
        yield FakeClient()

    monkeypatch.setattr(main, "turso_client", fake_turso_client)

    response = client.get("/db-health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "database": "turso",
    }
