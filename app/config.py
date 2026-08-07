import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()
# `vercel env pull` writes .env.local; values already set (including by .env) win.
load_dotenv(".env.local")


@dataclass(frozen=True)
class Settings:
    database_url: str | None = os.getenv("DATABASE_URL")
    ai_gateway_api_key: str | None = os.getenv("AI_GATEWAY_API_KEY")
    vercel_oidc_token: str | None = os.getenv("VERCEL_OIDC_TOKEN")
    ai_gateway_base_url: str = os.getenv("AI_GATEWAY_BASE_URL") or "https://ai-gateway.vercel.sh/v1"
    chat_model: str = os.getenv("CHAT_MODEL") or "openai/gpt-oss-20b"
    embedding_model: str = os.getenv("EMBEDDING_MODEL") or "openai/text-embedding-3-small"
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM") or "1536")
    chat_top_k: int = int(os.getenv("CHAT_TOP_K") or "6")
    chat_graph_top_k: int = int(os.getenv("CHAT_GRAPH_TOP_K") or "2")
    chat_max_tokens: int = int(os.getenv("CHAT_MAX_TOKENS") or "1000")
    hybrid_semantic_weight: float = float(os.getenv("HYBRID_SEMANTIC_WEIGHT") or "1.0")
    hybrid_lexical_weight: float = float(os.getenv("HYBRID_LEXICAL_WEIGHT") or "0.7")
    hybrid_rrf_k: int = int(os.getenv("HYBRID_RRF_K") or "60")
    hybrid_candidate_k: int = int(os.getenv("HYBRID_CANDIDATE_K") or "24")

    def __post_init__(self) -> None:
        if self.chat_top_k <= 0:
            raise ValueError("CHAT_TOP_K must be greater than zero")
        if self.hybrid_semantic_weight < 0 or self.hybrid_lexical_weight < 0:
            raise ValueError("hybrid ranking weights must be non-negative")
        if self.hybrid_semantic_weight == self.hybrid_lexical_weight == 0:
            raise ValueError("at least one hybrid ranking weight must be positive")
        if self.hybrid_rrf_k <= 0:
            raise ValueError("HYBRID_RRF_K must be greater than zero")
        if self.hybrid_candidate_k <= 0:
            raise ValueError("HYBRID_CANDIDATE_K must be greater than zero")


settings = Settings()
