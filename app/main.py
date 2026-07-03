from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

SERVICE_NAME = "omarmassfih.no-backend"
STARTED_AT = datetime.now(UTC)

app = FastAPI(title=SERVICE_NAME, version="0.1.0")


@app.get("/")
def read_root() -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "links": {
            "health": "/health",
            "docs": "/docs",
        },
    }


@app.get("/health")
def read_health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "started_at": STARTED_AT.isoformat(),
    }
