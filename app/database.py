from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import libsql_client

from app.config import settings


class DatabaseConfigError(RuntimeError):
    pass


@asynccontextmanager
async def turso_client() -> AsyncIterator[libsql_client.Client]:
    if not settings.turso_database_url or not settings.turso_auth_token:
        raise DatabaseConfigError("Turso is not configured")

    async with libsql_client.create_client(
        url=settings.turso_database_url,
        auth_token=settings.turso_auth_token,
    ) as client:
        yield client
