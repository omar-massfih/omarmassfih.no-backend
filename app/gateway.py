from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings

EMBED_TIMEOUT = 30.0
CHAT_TIMEOUT = 120.0
EMBED_RETRY_BASE_DELAY = 5.0
EMBED_RETRY_MAX_DELAY = 60.0
RETRYABLE_GATEWAY_STATUSES = frozenset({429, 500, 502, 503, 504})


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


def _embedding_retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), EMBED_RETRY_MAX_DELAY)
        except ValueError:
            pass

    return min(EMBED_RETRY_BASE_DELAY * (2**attempt), EMBED_RETRY_MAX_DELAY)


async def embed_texts(
    texts: list[str], *, token: str | None = None, max_attempts: int = 1
) -> list[list[float]]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
        for attempt in range(max_attempts):
            response = await client.post(
                f"{settings.ai_gateway_base_url}/embeddings",
                headers=_headers(token),
                json={"model": settings.embedding_model, "input": texts},
            )

            if response.status_code == 200:
                break

            is_retryable = response.status_code in RETRYABLE_GATEWAY_STATUSES
            if not is_retryable or attempt == max_attempts - 1:
                raise GatewayError(f"Embedding request failed with status {response.status_code}")

            await asyncio.sleep(_embedding_retry_delay(response, attempt))

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
