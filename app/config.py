"""Application configuration, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # no-op if the file is absent; real env vars take precedence


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    MAX_CONTENT_LENGTH = 16 * 1024  # JSON request bodies are tiny; reject anything larger.
    JSON_SORT_KEYS = False

    # Caching of genuine upstream data (tiles, windows, outlines) on local disk.
    CACHE_DIR = os.environ.get("CACHE_DIR", str(BASE_DIR / "instance" / "cache"))

    # Upstream timeouts (seconds).
    USDA_TIMEOUT = float(os.environ.get("USDA_TIMEOUT", "20"))
    CENSUS_TIMEOUT = float(os.environ.get("CENSUS_TIMEOUT", "6"))

    # Rate limiting. memory:// is DEVELOPMENT-ONLY (per-process, resets on restart).
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "600 per minute")
    RATELIMIT_LOOKUP = os.environ.get("RATELIMIT_LOOKUP", "30 per minute")
    RATELIMIT_AI = os.environ.get("RATELIMIT_AI", "5 per minute;40 per day")
    RATELIMIT_HEADERS_ENABLED = True

    # Cloudflare Turnstile (protects the AI endpoint only).
    TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
    TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
    TURNSTILE_TIMEOUT = float(os.environ.get("TURNSTILE_TIMEOUT", "6"))

    # AI audit via Anthropic Claude. AI_ENABLED is the kill switch.
    AI_ENABLED = _bool("AI_ENABLED", True)
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    AI_MODEL = os.environ.get("AI_MODEL") or "claude-haiku-5-5"
    AI_MAX_OUTPUT_TOKENS = _int("AI_MAX_OUTPUT_TOKENS", 4000)
    AI_MAX_INPUT_CHARS = _int("AI_MAX_INPUT_CHARS", 24000)
    AI_TIMEOUT = float(os.environ.get("AI_TIMEOUT", "45"))
    AI_MAX_ATTEMPTS = max(1, min(3, _int("AI_MAX_ATTEMPTS", 2)))

    # Selection tokens (signed proof that a crop lookup happened server-side).
    SELECTION_TOKEN_MAX_AGE = _int("SELECTION_TOKEN_MAX_AGE", 6 * 3600)

    # Log selected coordinates? Off by default (privacy).
    LOG_COORDINATES = _bool("LOG_COORDINATES", False)


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    RATELIMIT_STORAGE_URI = "memory://"
    TURNSTILE_SITE_KEY = "1x00000000000000000000AA"
    TURNSTILE_SECRET_KEY = "1x0000000000000000000000000000000AA"
    ANTHROPIC_API_KEY = "test-key"
    AI_ENABLED = True
