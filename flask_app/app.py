from __future__ import annotations

import logging
import os
import sys
import threading
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

app = Flask(__name__)


def _start_agent_loop() -> None:
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
        runner.run_forever()
    except Exception as exc:  # noqa: BLE001 - report status for health checks.
        AGENT_STATUS["last_error"] = str(exc)
        logger.exception("Background agent crashed: %s", exc)
    finally:
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
        "agent_id": None,
        "jobs_present": None,
        "jobs_submitted": None,
    }

    try:
        me = api.get_me()
        metrics["agent_id"] = me.get("id")
        metrics["jobs_submitted"] = me.get("jobsCompleted", me.get("jobsSubmitted", 0))
    except SeedstrApiError as exc:
        metrics["profile_error"] = str(exc)

    try:
        jobs_payload = api.list_jobs(limit=settings.max_jobs_per_cycle, offset=0)
        jobs = jobs_payload.get("jobs", [])
        total = jobs_payload.get("total")
        metrics["jobs_present"] = total if isinstance(total, int) else len(jobs)
    except SeedstrApiError as exc:
        metrics["jobs_error"] = str(exc)

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
                "seedstr_metrics": seedstr_metrics,
            }
        ),
        200,
    )


if __name__ == "__main__":
    _ensure_agent_thread()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

