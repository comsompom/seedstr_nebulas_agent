from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from seedstr_agent import config


class ConfigTests(unittest.TestCase):
    def test_split_models_trims_and_filters(self) -> None:
        self.assertEqual(config._split_models(" a, ,b ,, c "), ["a", "b", "c"])

    def test_has_llm_provider_with_gemini(self) -> None:
        settings = config.Settings(
            seedstr_base_url="https://example.com",
            seedstr_api_key="k",
            solana_wallet_address="w",
            seedstr_owner_url=None,
            gemini_api_key="g",
            openai_api_key="",
            gemini_models=["g1"],
            openai_models=[],
            poll_interval_seconds=30,
            min_budget_usd=0.0,
            max_jobs_per_cycle=20,
            request_timeout_seconds=30,
            log_level="INFO",
            state_path=Path(".agent_state.json"),
        )
        self.assertTrue(settings.has_llm_provider)

    def test_has_llm_provider_with_no_models(self) -> None:
        settings = config.Settings(
            seedstr_base_url="https://example.com",
            seedstr_api_key="k",
            solana_wallet_address="w",
            seedstr_owner_url=None,
            gemini_api_key="",
            openai_api_key="",
            gemini_models=[],
            openai_models=[],
            poll_interval_seconds=30,
            min_budget_usd=0.0,
            max_jobs_per_cycle=20,
            request_timeout_seconds=30,
            log_level="INFO",
            state_path=Path(".agent_state.json"),
        )
        self.assertFalse(settings.has_llm_provider)

    def test_load_settings_reads_env(self) -> None:
        env = {
            "SEEDSTR_BASE_URL": "https://api.example.com/",
            "SEEDSTR_API_KEY": "  key  ",
            "SOLANA_WALLET_ADDRESS": " wallet ",
            "SEEDSTR_OWNER_URL": " https://owner.example ",
            "GEMINI_API_KEY": "g-key",
            "OPENAI_API_KEY": "",
            "GEMINI_MODELS": "g1,g2",
            "OPENAI_MODELS": "",
            "POLL_INTERVAL_SECONDS": "15",
            "MIN_BUDGET_USD": "2.5",
            "MAX_JOBS_PER_CYCLE": "8",
            "REQUEST_TIMEOUT_SECONDS": "45",
            "LOG_LEVEL": "debug",
            "STATE_PATH": "custom_state.json",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = config.load_settings()

        self.assertEqual(settings.seedstr_base_url, "https://api.example.com")
        self.assertEqual(settings.seedstr_api_key, "key")
        self.assertEqual(settings.solana_wallet_address, "wallet")
        self.assertEqual(settings.seedstr_owner_url, "https://owner.example")
        self.assertEqual(settings.gemini_models, ["g1", "g2"])
        self.assertEqual(settings.poll_interval_seconds, 15)
        self.assertEqual(settings.min_budget_usd, 2.5)
        self.assertEqual(settings.max_jobs_per_cycle, 8)
        self.assertEqual(settings.request_timeout_seconds, 45)
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.state_path, Path("custom_state.json"))


if __name__ == "__main__":
    unittest.main()
