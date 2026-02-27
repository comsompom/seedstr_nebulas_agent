from __future__ import annotations

import json
import logging
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from seedstr_agent.config import Settings
from seedstr_agent.runner import AgentRunner


class FakeApi:
    def __init__(self) -> None:
        self.jobs_payload: dict[str, object] = {"jobs": []}
        self.accepted: list[str] = []
        self.uploaded: list[Path] = []
        self.responded: list[tuple[str, dict[str, object], str]] = []

    def list_jobs(self, limit: int, offset: int) -> dict[str, object]:
        return self.jobs_payload

    def accept_job(self, job_id: str) -> dict[str, object]:
        self.accepted.append(job_id)
        return {"ok": True}

    def upload_file(self, path: str | Path) -> dict[str, object]:
        path_obj = Path(path)
        self.uploaded.append(path_obj)
        return {"files": [{"url": f"https://cdn.example/{path_obj.name}"}]}

    def respond_file(self, job_id: str, upload_result: dict[str, object], fallback_text: str) -> dict[str, object]:
        self.responded.append((job_id, upload_result, fallback_text))
        return {"ok": True}


class FakeLLM:
    def __init__(self, answer: str = "answer", model: str = "openai:test") -> None:
        self.answer = answer
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def generate(self, prompt: str, system_prompt: str) -> tuple[str, str]:
        self.calls.append((prompt, system_prompt))
        return self.answer, self.model


class RunnerTests(unittest.TestCase):
    def _settings(self, state_path: Path) -> Settings:
        return Settings(
            seedstr_base_url="https://api.example.com",
            seedstr_api_key="key",
            solana_wallet_address="wallet",
            seedstr_owner_url=None,
            gemini_api_key="",
            openai_api_key="",
            gemini_models=[],
            openai_models=[],
            poll_interval_seconds=1,
            min_budget_usd=1.0,
            max_jobs_per_cycle=10,
            request_timeout_seconds=30,
            log_level="INFO",
            state_path=state_path,
        )

    def _runner(self, tmp: str) -> AgentRunner:
        logger = logging.getLogger("runner-tests")
        logger.setLevel(logging.DEBUG)
        state_path = Path(tmp) / ".agent_state.json"
        with patch("seedstr_agent.runner.LLMFailoverClient") as llm_cls:
            llm_cls.return_value = FakeLLM()
            return AgentRunner(settings=self._settings(state_path), logger=logger)

    def test_run_once_no_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(tmp)
            fake_api = FakeApi()
            runner.api = fake_api
            runner.run_once()
            self.assertEqual(fake_api.responded, [])

    def test_skips_low_budget_and_marks_seen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(tmp)
            fake_api = FakeApi()
            fake_api.jobs_payload = {"jobs": [{"id": "1", "budget": 0.1, "prompt": "ignored"}]}
            runner.api = fake_api

            runner.run_once()

            state = json.loads(runner.settings.state_path.read_text(encoding="utf-8"))
            self.assertIn("1", state["seen_jobs"])
            self.assertEqual(fake_api.responded, [])

    def test_processes_standard_job_and_submits_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(tmp)
            fake_api = FakeApi()
            fake_api.jobs_payload = {"jobs": [{"id": "2", "budget": 2.0, "prompt": "solve this"}]}
            fake_llm = FakeLLM(answer="final output", model="openai:model")
            runner.api = fake_api
            runner.llm = fake_llm

            runner.run_once()

            self.assertEqual(len(fake_api.uploaded), 1)
            uploaded_name = fake_api.uploaded[0].name
            self.assertTrue(uploaded_name.endswith(".zip"))
            self.assertEqual(fake_api.responded[0][0], "2")
            self.assertEqual(fake_api.responded[0][2], "final output")

    def test_accepts_swarm_before_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(tmp)
            fake_api = FakeApi()
            fake_api.jobs_payload = {
                "jobs": [{"id": "3", "jobType": "SWARM", "budgetPerAgent": 3.0, "prompt": "swarm task"}]
            }
            runner.api = fake_api
            runner.llm = FakeLLM()

            runner.run_once()

            self.assertEqual(fake_api.accepted, ["3"])
            self.assertEqual(len(fake_api.responded), 1)

    def test_create_submission_archive_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "out.zip"
            AgentRunner._create_submission_archive(
                archive_path=archive,
                job_id="job-x",
                prompt="what is up",
                answer="all good",
                model_name="openai:test",
            )

            self.assertTrue(archive.exists())
            with zipfile.ZipFile(archive, "r") as zf:
                names = set(zf.namelist())
                self.assertEqual(names, {"response.txt", "prompt.txt", "metadata.json"})
                self.assertEqual(zf.read("response.txt").decode("utf-8"), "all good\n")
                metadata = json.loads(zf.read("metadata.json").decode("utf-8"))
                self.assertEqual(metadata["job_id"], "job-x")
                self.assertEqual(metadata["model"], "openai:test")


if __name__ == "__main__":
    unittest.main()
