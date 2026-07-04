import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.notes import get_published_note, init_notes_schema, list_published_notes, parse_note_file

client = TestClient(app)


class FakeNotesClient:
    def __init__(self) -> None:
        self.executed: list[tuple[str, list[str] | None]] = []
        self.notes = [
            {
                "slug": "software-architecture/three-laws",
                "url": "/notes/software-architecture/three-laws.html",
                "title": "Three Laws",
                "heading": "Three Laws",
                "list_title": "Three Laws",
                "description": "A note.",
                "lang": "en",
                "category": "Software Architecture",
                "date": "2026-07-03",
                "date_text": "Jul 3",
                "content_html": "<p>Hello</p>",
                "published": 1,
            },
            {
                "slug": "drafts/private",
                "url": "/notes/drafts/private.html",
                "title": "Private",
                "heading": "Private",
                "list_title": "Private",
                "description": None,
                "lang": "en",
                "category": "Drafts",
                "date": "2026-07-04",
                "date_text": "Jul 4",
                "content_html": "<p>Draft</p>",
                "published": 0,
            },
        ]

    async def execute(self, query: str, args: list[str] | None = None):
        self.executed.append((query, args))
        normalized = " ".join(query.split()).lower()

        if normalized.startswith("create table") or normalized.startswith("create index"):
            return SimpleNamespace(rows=[])

        if "where published = 1 and slug = ?" in normalized:
            rows = [
                note
                for note in self.notes
                if note["published"] == 1 and args and note["slug"] == args[0]
            ]
            return SimpleNamespace(rows=rows[:1])

        if "from notes where published = 1" in normalized:
            if "content_html" in normalized:
                columns = [
                    "slug",
                    "url",
                    "title",
                    "heading",
                    "list_title",
                    "description",
                    "lang",
                    "category",
                    "date",
                    "date_text",
                    "content_html",
                ]
            else:
                columns = [
                    "slug",
                    "url",
                    "title",
                    "list_title",
                    "description",
                    "lang",
                    "category",
                    "date",
                    "date_text",
                ]

            rows = [
                {key: note[key] for key in columns}
                for note in self.notes
                if note["published"] == 1
            ]
            return SimpleNamespace(rows=rows)

        raise AssertionError(f"Unexpected query: {query}")


def test_parse_note_file_preserves_slug_and_metadata(tmp_path: Path) -> None:
    notes_root = tmp_path / "notes"
    note_path = notes_root / "software-architecture" / "three-laws.html"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        """---
title: Three Laws
heading: The Three Laws
listTitle: The Three Laws of Software Architecture
description: A note.
lang: en
category: Software Architecture
date: 2026-07-03
dateText: Jul 3
---
<p>Hello</p>
""",
        encoding="utf-8",
    )

    note = parse_note_file(note_path, notes_root)

    assert note.slug == "software-architecture/three-laws"
    assert note.url == "/notes/software-architecture/three-laws.html"
    assert note.title == "Three Laws"
    assert note.heading == "The Three Laws"
    assert note.list_title == "The Three Laws of Software Architecture"
    assert note.content_html == "<p>Hello</p>"


def test_init_notes_schema_creates_table_and_index() -> None:
    fake_client = FakeNotesClient()

    asyncio.run(init_notes_schema(fake_client))

    assert len(fake_client.executed) == 2
    assert "create table if not exists notes" in fake_client.executed[0][0]
    assert "create index if not exists" in fake_client.executed[1][0]


def test_list_published_notes_filters_drafts() -> None:
    notes = asyncio.run(list_published_notes(FakeNotesClient()))

    assert len(notes) == 1
    assert notes[0].slug == "software-architecture/three-laws"
    assert not hasattr(notes[0], "content_html")


def test_list_published_notes_includes_content_when_requested() -> None:
    notes = asyncio.run(list_published_notes(FakeNotesClient(), include_content=True))

    assert len(notes) == 1
    assert notes[0].content_html == "<p>Hello</p>"
    assert notes[0].heading == "Three Laws"


def test_list_published_notes_does_not_run_schema_ddl() -> None:
    fake_client = FakeNotesClient()

    asyncio.run(list_published_notes(fake_client))

    assert all(
        not query.strip().lower().startswith("create") for query, _ in fake_client.executed
    )


def test_get_published_note_returns_note_or_none() -> None:
    found = asyncio.run(get_published_note(FakeNotesClient(), "software-architecture/three-laws"))
    missing = asyncio.run(get_published_note(FakeNotesClient(), "missing"))

    assert found is not None
    assert found.content_html == "<p>Hello</p>"
    assert missing is None


def test_notes_endpoint_returns_published_notes(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_turso_client():
        yield FakeNotesClient()

    monkeypatch.setattr(main, "turso_client", fake_turso_client)

    response = client.get("/notes")

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "software-architecture/three-laws"


def test_notes_endpoint_includes_content_when_requested(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_turso_client():
        yield FakeNotesClient()

    monkeypatch.setattr(main, "turso_client", fake_turso_client)

    response = client.get("/notes?include=content")

    assert response.status_code == 200
    assert response.json()[0]["content_html"] == "<p>Hello</p>"


def test_notes_endpoint_sends_cache_headers_and_304(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_turso_client():
        yield FakeNotesClient()

    monkeypatch.setattr(main, "turso_client", fake_turso_client)

    response = client.get("/notes")

    assert response.headers["cache-control"] == main.CACHE_CONTROL
    etag = response.headers["etag"]

    revalidated = client.get("/notes", headers={"If-None-Match": etag})

    assert revalidated.status_code == 304
    assert revalidated.content == b""


def test_note_endpoint_returns_detail_or_404(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_turso_client():
        yield FakeNotesClient()

    monkeypatch.setattr(main, "turso_client", fake_turso_client)

    response = client.get("/notes/software-architecture/three-laws.html")
    missing = client.get("/notes/missing.html")

    assert response.status_code == 200
    assert response.json()["content_html"] == "<p>Hello</p>"
    assert missing.status_code == 404
