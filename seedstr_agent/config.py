from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _split_models(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


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
        seedstr_base_url=os.getenv("SEEDSTR_BASE_URL", "https://www.seedstr.io/api/v2").rstrip("/"),
        seedstr_api_key=os.getenv("SEEDSTR_API_KEY", "").strip(),
        solana_wallet_address=os.getenv("SOLANA_WALLET_ADDRESS", "").strip(),
        seedstr_owner_url=os.getenv("SEEDSTR_OWNER_URL", "").strip() or None,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        gemini_models=_split_models(
            os.getenv(
                "GEMINI_MODELS",
                "gemini-2.5-flash-preview-05-20,gemini-2.0-flash,gemini-2.5-pro,gemini-2.5-pro-preview-06-05,gemini-3-pro-preview",
            )
        ),
        openai_models=_split_models(os.getenv("OPENAI_MODELS", "gpt-4o-mini,gpt-4.1-mini,gpt-4.1")),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "30")),
        min_budget_usd=float(os.getenv("MIN_BUDGET_USD", "0.0")),
        max_jobs_per_cycle=int(os.getenv("MAX_JOBS_PER_CYCLE", "20")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        state_path=Path(os.getenv("STATE_PATH", str(default_state_path))),
    )

