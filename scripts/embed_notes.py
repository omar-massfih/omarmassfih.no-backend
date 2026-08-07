from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import postgres_client
from app.gateway import embed_texts
from app.notes import parse_notes_tree
from app.rag import (
    chunk_hash,
    chunk_note,
    delete_chunks,
    delete_stale_slugs,
    get_existing_hashes,
    init_chunks_schema,
    upsert_chunk,
)


async def embed_notes(notes_root: Path) -> tuple[int, int]:
    notes = [note for note in parse_notes_tree(notes_root) if note.published]

    embedded = 0
    unchanged = 0

    async with postgres_client() as client:
        await init_chunks_schema(client)

        for note in notes:
            chunks = chunk_note(note)
            existing = await get_existing_hashes(client, note.slug)

            pending = [(index, chunk, chunk_hash(chunk.text)) for index, chunk in enumerate(chunks)]
            changed = [item for item in pending if existing.get(item[0]) != item[2]]
            unchanged += len(pending) - len(changed)

            if changed:
                embeddings = await embed_texts(
                    [chunk.text for _, chunk, _ in changed], max_attempts=5
                )
                for (index, chunk, content_hash), embedding in zip(
                    changed, embeddings, strict=True
                ):
                    await upsert_chunk(
                        client,
                        note.slug,
                        index,
                        chunk.heading,
                        chunk.text,
                        content_hash,
                        embedding,
                    )
                embedded += len(changed)

            await delete_chunks(client, note.slug, from_index=len(chunks))

        await delete_stale_slugs(client, [note.slug for note in notes])

    return embedded, unchanged


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed note chunks into Postgres.")
    parser.add_argument(
        "--notes-root",
        default="notes",
        help="Path to the backend notes directory.",
    )
    args = parser.parse_args()

    embedded, unchanged = asyncio.run(embed_notes(Path(args.notes_root).resolve()))
    print(f"Embedded {embedded} chunks ({unchanged} unchanged).")


if __name__ == "__main__":
    main()
