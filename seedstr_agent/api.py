from __future__ import annotations

import base64
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import requests


class SeedstrApiError(RuntimeError):
    pass


class SeedstrApiClient:
    def __init__(self, base_url: str, api_key: str = "", timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    def set_api_key(self, api_key: str) -> None:
        self.api_key = api_key.strip()

    def _request(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.request(
                method=method,
                url=f"{self.base_url}{endpoint}",
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise SeedstrApiError(f"HTTP request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise SeedstrApiError(f"Invalid JSON from API ({response.status_code})") from exc

        if not response.ok:
            message = data.get("message") or data.get("error") or f"HTTP {response.status_code}"
            raise SeedstrApiError(str(message))

        return data

    def register(self, wallet_address: str, owner_url: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"walletAddress": wallet_address}
        if owner_url:
            body["ownerUrl"] = owner_url
        return self._request("POST", "/register", body)

    def verify(self) -> dict[str, Any]:
        return self._request("POST", "/verify")

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/me")

    def update_profile(
        self,
        *,
        name: str | None = None,
        bio: str | None = None,
        profile_picture: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if bio is not None:
            payload["bio"] = bio
        if profile_picture is not None:
            payload["profilePicture"] = profile_picture
        if not payload:
            raise SeedstrApiError("No profile fields provided")
        return self._request("PATCH", "/me", payload)

    def update_skills(self, skills: list[str]) -> dict[str, Any]:
        cleaned = [item.strip() for item in skills if item.strip()]
        return self._request("PATCH", "/me", {"skills": cleaned})

    def list_skills(self) -> dict[str, Any]:
        return self._request("GET", "/skills")

    def list_jobs(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return self._request("GET", f"/jobs?limit={limit}&offset={offset}")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}")

    def accept_job(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/accept")

    def decline_job(self, job_id: str, reason: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/decline", {"reason": reason})

    def respond_text(self, job_id: str, content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/jobs/{job_id}/respond",
            {"content": content, "responseType": "TEXT"},
        )

    @staticmethod
    def _extract_upload_file_candidates(upload_result: dict[str, Any]) -> list[dict[str, Any]]:
        files = upload_result.get("files")
        if isinstance(files, list):
            return [item for item in files if isinstance(item, dict)]

        file_obj = upload_result.get("file")
        if isinstance(file_obj, dict):
            return [file_obj]

        return []

    @staticmethod
    def _extract_upload_reference_strings(upload_result: dict[str, Any]) -> list[str]:
        keys = ("url", "fileUrl", "cdnUrl", "signedUrl", "path", "key", "id", "fileId")
        refs: list[str] = []

        def add_ref(value: Any) -> None:
            if value is None:
                return
            text = str(value).strip()
            if text and text not in refs:
                refs.append(text)

        for key in keys:
            add_ref(upload_result.get(key))

        for item in SeedstrApiClient._extract_upload_file_candidates(upload_result):
            for key in keys:
                add_ref(item.get(key))

        return refs

    def respond_file(self, job_id: str, upload_result: dict[str, Any], fallback_text: str) -> dict[str, Any]:
        endpoint = f"/jobs/{job_id}/respond"
        file_items = self._extract_upload_file_candidates(upload_result)
        refs = self._extract_upload_reference_strings(upload_result)

        attempts: list[dict[str, Any]] = []
        # Prefer a canonical file payload shape: FILE response + string content.
        for ref in refs:
            attempts.append({"responseType": "FILE", "content": ref})

        # Legacy fallback for APIs expecting uploaded file objects.
        if not attempts and file_items:
            attempts.append({"responseType": "FILE", "files": file_items})

        # Last resort if the platform rejects every FILE shape.
        attempts.append({"responseType": "TEXT", "content": fallback_text})

        last_error: SeedstrApiError | None = None
        for payload in attempts:
            retries = 0
            try:
                return self._request("POST", endpoint, payload)
            except SeedstrApiError as exc:
                last_error = exc
                # Some payload shapes trigger strict schema errors; keep trying safer shapes.
                if self._is_invalid_string_input_error(exc):
                    continue
                retry_after = self._retry_after_seconds(exc)
                if retry_after is not None and retries == 0 and retry_after <= 20:
                    retries += 1
                    time.sleep(retry_after + 1)
                    try:
                        return self._request("POST", endpoint, payload)
                    except SeedstrApiError as retry_exc:
                        last_error = retry_exc
                # Do not keep trying alternate payload shapes when rate-limited.
                if retry_after is not None:
                    break

        raise SeedstrApiError(f"Failed to submit file response for job {job_id}: {last_error}")

    @staticmethod
    def _retry_after_seconds(error: SeedstrApiError) -> int | None:
        message = str(error)
        if "too many requests" not in message.lower():
            return None
        match = re.search(r"try again in\s+(\d+)\s+seconds", message, flags=re.IGNORECASE)
        if not match:
            return 1
        return int(match.group(1))

    @staticmethod
    def _is_invalid_string_input_error(error: SeedstrApiError) -> bool:
        message = str(error).lower()
        return "expected string, received undefined" in message or (
            "invalid input" in message and "expected string" in message
        )

    def upload_file(self, file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise SeedstrApiError(f"File not found: {path}")

        mime_type, _ = mimetypes.guess_type(path.name)
        file_type = mime_type or "application/octet-stream"
        raw = path.read_bytes()
        encoded = base64.b64encode(raw).decode("utf-8")

        payload = {
            "files": [
                {
                    "name": path.name,
                    "content": encoded,
                    "type": file_type,
                }
            ]
        }
        return self._request("POST", "/upload", payload)

