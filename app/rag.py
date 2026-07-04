from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from app.config import settings
from app.notes import ParsedNote

SECTION_TAGS = {"h2", "h3"}
BLOCK_TAGS = {"p", "li", "ul", "ol", "pre", "blockquote", "figure", "figcaption", "table", "tr"}
SKIP_TAGS = {"script", "style"}
MIN_SECTION_CHARS = 200
MAX_CHUNK_CHARS = 2500


@dataclass(frozen=True)
class Section:
    heading: str | None
    text: str


@dataclass(frozen=True)
class Chunk:
    heading: str | None
    text: str


class _SectionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sections: list[tuple[str | None, list[str]]] = [(None, [])]
        self._in_section_tag = False
        self._skip_depth = 0
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in SECTION_TAGS:
            self._in_section_tag = True
            self._heading_parts = []
        elif tag in BLOCK_TAGS:
            self.sections[-1][1].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in SECTION_TAGS:
            self._in_section_tag = False
            heading = "".join(self._heading_parts).strip() or None
            self.sections.append((heading, []))
        elif tag in BLOCK_TAGS:
            self.sections[-1][1].append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_section_tag:
            self._heading_parts.append(data)
        else:
            self.sections[-1][1].append(data)


def _normalize_text(raw: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
    collapsed = "\n".join(line for line in lines if line)
    return collapsed.strip()


def strip_html_sections(content_html: str) -> list[Section]:
    parser = _SectionParser()
    parser.feed(content_html)
    parser.close()

    sections = []
    for heading, parts in parser.sections:
        text = _normalize_text("".join(parts))
        if text or heading:
            sections.append(Section(heading=heading, text=text))

    return sections


def _split_long_text(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    pieces: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        candidate = f"{current}\n{paragraph}" if current else paragraph
        if len(candidate) > MAX_CHUNK_CHARS and current:
            pieces.append(current)
            current = paragraph
        else:
            current = candidate

    if current:
        pieces.append(current)

    return pieces


def chunk_note(note: ParsedNote) -> list[Chunk]:
    merged: list[Section] = []
    for section in strip_html_sections(note.content_html):
        if merged and len(section.text) < MIN_SECTION_CHARS:
            previous = merged[-1]
            joined = f"{previous.text}\n{section.heading or ''}\n{section.text}".strip()
            merged[-1] = Section(heading=previous.heading, text=_normalize_text(joined))
        else:
            merged.append(section)

    chunks: list[Chunk] = []
    for section in merged:
        for piece in _split_long_text(section.text):
            heading = section.heading or note.heading
            chunks.append(Chunk(heading=heading, text=f"{note.title} — {heading}\n\n{piece}"))

    return chunks


def chunk_hash(text: str) -> str:
    payload = f"{settings.embedding_model}\x00{text}".encode()
    return hashlib.sha256(payload).hexdigest()


async def init_chunks_schema(client: Any) -> None:
    result = await client.execute(
        "select sql from sqlite_master where type = 'table' and name = 'note_chunks'"
    )
    if result.rows:
        declared = re.search(r"F32_BLOB\((\d+)\)", result.rows[0]["sql"] or "", re.IGNORECASE)
        if declared is None or int(declared.group(1)) != settings.embedding_dim:
            await client.execute("drop table note_chunks")

    await client.execute(
        f"""
        create table if not exists note_chunks (
          slug text not null,
          chunk_index integer not null,
          heading text,
          text text not null,
          content_hash text not null,
          embedding F32_BLOB({settings.embedding_dim}) not null,
          updated_at text not null default current_timestamp,
          primary key (slug, chunk_index)
        )
        """
    )


async def get_existing_hashes(client: Any, slug: str) -> dict[int, str]:
    result = await client.execute(
        "select chunk_index, content_hash from note_chunks where slug = ?",
        [slug],
    )
    return {row["chunk_index"]: row["content_hash"] for row in result.rows}


async def upsert_chunk(
    client: Any,
    slug: str,
    chunk_index: int,
    heading: str | None,
    text: str,
    content_hash: str,
    embedding: list[float],
) -> None:
    await client.execute(
        """
        insert into note_chunks (slug, chunk_index, heading, text, content_hash, embedding)
        values (?, ?, ?, ?, ?, vector32(?))
        on conflict(slug, chunk_index) do update set
          heading = excluded.heading,
          text = excluded.text,
          content_hash = excluded.content_hash,
          embedding = excluded.embedding,
          updated_at = current_timestamp
        """,
        [slug, chunk_index, heading, text, content_hash, json.dumps(embedding)],
    )


async def delete_chunks(client: Any, slug: str, from_index: int) -> None:
    await client.execute(
        "delete from note_chunks where slug = ? and chunk_index >= ?",
        [slug, from_index],
    )


async def delete_stale_slugs(client: Any, keep_slugs: list[str]) -> None:
    if not keep_slugs:
        await client.execute("delete from note_chunks")
        return

    placeholders = ", ".join("?" for _ in keep_slugs)
    await client.execute(
        f"delete from note_chunks where slug not in ({placeholders})",
        keep_slugs,
    )


@dataclass(frozen=True)
class RetrievedChunk:
    slug: str
    heading: str | None
    text: str
    title: str
    url: str
    distance: float


async def search_chunks(
    client: Any, query_embedding: list[float], k: int
) -> list[RetrievedChunk]:
    result = await client.execute(
        """
        select c.slug, c.heading, c.text, n.title, n.url,
               vector_distance_cos(c.embedding, vector32(?)) as distance
        from note_chunks c
        join notes n on n.slug = c.slug and n.published = 1
        order by distance
        limit ?
        """,
        [json.dumps(query_embedding), k],
    )

    return [
        RetrievedChunk(
            slug=row["slug"],
            heading=row["heading"],
            text=row["text"],
            title=row["title"],
            url=row["url"],
            distance=row["distance"],
        )
        for row in result.rows
    ]
