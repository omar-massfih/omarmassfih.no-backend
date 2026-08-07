from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import postgres_client
from app.notes import (
    delete_stale_notes,
    init_notes_schema,
    parse_notes_tree,
    upsert_note,
)


async def seed_notes(notes_root: Path) -> int:
    notes = parse_notes_tree(notes_root)

    async with postgres_client() as client:
        await init_notes_schema(client)
        for note in notes:
            await upsert_note(client, note)

        await delete_stale_notes(client, [note.slug for note in notes])

    return len(notes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed notes into Postgres.")
    parser.add_argument(
        "--notes-root",
        default="notes",
        help="Path to the backend notes directory.",
    )
    args = parser.parse_args()

    count = asyncio.run(seed_notes(Path(args.notes_root).resolve()))
    print(f"Seeded {count} notes.")


if __name__ == "__main__":
    main()
