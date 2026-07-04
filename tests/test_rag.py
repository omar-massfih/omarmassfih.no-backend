import asyncio
import json
from types import SimpleNamespace

from app.config import settings
from app.notes import ParsedNote
from app.rag import (
    MAX_CHUNK_CHARS,
    chunk_hash,
    chunk_note,
    delete_stale_slugs,
    init_chunks_schema,
    search_chunks,
    strip_html_sections,
    upsert_chunk,
)


def make_note(content_html: str, title: str = "Failure Detection") -> ParsedNote:
    return ParsedNote(
        slug="distributed-systems/failure-detection",
        url="/notes/distributed-systems/failure-detection.html",
        title=title,
        heading=title,
        list_title=title,
        description=None,
        lang="en",
        category="Distributed Systems",
        date="2026-07-01",
        date_text="Jul 1",
        content_html=content_html,
    )


class FakeChunksClient:
    def __init__(self, table_sql: str | None = None) -> None:
        self.executed: list[tuple[str, list[object] | None]] = []
        self.table_sql = table_sql
        self.search_rows: list[dict[str, object]] = []

    async def execute(self, query: str, args: list[object] | None = None):
        self.executed.append((query, args))
        normalized = " ".join(query.split()).lower()

        if "from sqlite_master" in normalized:
            rows = [{"sql": self.table_sql}] if self.table_sql else []
            return SimpleNamespace(rows=rows)

        if "vector_distance_cos" in normalized:
            return SimpleNamespace(rows=self.search_rows)

        return SimpleNamespace(rows=[])


def test_strip_html_sections_splits_on_headings() -> None:
    sections = strip_html_sections(
        "<p>Intro paragraph.</p>"
        "<h2>Heartbeats</h2><p>First point.</p><p>Second point.</p>"
        "<h3>Timeouts</h3><ul><li>One</li><li>Two</li></ul>"
    )

    assert [section.heading for section in sections] == [None, "Heartbeats", "Timeouts"]
    assert sections[0].text == "Intro paragraph."
    assert "First point." in sections[1].text
    assert "Second point." in sections[1].text
    assert "One" in sections[2].text


def test_strip_html_sections_ignores_script_and_style() -> None:
    sections = strip_html_sections("<p>Visible</p><script>alert('x')</script><style>p{}</style>")

    assert len(sections) == 1
    assert sections[0].text == "Visible"


def test_chunk_note_merges_small_sections_and_prefixes_title() -> None:
    long_text = "Sentence about failure detectors. " * 10
    note = make_note(
        f"<h2>Main</h2><p>{long_text}</p><h3>Tiny</h3><p>Short bit.</p>"
    )

    chunks = chunk_note(note)

    assert len(chunks) == 1
    assert chunks[0].text.startswith("Failure Detection — Main\n\n")
    assert "Short bit." in chunks[0].text


def test_chunk_note_splits_long_sections() -> None:
    paragraphs = "".join(f"<p>{'word ' * 120}end{i}.</p>" for i in range(8))
    note = make_note(f"<h2>Long</h2>{paragraphs}")

    chunks = chunk_note(note)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.heading == "Long"
        assert len(chunk.text) <= MAX_CHUNK_CHARS + len("Failure Detection — Long\n\n")


def test_chunk_hash_depends_on_model_and_text() -> None:
    assert chunk_hash("a") == chunk_hash("a")
    assert chunk_hash("a") != chunk_hash("b")


def test_init_chunks_schema_creates_table() -> None:
    fake_client = FakeChunksClient()

    asyncio.run(init_chunks_schema(fake_client))

    queries = [query for query, _ in fake_client.executed]
    assert not any(query.strip().lower().startswith("drop") for query in queries)
    assert any("create table if not exists note_chunks" in query for query in queries)
    assert any(f"F32_BLOB({settings.embedding_dim})" in query for query in queries)


def test_init_chunks_schema_recreates_on_dim_mismatch() -> None:
    fake_client = FakeChunksClient(
        table_sql="CREATE TABLE note_chunks (embedding F32_BLOB(42) not null)"
    )

    asyncio.run(init_chunks_schema(fake_client))

    queries = [query for query, _ in fake_client.executed]
    assert any(query.strip().lower().startswith("drop table") for query in queries)


def test_init_chunks_schema_keeps_matching_table() -> None:
    fake_client = FakeChunksClient(
        table_sql=f"CREATE TABLE note_chunks (embedding F32_BLOB({settings.embedding_dim}))"
    )

    asyncio.run(init_chunks_schema(fake_client))

    queries = [query for query, _ in fake_client.executed]
    assert not any(query.strip().lower().startswith("drop") for query in queries)


def test_upsert_chunk_binds_embedding_as_json() -> None:
    fake_client = FakeChunksClient()

    asyncio.run(upsert_chunk(fake_client, "slug", 0, "Heading", "text", "hash", [0.1, 0.2]))

    query, args = fake_client.executed[0]
    assert "vector32(?)" in query
    assert args is not None
    assert json.loads(str(args[-1])) == [0.1, 0.2]


def test_delete_stale_slugs_handles_empty_keep_list() -> None:
    fake_client = FakeChunksClient()

    asyncio.run(delete_stale_slugs(fake_client, []))

    assert fake_client.executed[0][0] == "delete from note_chunks"


def test_search_chunks_maps_rows() -> None:
    fake_client = FakeChunksClient()
    fake_client.search_rows = [
        {
            "slug": "distributed-systems/failure-detection",
            "heading": "Heartbeats",
            "text": "chunk text",
            "title": "Failure Detection",
            "url": "/notes/distributed-systems/failure-detection.html",
            "distance": 0.12,
        }
    ]

    results = asyncio.run(search_chunks(fake_client, [0.1, 0.2], k=3))

    assert len(results) == 1
    assert results[0].slug == "distributed-systems/failure-detection"
    assert results[0].distance == 0.12

    query, args = fake_client.executed[0]
    assert "join notes" in query
    assert args is not None and args[-1] == 3
