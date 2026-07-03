from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException

from app.database import DatabaseConfigError, turso_client

SERVICE_NAME = "omarmassfih.no-backend"
STARTED_AT = datetime.now(UTC)

app = FastAPI(title=SERVICE_NAME, version="0.1.0")


@app.get("/")
def read_root() -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "links": {
            "health": "/health",
            "database": "/db-health",
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


@app.get("/db-health")
async def read_db_health() -> dict[str, Any]:
    try:
        async with turso_client() as client:
            result = await client.execute("select 1 as ok")
    except DatabaseConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return {
        "ok": result.rows[0]["ok"] == 1,
        "database": "turso",
    }
