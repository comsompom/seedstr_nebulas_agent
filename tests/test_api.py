from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from seedstr_agent.api import SeedstrApiClient, SeedstrApiError


class FakeResponse:
    def __init__(self, ok: bool, status_code: int, payload: object) -> None:
        self.ok = ok
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class ApiClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SeedstrApiClient("https://api.example.com/", " token ")

    def test_request_success(self) -> None:
        with patch("seedstr_agent.api.requests.request", return_value=FakeResponse(True, 200, {"ok": True})) as req:
            data = self.client._request("GET", "/me")
        self.assertEqual(data, {"ok": True})
        called = req.call_args.kwargs
        self.assertEqual(called["url"], "https://api.example.com/me")
        self.assertEqual(called["headers"]["Authorization"], "Bearer token")

    def test_request_invalid_json_raises(self) -> None:
        with patch(
            "seedstr_agent.api.requests.request",
            return_value=FakeResponse(True, 200, ValueError("bad json")),
        ):
            with self.assertRaises(SeedstrApiError):
                self.client._request("GET", "/me")

    def test_request_http_error_raises_message(self) -> None:
        with patch(
            "seedstr_agent.api.requests.request",
            return_value=FakeResponse(False, 400, {"message": "boom"}),
        ):
            with self.assertRaisesRegex(SeedstrApiError, "boom"):
                self.client._request("GET", "/me")

    def test_update_profile_requires_fields(self) -> None:
        with self.assertRaisesRegex(SeedstrApiError, "No profile fields provided"):
            self.client.update_profile()

    def test_upload_file_builds_base64_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "a.txt"
            path.write_text("hello", encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_request(method: str, endpoint: str, payload: dict[str, object] | None = None) -> dict[str, object]:
                captured["method"] = method
                captured["endpoint"] = endpoint
                captured["payload"] = payload or {}
                return {"uploaded": True}

            with patch.object(self.client, "_request", side_effect=fake_request):
                result = self.client.upload_file(path)

        self.assertEqual(result, {"uploaded": True})
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["endpoint"], "/upload")
        payload = captured["payload"]
        assert isinstance(payload, dict)
        files = payload["files"]
        assert isinstance(files, list)
        file_obj = files[0]
        self.assertEqual(file_obj["name"], "a.txt")
        self.assertEqual(base64.b64decode(file_obj["content"]).decode("utf-8"), "hello")

    def test_upload_file_missing_raises(self) -> None:
        with self.assertRaisesRegex(SeedstrApiError, "File not found"):
            self.client.upload_file("missing.zip")

    def test_respond_file_uses_first_successful_payload(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_request(method: str, endpoint: str, payload: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(payload or {})
            if len(calls) == 1:
                raise SeedstrApiError("first failed")
            return {"ok": True}

        upload_result = {"files": [{"url": "https://cdn.example/file.zip"}]}
        with patch.object(self.client, "_request", side_effect=fake_request):
            result = self.client.respond_file("job-1", upload_result, fallback_text="fallback")

        self.assertEqual(result, {"ok": True})
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[0]["responseType"], "FILE")

    def test_respond_file_raises_when_all_attempts_fail(self) -> None:
        def always_fail(method: str, endpoint: str, payload: dict[str, object] | None = None) -> dict[str, object]:
            raise SeedstrApiError("nope")

        with patch.object(self.client, "_request", side_effect=always_fail):
            with self.assertRaisesRegex(SeedstrApiError, "Failed to submit file response"):
                self.client.respond_file("job-1", {"files": [{"url": "x"}]}, fallback_text="fallback")


if __name__ == "__main__":
    unittest.main()
