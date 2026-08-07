from __future__ import annotations

import asyncio
from functools import lru_cache
from threading import Lock
from typing import Literal

from fastembed import TextEmbedding

from app.config import settings

EmbeddingKind = Literal["passage", "query"]

_model_lock = Lock()


@lru_cache(maxsize=1)
def _embedding_model() -> TextEmbedding:
    return TextEmbedding(
        model_name=settings.embedding_model,
        cache_dir=settings.embedding_cache_dir,
        threads=settings.embedding_threads,
    )


def _embed_sync(texts: list[str], kind: EmbeddingKind) -> list[list[float]]:
    with _model_lock:
        model = _embedding_model()
        vectors = (
            model.query_embed(texts, batch_size=32)
            if kind == "query"
            else model.passage_embed(texts, batch_size=32)
        )
        embeddings = [vector.tolist() for vector in vectors]

    if any(len(embedding) != settings.embedding_dim for embedding in embeddings):
        raise RuntimeError(
            f"Local embedding model did not return {settings.embedding_dim} dimensions"
        )

    return embeddings


async def embed_texts(
    texts: list[str], *, kind: EmbeddingKind = "passage"
) -> list[list[float]]:
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts, kind)
