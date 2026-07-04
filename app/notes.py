from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class NoteSummary(BaseModel):
    slug: str
    url: str
    title: str
    list_title: str
    description: str | None = None
    lang: str
    category: str
    date: str
    date_text: str


class Note(NoteSummary):
    heading: str
    content_html: str


@dataclass(frozen=True)
class ParsedNote:
    slug: str
    url: str
    title: str
    heading: str
    list_title: str
    description: str | None
    lang: str
    category: str
    date: str
    date_text: str
    content_html: str
    published: bool = True


def row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)

    return {key: row[key] for key in row.keys()}


def parse_front_matter(raw: str, source: Path) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        raise ValueError(f"{source} is missing front matter")

    _, front_matter, body = raw.split("---", 2)
    data: dict[str, str] = {}

    for line in front_matter.strip().splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{source} has invalid front matter line: {line}")

        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()

    return data, body.strip()


def parse_note_file(path: Path, notes_root: Path) -> ParsedNote:
    front_matter, content_html = parse_front_matter(path.read_text(encoding="utf-8"), path)
    slug = path.relative_to(notes_root).with_suffix("").as_posix()
    title = front_matter["title"]

    return ParsedNote(
        slug=slug,
        url=f"/notes/{slug}.html",
        title=title,
        heading=front_matter.get("heading", title),
        list_title=front_matter.get("listTitle", title),
        description=front_matter.get("description"),
        lang=front_matter.get("lang", "en"),
        category=front_matter.get("category", "Notes"),
        date=front_matter.get("date", ""),
        date_text=front_matter.get("dateText", ""),
        content_html=content_html,
        published=front_matter.get("published", "true").lower() != "false",
    )


def parse_notes_tree(notes_root: Path) -> list[ParsedNote]:
    return [
        parse_note_file(path, notes_root)
        for path in sorted(notes_root.rglob("*.html"))
        if path.is_file()
    ]


async def init_notes_schema(client: Any) -> None:
    await client.execute(
        """
        create table if not exists notes (
          slug text primary key,
          url text not null unique,
          title text not null,
          heading text not null,
          list_title text not null,
          description text,
          lang text not null default 'en',
          category text not null,
          date text not null,
          date_text text not null,
          content_html text not null,
          published integer not null default 1,
          created_at text not null default current_timestamp,
          updated_at text not null default current_timestamp
        )
        """
    )
    await client.execute(
        "create index if not exists notes_published_category_date_idx on notes "
        "(published, category, date desc)"
    )


async def upsert_note(client: Any, note: ParsedNote) -> None:
    await client.execute(
        """
        insert into notes (
          slug, url, title, heading, list_title, description, lang, category,
          date, date_text, content_html, published
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(slug) do update set
          url = excluded.url,
          title = excluded.title,
          heading = excluded.heading,
          list_title = excluded.list_title,
          description = excluded.description,
          lang = excluded.lang,
          category = excluded.category,
          date = excluded.date,
          date_text = excluded.date_text,
          content_html = excluded.content_html,
          published = excluded.published,
          updated_at = current_timestamp
        """,
        [
            note.slug,
            note.url,
            note.title,
            note.heading,
            note.list_title,
            note.description,
            note.lang,
            note.category,
            note.date,
            note.date_text,
            note.content_html,
            1 if note.published else 0,
        ],
    )


async def list_published_notes(client: Any, include_content: bool = False) -> list[NoteSummary]:
    if include_content:
        result = await client.execute(
            """
            select slug, url, title, heading, list_title, description, lang, category,
                   date, date_text, content_html
            from notes
            where published = 1
            order by category asc, date desc, title asc
            """
        )

        return [Note.model_validate(row_to_dict(row)) for row in result.rows]

    result = await client.execute(
        """
        select slug, url, title, list_title, description, lang, category, date, date_text
        from notes
        where published = 1
        order by category asc, date desc, title asc
        """
    )

    return [NoteSummary.model_validate(row_to_dict(row)) for row in result.rows]


async def get_published_note(client: Any, slug: str) -> Note | None:
    result = await client.execute(
        """
        select slug, url, title, heading, list_title, description, lang, category,
               date, date_text, content_html
        from notes
        where published = 1 and slug = ?
        limit 1
        """,
        [slug],
    )

    if not result.rows:
        return None

    return Note.model_validate(row_to_dict(result.rows[0]))
