import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import libsql

from app.config import settings


class DatabaseConfigError(RuntimeError):
    pass


class DatabaseClient:
    def __init__(self) -> None:
        if not settings.turso_database_url or not settings.turso_auth_token:
            raise DatabaseConfigError("Turso is not configured")

        self.connection: libsql.Connection | None = None

    def _connect(self) -> libsql.Connection:
        if self.connection is None:
            self.connection = libsql.connect(
                database=settings.turso_database_url,
                auth_token=settings.turso_auth_token,
            )

        return self.connection

    def _execute_sync(self, query: str, parameters: list[object] | None) -> SimpleNamespace:
        connection = self._connect()
        cursor = connection.execute(query, parameters or [])
        connection.commit()

        rows = cursor.fetchall()
        if cursor.description is None or rows is None:
            return SimpleNamespace(rows=[])

        columns = [column[0] for column in cursor.description]
        return SimpleNamespace(rows=[dict(zip(columns, row, strict=True)) for row in rows])

    async def execute(self, query: str, parameters: list[object] | None = None) -> SimpleNamespace:
        return await asyncio.to_thread(self._execute_sync, query, parameters)

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()


@asynccontextmanager
async def turso_client() -> AsyncIterator[DatabaseClient]:
    client = DatabaseClient()

    try:
        yield client
    finally:
        client.close()
