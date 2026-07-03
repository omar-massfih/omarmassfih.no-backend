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

## Endpoints

- `GET /` returns service metadata.
- `GET /health` returns service health.
- `GET /docs` opens the FastAPI docs.
