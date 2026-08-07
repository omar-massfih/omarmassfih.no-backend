import asyncio
from types import SimpleNamespace

import pytest

from app import database


class FakeCursor:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.description = [object()] if rows is not None else None
        self.executed: list[tuple[str, list[object]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def execute(self, query: str, parameters: list[object]) -> None:
        self.executed.append((query, parameters))

    async def fetchall(self) -> list[dict]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    async def close(self) -> None:
        self.closed = True


def test_database_client_requires_postgres_configuration(monkeypatch) -> None:
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_url=None))

    with pytest.raises(database.DatabaseConfigError, match="Postgres is not configured"):
        database.DatabaseClient()


def test_database_client_executes_with_dict_rows_and_closes(monkeypatch) -> None:
    cursor = FakeCursor([{"ok": 1}])
    connection = FakeConnection(cursor)
    connect_calls: list[tuple[str, bool, object]] = []

    async def fake_connect(url: str, *, autocommit: bool, row_factory: object):
        connect_calls.append((url, autocommit, row_factory))
        return connection

    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(database_url="postgresql://user:secret@postgres.test/database"),
    )
    monkeypatch.setattr(
        database.psycopg,
        "AsyncConnection",
        SimpleNamespace(connect=fake_connect),
    )

    async def exercise_client():
        async with database.postgres_client() as client:
            return await client.execute("select %s as ok", [1])

    result = asyncio.run(exercise_client())

    assert result.rows == [{"ok": 1}]
    assert cursor.executed == [("select %s as ok", [1])]
    assert connect_calls == [
        (
            "postgresql://user:secret@postgres.test/database",
            True,
            database.dict_row,
        )
    ]
    assert connection.closed is True


def test_database_client_returns_no_rows_for_write(monkeypatch) -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    async def fake_connect(url: str, *, autocommit: bool, row_factory: object):
        return connection

    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(database_url="postgresql://user:secret@postgres.test/database"),
    )
    monkeypatch.setattr(
        database.psycopg,
        "AsyncConnection",
        SimpleNamespace(connect=fake_connect),
    )

    client = database.DatabaseClient()
    result = asyncio.run(client.execute("delete from notes"))

    assert result.rows == []
