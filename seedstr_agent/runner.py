from __future__ import annotations

import json
import logging
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api import SeedstrApiClient, SeedstrApiError
from .config import Settings
from .llm import LLMFailoverClient


class AgentRunner:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.api = SeedstrApiClient(
            base_url=settings.seedstr_base_url,
            api_key=settings.seedstr_api_key,
            timeout_seconds=settings.request_timeout_seconds,
        )
        self.llm = LLMFailoverClient(
            gemini_api_key=settings.gemini_api_key,
            openai_api_key=settings.openai_api_key,
            gemini_models=settings.gemini_models,
            openai_models=settings.openai_models,
            logger=logger,
        )
        self._seen_jobs = self._load_seen_jobs(settings.state_path)

    def run_forever(self) -> None:
        self.logger.info("Agent started. Polling every %ss", self.settings.poll_interval_seconds)
        while True:
            self.run_once()
            time.sleep(self.settings.poll_interval_seconds)

    def run_once(self) -> None:
        try:
            payload = self.api.list_jobs(limit=self.settings.max_jobs_per_cycle, offset=0)
        except SeedstrApiError as exc:
            self.logger.error("Failed to list jobs: %s", exc)
            return

        jobs = payload.get("jobs", [])
        if not jobs:
            self.logger.info("No jobs available")
            return

        for job in jobs:
            self._process_job(job)

    def _process_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id", ""))
        if not job_id:
            return

        if job_id in self._seen_jobs:
            return

        effective_budget = self._effective_budget(job)
        if effective_budget < self.settings.min_budget_usd:
            self.logger.info(
                "Skip job %s: budget %.2f < min %.2f",
                job_id,
                effective_budget,
                self.settings.min_budget_usd,
            )
            self._mark_seen(job_id)
            return

        job_type = str(job.get("jobType", "STANDARD"))
        if job_type == "SWARM":
            try:
                self.api.accept_job(job_id)
                self.logger.info("Accepted SWARM job %s", job_id)
            except SeedstrApiError as exc:
                self.logger.warning("Could not accept SWARM job %s: %s", job_id, exc)
                self._mark_seen(job_id)
                return

        prompt = str(job.get("prompt", "")).strip()
        if not prompt:
            self.logger.warning("Job %s has empty prompt", job_id)
            self._mark_seen(job_id)
            return

        system_prompt = (
            "You are an autonomous Seedstr marketplace agent. "
            "Give accurate and concise responses. "
            "If you are unsure, say what assumptions you made."
        )

        try:
            answer, used_model = self.llm.generate(prompt=prompt, system_prompt=system_prompt)
            with tempfile.TemporaryDirectory(prefix=f"seedstr-{job_id}-") as temp_dir:
                archive_path = Path(temp_dir) / f"seedstr-job-{job_id}-response.zip"
                self._create_submission_archive(
                    archive_path=archive_path,
                    job_id=job_id,
                    prompt=prompt,
                    answer=answer,
                    model_name=used_model,
                )
                upload_result = self.api.upload_file(archive_path)
                self.api.respond_file(job_id, upload_result=upload_result, fallback_text=answer)
            self.logger.info("Submitted ZIP response for %s using %s", job_id, used_model)
            self._mark_seen(job_id)
        except Exception as exc:
            self.logger.error("Failed processing job %s: %s", job_id, exc)

    @staticmethod
    def _effective_budget(job: dict[str, Any]) -> float:
        if job.get("jobType") == "SWARM":
            per_agent = job.get("budgetPerAgent")
            if per_agent is not None:
                try:
                    return float(per_agent)
                except (TypeError, ValueError):
                    return 0.0
        try:
            return float(job.get("budget", 0))
        except (TypeError, ValueError):
            return 0.0

    def _load_seen_jobs(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            jobs = payload.get("seen_jobs", [])
            return {str(item) for item in jobs}
        except Exception:
            return set()

    def _mark_seen(self, job_id: str) -> None:
        self._seen_jobs.add(job_id)
        trimmed = list(self._seen_jobs)[-1000:]
        self.settings.state_path.write_text(
            json.dumps({"seen_jobs": trimmed}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _create_submission_archive(
        *,
        archive_path: Path,
        job_id: str,
        prompt: str,
        answer: str,
        model_name: str,
    ) -> None:
        metadata = {
            "job_id": job_id,
            "model": model_name,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("response.txt", f"{answer.rstrip()}\n")
            zip_file.writestr("prompt.txt", f"{prompt.rstrip()}\n")
            zip_file.writestr("metadata.json", json.dumps(metadata, indent=2))

