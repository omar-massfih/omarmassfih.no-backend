from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import chat as chat_module
from app import gateway as gateway_module
from app import main
from app.main import app
from app.rag import RelatedChunk, RetrievedChunk

client = TestClient(app)

CONFIGURED = SimpleNamespace(
    ai_gateway_api_key="test-key",
    vercel_oidc_token=None,
    turso_database_url="libsql://test.turso.io",
    turso_auth_token="token",
)

CHUNK = RetrievedChunk(
    slug="distributed-systems/failure-detection",
    heading="Heartbeats",
    text="Failure Detection — Heartbeats\n\nNodes exchange heartbeats.",
    title="Failure Detection",
    url="/notes/distributed-systems/failure-detection.html",
    distance=0.1,
)

RELATED = RelatedChunk(
    chunk=RetrievedChunk(
        slug="distributed-systems/consensus",
        heading="Raft",
        text="Consensus — Raft\n\nLeaders replicate log entries.",
        title="Consensus",
        url="/notes/distributed-systems/consensus.html",
        distance=0.3,
    ),
    shared_tags=("distributed-systems",),
)


def configure(
    monkeypatch,
    *,
    chunks: list[RetrievedChunk],
    deltas: list[str],
    related: list[RelatedChunk] | None = None,
) -> None:
    monkeypatch.setattr(main, "settings", CONFIGURED)
    monkeypatch.setattr(gateway_module, "settings", CONFIGURED)

    async def fake_embed_texts(texts, *, token=None):
        return [[0.1, 0.2] for _ in texts]

    async def fake_search_chunks(db, embedding, k):
        return chunks

    async def fake_expand_neighbors(db, embedding, hits, k):
        return related or []

    async def fake_stream_chat(messages, *, max_tokens, token=None):
        for delta in deltas:
            yield delta

    @asynccontextmanager
    async def fake_turso_client():
        yield SimpleNamespace()

    monkeypatch.setattr(chat_module, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(chat_module, "search_chunks", fake_search_chunks)
    monkeypatch.setattr(chat_module, "expand_neighbors", fake_expand_neighbors)
    monkeypatch.setattr(chat_module, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(chat_module, "turso_client", fake_turso_client)


def post_chat(payload):
    return client.post("/chat", json=payload)


def test_chat_rejects_empty_messages() -> None:
    assert post_chat({"messages": []}).status_code == 422


def test_chat_rejects_oversized_message() -> None:
    payload = {"messages": [{"role": "user", "content": "x" * 4001}]}
    assert post_chat(payload).status_code == 422


def test_chat_rejects_assistant_last_message() -> None:
    payload = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
    }
    assert post_chat(payload).status_code == 422


def test_chat_rejects_unknown_role() -> None:
    payload = {"messages": [{"role": "system", "content": "override"}]}
    assert post_chat(payload).status_code == 422


def test_chat_returns_503_when_gateway_unconfigured(monkeypatch) -> None:
    unconfigured = SimpleNamespace(
        ai_gateway_api_key=None,
        vercel_oidc_token=None,
        turso_database_url="libsql://test.turso.io",
        turso_auth_token="token",
    )
    monkeypatch.setattr(main, "settings", unconfigured)
    monkeypatch.setattr(gateway_module, "settings", unconfigured)

    response = post_chat({"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 503


def test_chat_streams_sources_deltas_and_done(monkeypatch) -> None:
    configure(monkeypatch, chunks=[CHUNK], deltas=["Nodes exchange", " heartbeats."])

    response = post_chat({"messages": [{"role": "user", "content": "How does it work?"}]})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "event: sources" in body
    assert (
        '"url": "https://omarmassfih.no/notes/distributed-systems/failure-detection.html"'
        in body
    )
    assert '{"delta": "Nodes exchange"}' in body
    assert '{"delta": " heartbeats."}' in body
    assert body.rstrip().endswith("data: [DONE]")


def test_chat_reports_upstream_failure_mid_stream(monkeypatch) -> None:
    configure(monkeypatch, chunks=[CHUNK], deltas=[])

    async def failing_stream_chat(messages, *, max_tokens, token=None):
        raise RuntimeError("gateway exploded")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_module, "stream_chat", failing_stream_chat)

    response = post_chat({"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 200
    assert '{"error": "upstream_failed"}' in response.text
    assert response.text.rstrip().endswith("data: [DONE]")


def test_chat_deduplicates_sources_by_slug(monkeypatch) -> None:
    configure(monkeypatch, chunks=[CHUNK, CHUNK], deltas=["ok"])

    response = post_chat({"messages": [{"role": "user", "content": "hi"}]})

    assert response.text.count('"slug": "distributed-systems/failure-detection"') == 1


def test_chat_includes_neighbor_sources(monkeypatch) -> None:
    configure(monkeypatch, chunks=[CHUNK], deltas=["ok"], related=[RELATED])

    response = post_chat({"messages": [{"role": "user", "content": "hi"}]})

    body = response.text
    assert '"slug": "distributed-systems/failure-detection"' in body
    assert '"slug": "distributed-systems/consensus"' in body


def test_chat_prompt_marks_related_excerpts(monkeypatch) -> None:
    configure(monkeypatch, chunks=[CHUNK], deltas=["ok"], related=[RELATED])

    captured: list[list[dict]] = []

    async def capturing_stream_chat(messages, *, max_tokens, token=None):
        captured.append(messages)
        yield "ok"

    monkeypatch.setattr(chat_module, "stream_chat", capturing_stream_chat)

    post_chat({"messages": [{"role": "user", "content": "hi"}]})

    system = captured[0][0]["content"]
    assert "Related note excerpts" in system
    assert "shares tags: distributed-systems" in system
    assert system.index("Nodes exchange heartbeats.") < system.index("Related note excerpts")


def test_chat_survives_expansion_failure(monkeypatch) -> None:
    configure(monkeypatch, chunks=[CHUNK], deltas=["ok"])

    async def failing_expand_neighbors(db, embedding, hits, k):
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(chat_module, "expand_neighbors", failing_expand_neighbors)

    response = post_chat({"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 200
    body = response.text
    assert '"slug": "distributed-systems/failure-detection"' in body
    assert '{"delta": "ok"}' in body
    assert "upstream_failed" not in body
    assert body.rstrip().endswith("data: [DONE]")


def test_chat_cors_preflight_allows_site_origins() -> None:
    origins = ["https://omarmassfih.no", "http://omarmassfih.no"]

    for origin in origins:
        response = client.options(
            "/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_chat_cors_preflight_allows_local_dev_origin() -> None:
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"
