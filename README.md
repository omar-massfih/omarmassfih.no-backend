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

## Postgres

Set a Postgres connection string locally, in Vercel, and as a GitHub Actions secret:

```sh
DATABASE_URL=postgresql://user:password@host-pooler.region.aws.neon.tech/database?sslmode=require
```

For Neon, use the pooled connection string for a serverless deployment. On the
self-hosted platform, the backend receives CloudNativePG's generated connection URI.
The seed scripts create the required tables and enable the `vector` extension.

Use `GET /db-health` to verify the database connection.

Seed notes from the backend repo:

```sh
uv run python scripts/seed_notes.py
```

## Endpoints

- `GET /` returns service metadata.
- `GET /health` returns service health.
- `GET /db-health` checks the Postgres connection.
- `GET /notes` returns published note metadata. Add `?include=content` to also get `heading` and `content_html` for every note.
- `GET /notes/{slug}` returns a published note.
- `GET /docs` opens the FastAPI docs.

Note endpoints send `ETag` and `Cache-Control` headers so the Vercel edge cache serves reads for up to five minutes (`s-maxage=300`) with stale-while-revalidate beyond that.

## Deployment

The container image is published to GHCR for `linux/arm64`. The platform repository
pins that image in k3s, runs note synchronization before the API starts, and connects
the backend to its cluster-internal CloudNativePG service. The database is never
exposed publicly; only the FastAPI service is routed through HTTPS.
