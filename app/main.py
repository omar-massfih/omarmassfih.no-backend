import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.chat import ChatRequest, stream_answer
from app.config import settings
from app.database import DatabaseConfigError, postgres_client
from app.gateway import GatewayConfigError, resolve_token
from app.notes import get_published_note, list_published_notes

SERVICE_NAME = "omarmassfih.no-backend"
STARTED_AT = datetime.now(UTC)
CACHE_CONTROL = "public, max-age=0, s-maxage=300, stale-while-revalidate=86400"

app = FastAPI(title=SERVICE_NAME, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://omarmassfih.no",
        "http://omarmassfih.no",
        "http://localhost:8080",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def cached_json(payload: Any, request: Request) -> Response:
    body = json.dumps(payload).encode()
    etag = f'"{hashlib.md5(body).hexdigest()}"'
    headers = {"Cache-Control": CACHE_CONTROL, "ETag": etag}

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    return Response(body, media_type="application/json", headers=headers)


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
        async with postgres_client() as client:
            result = await client.execute("select 1 as ok")
    except DatabaseConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Postgres health check failed") from error

    return {
        "ok": result.rows[0]["ok"] == 1,
        "database": "postgres",
    }


@app.post("/chat")
async def post_chat(chat_request: ChatRequest, request: Request) -> StreamingResponse:
    oidc_token = request.headers.get("x-vercel-oidc-token")

    try:
        token = resolve_token(oidc_token)
    except GatewayConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Postgres is not configured")

    return StreamingResponse(
        stream_answer(chat_request, token=token),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/notes")
async def read_notes(request: Request, include: str | None = None) -> Response:
    try:
        async with postgres_client() as client:
            notes = await list_published_notes(client, include_content=include == "content")
    except DatabaseConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Postgres notes query failed") from error

    return cached_json([note.model_dump() for note in notes], request)


@app.get("/notes/{slug:path}")
async def read_note(slug: str, request: Request) -> Response:
    slug = slug.removesuffix(".html")

    try:
        async with postgres_client() as client:
            note = await get_published_note(client, slug)
    except DatabaseConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Postgres note query failed") from error

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    return cached_json(note.model_dump(), request)
