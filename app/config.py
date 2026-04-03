from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent

# Accept both project-root `.env` and `app/.env` to reduce setup friction.
load_dotenv(BASE_DIR / ".env")
load_dotenv(APP_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    gmail_client_id: str
    gmail_client_secret: str
    gmail_redirect_uri: str
    webhook_url: str
    poll_interval_seconds: int = 45
    port: int = 8000
    database_path: str = "mailboxes.db"


def load_settings() -> Settings:
    return Settings(
        gmail_client_id=_required("GMAIL_CLIENT_ID"),
        gmail_client_secret=_required("GMAIL_CLIENT_SECRET"),
        gmail_redirect_uri=_required("GMAIL_REDIRECT_URI"),
        webhook_url=_required("WEBHOOK_URL"),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "45")),
        port=int(os.getenv("PORT", "8000")),
        database_path=os.getenv("DATABASE_PATH", "mailboxes.db"),
    )


def get_missing_settings() -> list[str]:
    required = [
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REDIRECT_URI",
        "WEBHOOK_URL",
    ]
    return [name for name in required if not os.getenv(name)]


def should_allow_insecure_oauth_transport() -> bool:
    redirect_uri = os.getenv("GMAIL_REDIRECT_URI", "")
    if not redirect_uri:
        return False
    parsed = urlparse(redirect_uri)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
