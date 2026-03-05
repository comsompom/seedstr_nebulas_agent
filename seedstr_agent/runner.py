from __future__ import annotations

import json
import logging
import re
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
        self._deferred_jobs: dict[str, float] = {}
        self._submission_log_path = settings.submission_log_path
        self._runtime_stats: dict[str, int] = {
            "cycles": 0,
            "submitted_total": 0,
            "deferred_total": 0,
            "skipped_seen_total": 0,
            "skipped_budget_total": 0,
            "skipped_other_total": 0,
            "failed_total": 0,
        }
        self._last_cycle_summary: dict[str, int] = {
            "submitted": 0,
            "deferred": 0,
            "skipped_seen": 0,
            "skipped_budget": 0,
            "skipped_other": 0,
            "failed": 0,
        }

    def run_forever(self) -> None:
        self.logger.info("Agent started. Polling every %ss", self.settings.poll_interval_seconds)
        cycle = 0
        while True:
            try:
                cycle += 1
                self.logger.info("Polling cycle %s started", cycle)
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - keep long-running worker alive.
                self.logger.exception("Unhandled polling cycle error: %s", exc)
            time.sleep(self.settings.poll_interval_seconds)

    def run_once(self) -> None:
        try:
            payload = self.api.list_jobs(limit=self.settings.max_jobs_per_cycle, offset=0)
        except SeedstrApiError as exc:
            self.logger.error("Failed to list jobs: %s", exc)
            return

        jobs = payload.get("jobs", [])
        self.logger.info("Fetched %s jobs from marketplace", len(jobs))
        if not jobs:
            self.logger.info("No jobs available")
            return

        counts = {
            "submitted": 0,
            "deferred": 0,
            "skipped_seen": 0,
            "skipped_budget": 0,
            "skipped_other": 0,
            "failed": 0,
        }
        deferred_waits: list[int] = []
        for job in jobs:
            outcome = self._process_job(job)
            if outcome in counts:
                counts[outcome] += 1
            elif outcome.startswith("deferred:"):
                counts["deferred"] += 1
                try:
                    deferred_waits.append(int(outcome.split(":", 1)[1]))
                except (TypeError, ValueError):
                    pass
            elif outcome.startswith("skipped_"):
                counts["skipped_other"] += 1
            else:
                counts["failed"] += 1
        self.logger.info(
            "Cycle summary: submitted=%s deferred=%s skipped_seen=%s skipped_budget=%s skipped_other=%s failed=%s",
            counts["submitted"],
            counts["deferred"],
            counts["skipped_seen"],
            counts["skipped_budget"],
            counts["skipped_other"],
            counts["failed"],
        )
        self._runtime_stats["cycles"] += 1
        self._runtime_stats["submitted_total"] += counts["submitted"]
        self._runtime_stats["deferred_total"] += counts["deferred"]
        self._runtime_stats["skipped_seen_total"] += counts["skipped_seen"]
        self._runtime_stats["skipped_budget_total"] += counts["skipped_budget"]
        self._runtime_stats["skipped_other_total"] += counts["skipped_other"]
        self._runtime_stats["failed_total"] += counts["failed"]
        self._last_cycle_summary = counts.copy()
        if deferred_waits:
            self.logger.info(
                "Deferred jobs are pending; next retry in ~%ss (max wait ~%ss)",
                min(deferred_waits),
                max(deferred_waits),
            )

    def _process_job(self, job: dict[str, Any]) -> str:
        job_id = str(job.get("id", ""))
        if not job_id:
            return "skipped_invalid_id"

        if (not self.settings.reprocess_seen_jobs) and job_id in self._seen_jobs:
            return "skipped_seen"

        defer_until = self._deferred_jobs.get(job_id)
        if defer_until and time.time() < defer_until:
            seconds_left = max(1, int(defer_until - time.time()))
            self.logger.info("Job %s is deferred for another %ss", job_id, seconds_left)
            return f"deferred:{seconds_left}"
        if defer_until and time.time() >= defer_until:
            del self._deferred_jobs[job_id]

        effective_budget = self._effective_budget(job)
        if effective_budget < self.settings.min_budget_usd:
            self.logger.info(
                "Skip job %s: budget %.2f < min %.2f",
                job_id,
                effective_budget,
                self.settings.min_budget_usd,
            )
            self._mark_seen(job_id)
            return "skipped_budget"

        job_type = str(job.get("jobType", "STANDARD"))
        if job_type == "SWARM":
            try:
                self.api.accept_job(job_id)
                self.logger.info("Accepted SWARM job %s", job_id)
            except SeedstrApiError as exc:
                self.logger.warning("Could not accept SWARM job %s: %s", job_id, exc)
                self._mark_seen(job_id)
                return "skipped_accept_failed"

        prompt = str(job.get("prompt", "")).strip()
        if not prompt:
            self.logger.warning("Job %s has empty prompt", job_id)
            self._mark_seen(job_id)
            return "skipped_empty_prompt"

        system_prompt = (
            "You are an autonomous Seedstr marketplace agent. "
            "Give accurate and concise responses. "
            "If you are unsure, say what assumptions you made."
        )

        try:
            answer, used_model = self.llm.generate(prompt=prompt, system_prompt=system_prompt)
            zip_size_bytes: int | None = None
            with tempfile.TemporaryDirectory(prefix=f"seedstr-{job_id}-") as temp_dir:
                archive_path = Path(temp_dir) / f"seedstr-job-{job_id}-response.zip"
                self._create_submission_archive(
                    archive_path=archive_path,
                    job_id=job_id,
                    prompt=prompt,
                    answer=answer,
                    model_name=used_model,
                )
                zip_size_bytes = archive_path.stat().st_size
                upload_result = self.api.upload_file(archive_path)
                self.api.respond_file(job_id, upload_result=upload_result, fallback_text=answer)
            self._append_submission_log(
                job_id=job_id,
                submitted=True,
                zip_size_bytes=zip_size_bytes,
                status="submitted",
                model=used_model,
            )
            self.logger.info("Submitted ZIP response for %s using %s", job_id, used_model)
            self._deferred_jobs.pop(job_id, None)
            self._mark_seen(job_id)
            return "submitted"
        except Exception as exc:
            if self._is_already_submitted_error(exc):
                self._append_submission_log(
                    job_id=job_id,
                    submitted=False,
                    zip_size_bytes=None,
                    status="already_submitted",
                    model=None,
                    error=str(exc),
                )
                self.logger.info("Job %s already has a submitted response; marking as seen", job_id)
                self._log_job_server_status(job_id)
                self._mark_seen(job_id)
                return "skipped_already_submitted"
            retry_after = self._retry_after_seconds_from_error(exc)
            if retry_after is not None:
                self._append_submission_log(
                    job_id=job_id,
                    submitted=False,
                    zip_size_bytes=None,
                    status="deferred_rate_limit",
                    model=None,
                    error=str(exc),
                )
                self._deferred_jobs[job_id] = time.time() + retry_after
                self.logger.warning(
                    "Deferring job %s for %ss due to rate limit",
                    job_id,
                    retry_after,
                )
                return f"deferred:{retry_after}"
            self._append_submission_log(
                job_id=job_id,
                submitted=False,
                zip_size_bytes=None,
                status="failed",
                model=None,
                error=str(exc),
            )
            self.logger.error("Failed processing job %s: %s", job_id, exc)
            return "failed"

    @staticmethod
    def _is_already_submitted_error(error: Exception) -> bool:
        message = str(error).lower()
        return "already submitted a response to this job" in message

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
    def _retry_after_seconds_from_error(error: Exception) -> int | None:
        message = str(error)
        if "too many requests" not in message.lower():
            return None
        match = re.search(r"try again in\s+(\d+)\s+seconds", message, flags=re.IGNORECASE)
        if not match:
            return 60
        return max(1, int(match.group(1)))

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

    def get_runtime_stats(self) -> dict[str, Any]:
        return {
            **self._runtime_stats,
            "seen_jobs_count": len(self._seen_jobs),
            "deferred_jobs_count": len(self._deferred_jobs),
            "last_cycle": self._last_cycle_summary.copy(),
        }

    def _append_submission_log(
        self,
        *,
        job_id: str,
        submitted: bool,
        zip_size_bytes: int | None,
        status: str,
        model: str | None,
        error: str | None = None,
    ) -> None:
        entry = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "job_id": job_id,
            "submitted": submitted,
            "zip_size_bytes": zip_size_bytes,
            "status": status,
            "model": model,
            "error": error,
        }
        self._submission_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._submission_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def _log_job_server_status(self, job_id: str) -> None:
        try:
            job_payload = self.api.get_job(job_id)
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            self.logger.warning("Could not fetch server status for job %s: %s", job_id, exc)
            return

        status = job_payload.get("status")
        response_status, response_id, response_source = self._extract_response_status(job_payload)
        if response_status is None:
            response_status = "NOT_EXPOSED"
        if response_id is None:
            response_id = "NOT_EXPOSED"

        self.logger.info(
            "Server job status for %s: job_status=%s response_status=%s response_id=%s source=%s",
            job_id,
            status,
            response_status,
            response_id,
            response_source,
        )

    @staticmethod
    def _extract_response_status(job_payload: dict[str, Any]) -> tuple[Any, Any, str]:
        # Common single-object locations
        for key in ("response", "myResponse", "submission"):
            value = job_payload.get(key)
            if isinstance(value, dict):
                return value.get("status"), value.get("id"), key

        # Common array locations
        for key in ("responses", "submissions"):
            value = job_payload.get(key)
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict):
                    return first.get("status"), first.get("id"), key

        return None, None, "not_exposed_by_endpoint"

