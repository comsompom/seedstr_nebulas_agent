from __future__ import annotations

import logging
import os
import sys
import threading
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify

# Allow running this file directly: `python ./flask_app/app.py`
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from seedstr_agent.api import SeedstrApiClient, SeedstrApiError
from seedstr_agent.config import load_settings
from seedstr_agent.runner import AgentRunner


APP_START_UTC = datetime.now(timezone.utc).isoformat()
AGENT_STATUS: dict[str, Any] = {
    "started": False,
    "running": False,
    "last_error": None,
    "last_started_utc": None,
}
_AGENT_LOCK = threading.Lock()
RUNNER_INSTANCE: AgentRunner | None = None

app = Flask(__name__)


def _start_agent_loop() -> None:
    global RUNNER_INSTANCE
    with _AGENT_LOCK:
        if AGENT_STATUS["running"]:
            return
        AGENT_STATUS["started"] = True
        AGENT_STATUS["running"] = True
        AGENT_STATUS["last_started_utc"] = datetime.now(timezone.utc).isoformat()
        AGENT_STATUS["last_error"] = None

    logger = logging.getLogger("seedstr-agent-flask")
    try:
        settings = load_settings()
        runner = AgentRunner(settings=settings, logger=logger)
        RUNNER_INSTANCE = runner
        runner.run_forever()
    except Exception as exc:  # noqa: BLE001 - report status for health checks.
        AGENT_STATUS["last_error"] = str(exc)
        logger.exception("Background agent crashed: %s", exc)
    finally:
        RUNNER_INSTANCE = None
        AGENT_STATUS["running"] = False


def _ensure_agent_thread() -> None:
    if AGENT_STATUS["running"]:
        return
    worker = threading.Thread(target=_start_agent_loop, daemon=True, name="seedstr-agent-worker")
    worker.start()


def _collect_seedstr_metrics() -> dict[str, Any]:
    settings = load_settings()
    api = SeedstrApiClient(
        base_url=settings.seedstr_base_url,
        api_key=settings.seedstr_api_key,
        timeout_seconds=settings.request_timeout_seconds,
    )
    metrics: dict[str, Any] = {
        "base_url": settings.seedstr_base_url,
        "agent_id": None,
        "jobs_present": None,
        "jobs_submitted": 0,
        "jobs_submitted_source": "default_zero",
        "jobs_completed": None,
        "local_seen_jobs_count": 0,
        "llm_config": {
            "gemini_enabled": bool(settings.gemini_api_key and settings.gemini_models),
            "openai_enabled": bool(settings.openai_api_key and settings.openai_models),
            "gemini_models": settings.gemini_models,
            "openai_models": settings.openai_models,
        },
        "me_summary": None,
        "jobs_summary": None,
        "runner_stats": None,
    }

    try:
        me = api.get_me()
        metrics["agent_id"] = me.get("id")
        jobs_submitted = me.get("jobsSubmitted")
        if jobs_submitted is not None:
            metrics["jobs_submitted"] = jobs_submitted
            metrics["jobs_submitted_source"] = "seedstr_me.jobsSubmitted"
        else:
            metrics["jobs_submitted_source"] = "fallback_local_seen_jobs_count"
        metrics["jobs_completed"] = me.get("jobsCompleted")
        verification = me.get("verification", {}) if isinstance(me.get("verification"), dict) else {}
        metrics["me_summary"] = {
            "id": me.get("id"),
            "name": me.get("name"),
            "verified": verification.get("isVerified"),
            "jobs_completed": me.get("jobsCompleted", 0),
            "jobs_submitted": jobs_submitted,
        }
    except SeedstrApiError as exc:
        metrics["profile_error"] = str(exc)

    try:
        jobs_payload = api.list_jobs(limit=settings.max_jobs_per_cycle, offset=0)
        jobs = jobs_payload.get("jobs", [])
        total = jobs_payload.get("total")
        metrics["jobs_present"] = total if isinstance(total, int) else len(jobs)
        metrics["jobs_summary"] = {
            "count": len(jobs),
            "ids": [str(job.get("id")) for job in jobs if isinstance(job, dict) and job.get("id") is not None],
        }
    except SeedstrApiError as exc:
        metrics["jobs_error"] = str(exc)

    try:
        if settings.state_path.exists():
            state_payload = json.loads(settings.state_path.read_text(encoding="utf-8"))
            seen_jobs = state_payload.get("seen_jobs", [])
            if isinstance(seen_jobs, list):
                metrics["local_seen_jobs_count"] = len(seen_jobs)
                if metrics["jobs_submitted_source"] == "fallback_local_seen_jobs_count":
                    metrics["jobs_submitted"] = len(seen_jobs)
    except Exception:
        metrics["local_seen_jobs_count"] = 0

    if RUNNER_INSTANCE is not None:
        runtime_stats = RUNNER_INSTANCE.get_runtime_stats()
        metrics["runner_stats"] = runtime_stats
        # Prefer runtime submissions because they reflect this live process.
        runtime_submitted = int(runtime_stats.get("submitted_total", 0))
        if runtime_submitted > int(metrics.get("jobs_submitted") or 0):
            metrics["jobs_submitted"] = runtime_submitted
            metrics["jobs_submitted_source"] = "runner_stats.submitted_total"
        if runtime_stats.get("seen_jobs_count", 0) > int(metrics.get("local_seen_jobs_count") or 0):
            metrics["local_seen_jobs_count"] = int(runtime_stats["seen_jobs_count"])

    return metrics


@app.get("/")
def health_check() -> tuple[dict[str, Any], int]:
    _ensure_agent_thread()
    seedstr_metrics = _collect_seedstr_metrics()
    return (
        {
            "ok": True,
            "service": "seedstr-agent-flask-wrapper",
            "app_started_utc": APP_START_UTC,
            "agent": AGENT_STATUS,
            "agent_id": seedstr_metrics.get("agent_id"),
            "jobs_present": seedstr_metrics.get("jobs_present"),
            "jobs_submitted": seedstr_metrics.get("jobs_submitted"),
            "jobs_completed": seedstr_metrics.get("jobs_completed"),
            "local_seen_jobs_count": seedstr_metrics.get("local_seen_jobs_count"),
            "seedstr_metrics": seedstr_metrics,
        },
        200,
    )


@app.get("/healthz")
def healthz() -> tuple[dict[str, Any], int]:
    _ensure_agent_thread()
    seedstr_metrics = _collect_seedstr_metrics()
    return (
        jsonify(
            {
                "ok": True,
                "agent": AGENT_STATUS,
                "agent_id": seedstr_metrics.get("agent_id"),
                "jobs_present": seedstr_metrics.get("jobs_present"),
                "jobs_submitted": seedstr_metrics.get("jobs_submitted"),
                "jobs_completed": seedstr_metrics.get("jobs_completed"),
                "local_seen_jobs_count": seedstr_metrics.get("local_seen_jobs_count"),
                "seedstr_metrics": seedstr_metrics,
            }
        ),
        200,
    )


if __name__ == "__main__":
    _ensure_agent_thread()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

