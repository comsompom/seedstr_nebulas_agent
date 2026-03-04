from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _split_models(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_seedstr_base_url(raw: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return "https://www.seedstr.io/api/v2"

    # Legacy/incorrect host seen in some env setups.
    if "api.seedstr.io" in value:
        return "https://www.seedstr.io/api/v2"

    # If user provides site root or docs host, force API v2 base.
    if value.startswith("https://www.seedstr.io") and "/api/v2" not in value:
        return "https://www.seedstr.io/api/v2"

    # If user provides /api, upgrade to /api/v2.
    if value.endswith("/api"):
        return f"{value}/v2"

    return value


def _to_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    seedstr_base_url: str
    seedstr_api_key: str
    solana_wallet_address: str
    seedstr_owner_url: str | None
    gemini_api_key: str
    openai_api_key: str
    gemini_models: list[str]
    openai_models: list[str]
    poll_interval_seconds: int
    min_budget_usd: float
    max_jobs_per_cycle: int
    request_timeout_seconds: int
    log_level: str
    state_path: Path
    submission_log_path: Path
    reprocess_seen_jobs: bool = False

    @property
    def has_llm_provider(self) -> bool:
        return bool(
            (self.gemini_api_key and self.gemini_models)
            or (self.openai_api_key and self.openai_models)
        )


def load_settings() -> Settings:
    load_dotenv()

    base_dir = Path(__file__).resolve().parents[1]
    default_state_path = base_dir / ".agent_state.json"

    return Settings(
        seedstr_base_url=_normalize_seedstr_base_url(os.getenv("SEEDSTR_BASE_URL", "https://www.seedstr.io/api/v2")),
        seedstr_api_key=os.getenv("SEEDSTR_API_KEY", "").strip(),
        solana_wallet_address=os.getenv("SOLANA_WALLET_ADDRESS", "").strip(),
        seedstr_owner_url=os.getenv("SEEDSTR_OWNER_URL", "").strip() or None,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        gemini_models=_split_models(
            os.getenv(
                "GEMINI_MODELS",
                "gemini-2.0-flash,gemini-2.5-pro",
            )
        ),
        openai_models=_split_models(os.getenv("OPENAI_MODELS", "gpt-4o-mini,gpt-4.1-mini,gpt-4.1")),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "180")),
        min_budget_usd=float(os.getenv("MIN_BUDGET_USD", "0.0")),
        max_jobs_per_cycle=int(os.getenv("MAX_JOBS_PER_CYCLE", "20")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        state_path=Path(os.getenv("STATE_PATH", str(default_state_path))),
        submission_log_path=Path(os.getenv("SUBMISSION_LOG_PATH", str(base_dir / ".submission_log.jsonl"))),
        reprocess_seen_jobs=_to_bool(os.getenv("REPROCESS_SEEN_JOBS"), default=False),
    )

