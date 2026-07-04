from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings

EMBED_TIMEOUT = 30.0
CHAT_TIMEOUT = 120.0


class GatewayConfigError(RuntimeError):
    pass


class GatewayError(RuntimeError):
    pass


def resolve_token(request_oidc_token: str | None = None) -> str:
    token = settings.ai_gateway_api_key or request_oidc_token or settings.vercel_oidc_token
    if not token:
        raise GatewayConfigError("AI gateway is not configured")
    return token


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {resolve_token(token)}"}


async def embed_texts(texts: list[str], *, token: str | None = None) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
        response = await client.post(
            f"{settings.ai_gateway_base_url}/embeddings",
            headers=_headers(token),
            json={"model": settings.embedding_model, "input": texts},
        )

    if response.status_code != 200:
        raise GatewayError(f"Embedding request failed with status {response.status_code}")

    data = sorted(response.json()["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in data]


async def stream_chat(
    messages: list[dict[str, Any]], *, max_tokens: int, token: str | None = None
) -> AsyncIterator[str]:
    async with (
        httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client,
        client.stream(
            "POST",
            f"{settings.ai_gateway_base_url}/chat/completions",
            headers=_headers(token),
            json={
                "model": settings.chat_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as response,
    ):
        if response.status_code != 200:
            raise GatewayError(f"Chat request failed with status {response.status_code}")

        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue

            payload = line.removeprefix("data:").strip()
            if payload == "[DONE]":
                return

            choices = json.loads(payload).get("choices")
            if not choices:
                continue

            delta = choices[0].get("delta", {}).get("content")
            if delta:
                yield delta
