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
        if AGENT_STATUS["started"]:
            return
        AGENT_STATUS["started"] = True
        AGENT_STATUS["running"] = True
        AGENT_STATUS["last_started_utc"] = datetime.now(timezone.utc).isoformat()

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
    if AGENT_STATUS["started"]:
        return
    worker = threading.Thread(target=_start_agent_loop, daemon=True, name="seedstr-agent-worker")
    worker.start()


@app.get("/")
def health_check() -> tuple[dict[str, Any], int]:
    _ensure_agent_thread()
    return (
        {
            "ok": True,
            "service": "seedstr-agent-flask-wrapper",
            "app_started_utc": APP_START_UTC,
            "agent": AGENT_STATUS,
        },
        200,
    )


@app.get("/healthz")
def healthz() -> tuple[dict[str, Any], int]:
    return jsonify({"ok": True, "agent": AGENT_STATUS}), 200


if __name__ == "__main__":
    _ensure_agent_thread()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

