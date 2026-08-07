from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import settings


class DatabaseConfigError(RuntimeError):
    pass


class DatabaseClient:
    def __init__(self) -> None:
        if not settings.database_url:
            raise DatabaseConfigError("Postgres is not configured")

        self.connection: psycopg.AsyncConnection | None = None

    async def _connect(self) -> psycopg.AsyncConnection:
        if self.connection is None:
            self.connection = await psycopg.AsyncConnection.connect(
                settings.database_url,
                autocommit=True,
                row_factory=dict_row,
            )

        return self.connection

    async def execute(self, query: str, parameters: list[object] | None = None) -> SimpleNamespace:
        connection = await self._connect()
        async with connection.cursor() as cursor:
            await cursor.execute(query, parameters or [])
            rows: list[dict[str, Any]] = (
                await cursor.fetchall() if cursor.description is not None else []
            )
        return SimpleNamespace(rows=rows)

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()


@asynccontextmanager
async def postgres_client() -> AsyncIterator[DatabaseClient]:
    client = DatabaseClient()

    try:
        yield client
    finally:
        await client.close()
