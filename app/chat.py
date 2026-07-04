from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.database import turso_client
from app.gateway import embed_texts, stream_chat
from app.rag import RetrievedChunk, search_chunks

SITE_URL = "https://omarmassfih.no"
HISTORY_LIMIT = 8

SYSTEM_PROMPT = """\
You are the notes assistant on omarmassfih.no, answering questions about Omar Massfih's \
technical notes. You are given excerpts from the notes below. Answer using only those \
excerpts. If the answer is not in the excerpts, say you don't know and suggest browsing \
the notes instead. Answer in plain text without markdown formatting. Keep answers short \
and to the point.\
"""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _last_message_is_user(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("last message must be from the user")
        return self


def _sse(data: str, event: str | None = None) -> str:
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {data}\n\n"


def _sources_payload(chunks: list[RetrievedChunk]) -> str:
    sources = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.slug in seen:
            continue
        seen.add(chunk.slug)
        sources.append(
            {"slug": chunk.slug, "title": chunk.title, "url": f"{SITE_URL}{chunk.url}"}
        )

    return json.dumps({"sources": sources})


def _gateway_messages(request: ChatRequest, chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    excerpts = "\n\n".join(
        f"{chunk.title} ({SITE_URL}{chunk.url}) — {chunk.heading}:\n{chunk.text}"
        for chunk in chunks
    )
    system = f"{SYSTEM_PROMPT}\n\nNote excerpts:\n\n{excerpts}" if chunks else SYSTEM_PROMPT

    history = [
        {"role": message.role, "content": message.content}
        for message in request.messages[-HISTORY_LIMIT:]
    ]

    return [{"role": "system", "content": system}, *history]


async def stream_answer(request: ChatRequest, token: str | None = None) -> AsyncIterator[str]:
    try:
        query = request.messages[-1].content
        query_embedding = (await embed_texts([query], token=token))[0]
        async with turso_client() as client:
            chunks = await search_chunks(client, query_embedding, settings.chat_top_k)

        yield _sse(_sources_payload(chunks), event="sources")

        async for delta in stream_chat(
            _gateway_messages(request, chunks),
            max_tokens=settings.chat_max_tokens,
            token=token,
        ):
            yield _sse(json.dumps({"delta": delta}))
    except Exception:
        yield _sse(json.dumps({"error": "upstream_failed"}))

    yield _sse("[DONE]")
