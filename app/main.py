from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException

from app.database import DatabaseConfigError, turso_client
from app.notes import get_published_note, list_published_notes

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
            "notes": "/notes",
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
    except Exception as error:
        raise HTTPException(status_code=503, detail="Turso health check failed") from error

    return {
        "ok": result.rows[0]["ok"] == 1,
        "database": "turso",
    }


@app.get("/notes")
async def read_notes() -> list[dict[str, Any]]:
    try:
        async with turso_client() as client:
            notes = await list_published_notes(client)
    except DatabaseConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Turso notes query failed") from error

    return [note.model_dump() for note in notes]


@app.get("/notes/{slug:path}")
async def read_note(slug: str) -> dict[str, Any]:
    slug = slug.removesuffix(".html")

    try:
        async with turso_client() as client:
            note = await get_published_note(client, slug)
    except DatabaseConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Turso note query failed") from error

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    return note.model_dump()
