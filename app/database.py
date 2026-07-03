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

        self.connection = libsql.connect(
            database=settings.turso_database_url,
            auth_token=settings.turso_auth_token,
        )

    async def execute(self, query: str, parameters: list[object] | None = None) -> SimpleNamespace:
        cursor = self.connection.execute(query, parameters or [])
        self.connection.commit()

        rows = cursor.fetchall()
        if cursor.description is None or rows is None:
            return SimpleNamespace(rows=[])

        columns = [column[0] for column in cursor.description]
        return SimpleNamespace(rows=[dict(zip(columns, row, strict=True)) for row in rows])

    def close(self) -> None:
        self.connection.close()


@asynccontextmanager
async def turso_client() -> AsyncIterator[DatabaseClient]:
    client = DatabaseClient()

    try:
        yield client
    finally:
        client.close()
