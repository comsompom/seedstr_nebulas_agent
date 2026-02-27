from __future__ import annotations

import logging
from dataclasses import dataclass

import google.generativeai as genai
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

        self._gemini_enabled = bool(gemini_api_key and gemini_models)
        self._openai_enabled = bool(openai_api_key and openai_models)

        self._openai_client = OpenAI(api_key=openai_api_key) if self._openai_enabled else None

        if self._gemini_enabled:
            genai.configure(api_key=gemini_api_key)
            self.targets.extend(ModelTarget("gemini", model) for model in gemini_models)

        if self._openai_enabled:
            self.targets.extend(ModelTarget("openai", model) for model in openai_models)

        if not self.targets:
            raise ValueError("No LLM models configured. Set GEMINI_API_KEY/OPENAI_API_KEY with model lists.")

    def generate(self, prompt: str, system_prompt: str) -> tuple[str, str]:
        errors: list[str] = []

        for target in self.targets:
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
                msg = f"{target.provider}:{target.model} failed: {exc}"
                self.logger.warning(msg)
                errors.append(msg)

        raise RuntimeError("All configured models failed. " + " | ".join(errors))

    def _generate_gemini(self, model_name: str, prompt: str, system_prompt: str) -> str:
        model = genai.GenerativeModel(model_name=model_name)
        full_prompt = (
            f"{system_prompt}\n\n"
            f"User task:\n{prompt}\n\n"
            "Return only the final answer for the user."
        )
        response = model.generate_content(full_prompt)
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

