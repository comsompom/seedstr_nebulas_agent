from __future__ import annotations

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from seedstr_agent.llm import LLMFailoverClient


class LLMTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("llm-tests")

    def test_init_requires_any_models(self) -> None:
        with self.assertRaisesRegex(ValueError, "No LLM models configured"):
            LLMFailoverClient("", "", [], [], self.logger)

    def test_generate_falls_back_between_targets(self) -> None:
        with patch("seedstr_agent.llm.OpenAI") as openai_cls, patch("seedstr_agent.llm.genai.configure"):
            openai_cls.return_value = MagicMock()
            client = LLMFailoverClient(
                gemini_api_key="g",
                openai_api_key="o",
                gemini_models=["g1"],
                openai_models=["o1"],
                logger=self.logger,
            )

        client._generate_gemini = MagicMock(side_effect=RuntimeError("gemini down"))  # type: ignore[method-assign]
        client._generate_openai = MagicMock(return_value="final")  # type: ignore[method-assign]

        text, used = client.generate(prompt="hello", system_prompt="system")
        self.assertEqual(text, "final")
        self.assertEqual(used, "openai:o1")

    def test_generate_raises_after_all_fail(self) -> None:
        with patch("seedstr_agent.llm.OpenAI") as openai_cls:
            openai_cls.return_value = MagicMock()
            client = LLMFailoverClient(
                gemini_api_key="",
                openai_api_key="o",
                gemini_models=[],
                openai_models=["o1"],
                logger=self.logger,
            )
        client._generate_openai = MagicMock(side_effect=RuntimeError("openai down"))  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "All configured models failed"):
            client.generate(prompt="x", system_prompt="y")

    def test_generate_openai_handles_empty_content(self) -> None:
        with patch("seedstr_agent.llm.OpenAI") as openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
            )
            openai_cls.return_value = mock_client
            client = LLMFailoverClient(
                gemini_api_key="",
                openai_api_key="o",
                gemini_models=[],
                openai_models=["o1"],
                logger=self.logger,
            )

        with self.assertRaisesRegex(RuntimeError, "OpenAI response is empty"):
            client._generate_openai("o1", "p", "s")


if __name__ == "__main__":
    unittest.main()
