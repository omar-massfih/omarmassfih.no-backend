import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()
# `vercel env pull` writes .env.local; values already set (including by .env) win.
load_dotenv(".env.local")


@dataclass(frozen=True)
class Settings:
    turso_database_url: str | None = os.getenv("TURSO_DATABASE_URL")
    turso_auth_token: str | None = os.getenv("TURSO_AUTH_TOKEN")
    ai_gateway_api_key: str | None = os.getenv("AI_GATEWAY_API_KEY")
    vercel_oidc_token: str | None = os.getenv("VERCEL_OIDC_TOKEN")
    ai_gateway_base_url: str = os.getenv("AI_GATEWAY_BASE_URL") or "https://ai-gateway.vercel.sh/v1"
    chat_model: str = os.getenv("CHAT_MODEL") or "openai/gpt-oss-120b"
    embedding_model: str = os.getenv("EMBEDDING_MODEL") or "openai/text-embedding-3-small"
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM") or "1536")
    chat_top_k: int = int(os.getenv("CHAT_TOP_K") or "6")
    chat_max_tokens: int = int(os.getenv("CHAT_MAX_TOKENS") or "1000")


settings = Settings()
