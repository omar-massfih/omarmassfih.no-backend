# omarmassfih.no backend

FastAPI backend service for [omarmassfih.no](https://omarmassfih.no).

## Development

```sh
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

The service listens on `http://localhost:8000` by default.

## Scripts

```sh
uv run pytest
uv run ruff check .
```

## Turso

Set these environment variables locally and in Vercel:

```sh
TURSO_DATABASE_URL=libsql://your-database.turso.io
TURSO_AUTH_TOKEN=your-token
```

Use `GET /db-health` to verify the database connection.

Seed notes from the backend repo:

```sh
uv run python scripts/seed_notes.py
```

## Endpoints

- `GET /` returns service metadata.
- `GET /health` returns service health.
- `GET /db-health` checks the Turso connection.
- `GET /notes` returns published note metadata.
- `GET /notes/{slug}` returns a published note.
- `GET /docs` opens the FastAPI docs.
