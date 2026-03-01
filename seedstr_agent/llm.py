from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from google import genai
from openai import OpenAI


@dataclass(frozen=True)
class ModelTarget:
    provider: str
    model: str


class LLMFailoverClient:
    def __init__(
        self,
        gemini_api_key: str,
        openai_api_key: str,
        gemini_models: list[str],
        openai_models: list[str],
        logger: logging.Logger,
    ) -> None:
        self.logger = logger
        self.targets: list[ModelTarget] = []
        self._unavailable_models: set[str] = set()
        self._gemini_cooldown_until_epoch: float = 0.0

        self._gemini_enabled = bool(gemini_api_key and gemini_models)
        self._openai_enabled = bool(openai_api_key and openai_models)

        self._gemini_client = genai.Client(api_key=gemini_api_key) if self._gemini_enabled else None
        self._openai_client = OpenAI(api_key=openai_api_key) if self._openai_enabled else None

        if self._gemini_enabled:
            self.targets.extend(ModelTarget("gemini", model) for model in gemini_models)

        if self._openai_enabled:
            self.targets.extend(ModelTarget("openai", model) for model in openai_models)

        if not self.targets:
            raise ValueError("No LLM models configured. Set GEMINI_API_KEY/OPENAI_API_KEY with model lists.")

    def generate(self, prompt: str, system_prompt: str) -> tuple[str, str]:
        errors: list[str] = []
        now = time.time()

        for target in self.targets:
            if target.provider == "gemini":
                if target.model in self._unavailable_models:
                    continue
                if now < self._gemini_cooldown_until_epoch:
                    continue
            try:
                self.logger.info("Trying %s model: %s", target.provider, target.model)
                if target.provider == "gemini":
                    text = self._generate_gemini(target.model, prompt, system_prompt)
                else:
                    text = self._generate_openai(target.model, prompt, system_prompt)
                if text.strip():
                    return text.strip(), f"{target.provider}:{target.model}"
                errors.append(f"{target.provider}:{target.model} returned empty output")
            except Exception as exc:
                if target.provider == "gemini":
                    self._handle_gemini_error(target.model, str(exc))
                msg = f"{target.provider}:{target.model} failed: {exc}"
                self.logger.warning(msg)
                errors.append(msg)

        raise RuntimeError("All configured models failed. " + " | ".join(errors))

    def _generate_gemini(self, model_name: str, prompt: str, system_prompt: str) -> str:
        if not self._gemini_client:
            raise RuntimeError("Gemini client is not configured")
        full_prompt = (
            f"{system_prompt}\n\n"
            f"User task:\n{prompt}\n\n"
            "Return only the final answer for the user."
        )
        response = self._gemini_client.models.generate_content(
            model=model_name,
            contents=full_prompt,
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini response has no text field")
        return text

    def _generate_openai(self, model_name: str, prompt: str, system_prompt: str) -> str:
        if not self._openai_client:
            raise RuntimeError("OpenAI client is not configured")
        completion = self._openai_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        content = completion.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI response is empty")
        return content

    def _handle_gemini_error(self, model_name: str, message: str) -> None:
        lowered = message.lower()
        if "is not found" in lowered or "not supported for generatecontent" in lowered:
            self._unavailable_models.add(model_name)
            self.logger.info("Marking Gemini model unavailable for this run: %s", model_name)
            return

        if "quota" in lowered or "resource_exhausted" in lowered or "too many requests" in lowered:
            wait_seconds = self._parse_retry_seconds(message) or 60
            # When day-level free-tier quota is exhausted, short retry delays are misleading.
            if "perday" in lowered or "limit: 0" in lowered:
                wait_seconds = max(wait_seconds, 1800)
            self._gemini_cooldown_until_epoch = max(
                self._gemini_cooldown_until_epoch,
                time.time() + wait_seconds,
            )
            self.logger.info("Gemini is in cooldown for %ss", int(wait_seconds))

    @staticmethod
    def _parse_retry_seconds(message: str) -> int | None:
        match = re.search(r"retry in\s+(\d+(?:\.\d+)?)s?", message, flags=re.IGNORECASE)
        if match:
            return max(1, int(float(match.group(1))))
        match = re.search(r"retrydelay'\s*:\s*'(\d+)s'", message, flags=re.IGNORECASE)
        if match:
            return max(1, int(match.group(1)))
        return None

