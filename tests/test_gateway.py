import asyncio
from types import SimpleNamespace

import pytest

from app import gateway


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        payload: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def configure_gateway(monkeypatch, responses: list[FakeResponse]) -> list[dict]:
    requests: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == gateway.EMBED_TIMEOUT

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url: str, *, headers: dict, json: dict):
            requests.append({"url": url, "headers": headers, "json": json})
            return responses.pop(0)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        gateway,
        "settings",
        SimpleNamespace(
            ai_gateway_api_key="test-key",
            vercel_oidc_token=None,
            ai_gateway_base_url="https://gateway.test/v1",
            embedding_model="test-model",
        ),
    )
    return requests


def test_embed_texts_retries_rate_limit_and_honors_retry_after(monkeypatch) -> None:
    responses = [
        FakeResponse(429, headers={"Retry-After": "0.25"}),
        FakeResponse(
            200,
            payload={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        ),
    ]
    requests = configure_gateway(monkeypatch, responses)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(gateway.asyncio, "sleep", fake_sleep)

    embeddings = asyncio.run(gateway.embed_texts(["a", "b"], max_attempts=3))

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert len(requests) == 2
    assert delays == [0.25]


def test_embed_texts_does_not_retry_non_transient_failure(monkeypatch) -> None:
    requests = configure_gateway(monkeypatch, [FakeResponse(400)])

    with pytest.raises(gateway.GatewayError, match="status 400"):
        asyncio.run(gateway.embed_texts(["bad input"], max_attempts=5))

    assert len(requests) == 1


def test_embed_texts_rejects_invalid_attempt_count() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        asyncio.run(gateway.embed_texts(["text"], max_attempts=0))
