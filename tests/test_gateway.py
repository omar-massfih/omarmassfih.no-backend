from types import SimpleNamespace

import pytest

from app import gateway


def test_resolve_token_prefers_configured_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway,
        "settings",
        SimpleNamespace(ai_gateway_api_key="api-key", vercel_oidc_token="oidc-token"),
    )

    assert gateway.resolve_token("request-token") == "api-key"


def test_resolve_token_uses_request_oidc_token(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway,
        "settings",
        SimpleNamespace(ai_gateway_api_key=None, vercel_oidc_token="fallback-token"),
    )

    assert gateway.resolve_token("request-token") == "request-token"


def test_resolve_token_rejects_missing_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway,
        "settings",
        SimpleNamespace(ai_gateway_api_key=None, vercel_oidc_token=None),
    )

    with pytest.raises(gateway.GatewayConfigError, match="not configured"):
        gateway.resolve_token()
