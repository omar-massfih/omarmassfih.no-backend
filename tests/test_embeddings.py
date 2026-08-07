import asyncio
from types import SimpleNamespace

import pytest

from app import embeddings


class FakeVector:
    def __init__(self, values: list[float]) -> None:
        self.values = values

    def tolist(self) -> list[float]:
        return self.values


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], int]] = []

    def passage_embed(self, texts: list[str], *, batch_size: int):
        self.calls.append(("passage", texts, batch_size))
        return iter(FakeVector([0.1, 0.2]) for _ in texts)

    def query_embed(self, texts: list[str], *, batch_size: int):
        self.calls.append(("query", texts, batch_size))
        return iter(FakeVector([0.3, 0.4]) for _ in texts)


def configure_model(monkeypatch) -> FakeModel:
    model = FakeModel()
    monkeypatch.setattr(embeddings, "_embedding_model", lambda: model)
    monkeypatch.setattr(
        embeddings,
        "settings",
        SimpleNamespace(embedding_dim=2),
    )
    return model


def test_embed_texts_uses_passage_embeddings_by_default(monkeypatch) -> None:
    model = configure_model(monkeypatch)

    result = asyncio.run(embeddings.embed_texts(["a", "b"]))

    assert result == [[0.1, 0.2], [0.1, 0.2]]
    assert model.calls == [("passage", ["a", "b"], 32)]


def test_embed_texts_uses_query_embeddings(monkeypatch) -> None:
    model = configure_model(monkeypatch)

    result = asyncio.run(embeddings.embed_texts(["question"], kind="query"))

    assert result == [[0.3, 0.4]]
    assert model.calls == [("query", ["question"], 32)]


def test_embed_texts_skips_model_for_empty_input(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "_embedding_model",
        lambda: pytest.fail("model should not be loaded"),
    )

    assert asyncio.run(embeddings.embed_texts([])) == []


def test_embed_texts_validates_dimensions(monkeypatch) -> None:
    model = configure_model(monkeypatch)
    monkeypatch.setattr(embeddings, "settings", SimpleNamespace(embedding_dim=3))

    with pytest.raises(RuntimeError, match="3 dimensions"):
        asyncio.run(embeddings.embed_texts(["bad dimensions"]))

    assert model.calls == [("passage", ["bad dimensions"], 32)]
