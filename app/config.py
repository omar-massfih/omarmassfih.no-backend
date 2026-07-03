import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    turso_database_url: str | None = os.getenv("TURSO_DATABASE_URL")
    turso_auth_token: str | None = os.getenv("TURSO_AUTH_TOKEN")


settings = Settings()
