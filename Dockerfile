FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 \
    EMBEDDING_DIM=384 \
    EMBEDDING_CACHE_DIR=/app/.cache/fastembed \
    EMBEDDING_THREADS=2

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Download the compact ONNX embedding model during the build. Runtime pods do
# not need Hugging Face or Vercel network access to create embeddings.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/.cache/fastembed', threads=2)"

COPY app ./app
COPY notes ./notes
COPY scripts ./scripts

RUN useradd --uid 1000 --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
