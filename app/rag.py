from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from app.config import settings
from app.notes import ParsedNote, today_iso

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
    await client.execute("create extension if not exists vector")
    result = await client.execute(
        """
        select format_type(attribute.atttypid, attribute.atttypmod) as data_type
        from pg_attribute attribute
        where attribute.attrelid = to_regclass('note_chunks')
          and attribute.attname = 'embedding'
          and not attribute.attisdropped
        """
    )
    if result.rows:
        declared = re.fullmatch(r"vector\((\d+)\)", result.rows[0]["data_type"] or "")
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
          embedding vector({settings.embedding_dim}) not null,
          updated_at timestamp with time zone not null default current_timestamp,
          primary key (slug, chunk_index)
        )
        """
    )
    await client.execute(
        "create index if not exists note_chunks_embedding_hnsw_idx "
        "on note_chunks using hnsw (embedding vector_cosine_ops)"
    )


async def get_existing_hashes(client: Any, slug: str) -> dict[int, str]:
    result = await client.execute(
        "select chunk_index, content_hash from note_chunks where slug = %s",
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
        values (%s, %s, %s, %s, %s, %s::vector)
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
        "delete from note_chunks where slug = %s and chunk_index >= %s",
        [slug, from_index],
    )


async def delete_stale_slugs(client: Any, keep_slugs: list[str]) -> None:
    if not keep_slugs:
        await client.execute("delete from note_chunks")
        return

    placeholders = ", ".join("%s" for _ in keep_slugs)
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
    chunk_index: int = 0


def _row_to_chunk(row: dict[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        slug=row["slug"],
        heading=row["heading"],
        text=row["text"],
        title=row["title"],
        url=row["url"],
        distance=row.get("distance", 0.0),
        chunk_index=row.get("chunk_index", 0),
    )


async def search_chunks(
    client: Any, query_embedding: list[float], k: int
) -> list[RetrievedChunk]:
    result = await client.execute(
        """
        select c.slug, c.chunk_index, c.heading, c.text, n.title, n.url,
               c.embedding <=> %s::vector as distance
        from note_chunks c
        join notes n on n.slug = c.slug and n.published = 1 and n.date <= %s
        order by distance
        limit %s
        """,
        [json.dumps(query_embedding), today_iso(), k],
    )

    return [_row_to_chunk(row) for row in result.rows]


TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[._:/-][a-z0-9]+)*")
BM25_K1 = 1.5
BM25_B = 0.75


def lexical_tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.casefold())


def rank_lexical(
    query: str, chunks: list[RetrievedChunk], k: int
) -> list[RetrievedChunk]:
    """Rank chunks with deterministic BM25, excluding documents with no lexical match."""
    query_terms = lexical_tokens(query)
    if not query_terms or not chunks or k <= 0:
        return []

    documents = [
        lexical_tokens(f"{chunk.title} {chunk.heading or ''} {chunk.text}")
        for chunk in chunks
    ]
    average_length = sum(map(len, documents)) / len(documents)
    document_frequency = Counter(
        term for document in documents for term in set(document)
    )
    scores: list[tuple[float, int, RetrievedChunk]] = []

    for source_order, (chunk, document) in enumerate(zip(chunks, documents, strict=True)):
        frequencies = Counter(document)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            inverse_frequency = math.log(
                1 + (len(documents) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            length_factor = 1 - BM25_B + BM25_B * len(document) / (average_length or 1)
            score += inverse_frequency * (
                frequency * (BM25_K1 + 1) / (frequency + BM25_K1 * length_factor)
            )
        if score > 0:
            scores.append((score, source_order, chunk))

    scores.sort(key=lambda item: (-item[0], item[2].slug, item[2].chunk_index, item[1]))
    return [item[2] for item in scores[:k]]


def reciprocal_rank_fusion(
    semantic: list[RetrievedChunk],
    lexical: list[RetrievedChunk],
    *,
    k: int,
    rrf_k: int,
    semantic_weight: float,
    lexical_weight: float,
) -> list[RetrievedChunk]:
    chunks: dict[tuple[str, int], RetrievedChunk] = {}
    scores: Counter[tuple[str, int]] = Counter()

    for weight, ranking in ((semantic_weight, semantic), (lexical_weight, lexical)):
        seen: set[tuple[str, int]] = set()
        for rank, chunk in enumerate(ranking, start=1):
            identity = (chunk.slug, chunk.chunk_index)
            if identity in seen:
                continue
            seen.add(identity)
            chunks.setdefault(identity, chunk)
            scores[identity] += weight / (rrf_k + rank)

    identities = sorted(scores, key=lambda identity: (-scores[identity], identity))
    return [chunks[identity] for identity in identities[:k]]


async def load_lexical_candidates(client: Any) -> list[RetrievedChunk]:
    result = await client.execute(
        """
        select c.slug, c.chunk_index, c.heading, c.text, n.title, n.url
        from note_chunks c
        join notes n on n.slug = c.slug and n.published = 1 and n.date <= %s
        order by c.slug, c.chunk_index
        """,
        [today_iso()],
    )
    return [_row_to_chunk(row) for row in result.rows]


async def hybrid_search_chunks(
    client: Any,
    query: str,
    query_embedding: list[float],
    k: int,
    *,
    candidate_k: int,
    semantic_weight: float,
    lexical_weight: float,
    rrf_k: int,
) -> list[RetrievedChunk]:
    if k <= 0:
        return []
    depth = max(k, candidate_k)
    semantic = await search_chunks(client, query_embedding, depth)
    candidates = await load_lexical_candidates(client)
    lexical = rank_lexical(query, candidates, depth)
    return reciprocal_rank_fusion(
        semantic,
        lexical,
        k=k,
        rrf_k=rrf_k,
        semantic_weight=semantic_weight,
        lexical_weight=lexical_weight,
    )


@dataclass(frozen=True)
class RelatedChunk:
    chunk: RetrievedChunk
    shared_tags: tuple[str, ...]


async def get_published_tags(client: Any) -> dict[str, tuple[str, ...]]:
    result = await client.execute(
        "select slug, tags from notes where published = 1 and date <= %s",
        [today_iso()],
    )
    return {row["slug"]: tuple(json.loads(row["tags"] or "[]")) for row in result.rows}


def tag_neighbors(
    hit_slugs: set[str], tags_by_slug: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    hit_tags = {tag for slug in hit_slugs for tag in tags_by_slug.get(slug, ())}

    neighbors: dict[str, tuple[str, ...]] = {}
    for slug, tags in tags_by_slug.items():
        if slug in hit_slugs:
            continue
        shared = tuple(tag for tag in tags if tag in hit_tags)
        if shared:
            neighbors[slug] = shared

    return neighbors


async def search_chunks_in_slugs(
    client: Any, query_embedding: list[float], slugs: list[str], k: int
) -> list[RetrievedChunk]:
    if not slugs or k <= 0:
        return []

    placeholders = ", ".join("%s" for _ in slugs)
    result = await client.execute(
        f"""
        select c.slug, c.chunk_index, c.heading, c.text, n.title, n.url,
               c.embedding <=> %s::vector as distance
        from note_chunks c
        join notes n on n.slug = c.slug and n.published = 1 and n.date <= %s
        where c.slug in ({placeholders})
        order by distance
        limit %s
        """,
        [json.dumps(query_embedding), today_iso(), *slugs, k],
    )

    return [_row_to_chunk(row) for row in result.rows]


async def expand_neighbors(
    client: Any, query_embedding: list[float], hits: list[RetrievedChunk], k: int
) -> list[RelatedChunk]:
    if k <= 0 or not hits:
        return []

    tags_by_slug = await get_published_tags(client)
    neighbors = tag_neighbors({hit.slug for hit in hits}, tags_by_slug)
    if not neighbors:
        return []

    chunks = await search_chunks_in_slugs(client, query_embedding, sorted(neighbors), k)
    return [RelatedChunk(chunk=chunk, shared_tags=neighbors[chunk.slug]) for chunk in chunks]
