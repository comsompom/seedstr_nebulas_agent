from __future__ import annotations

import argparse
import json
import os
from typing import Any

import requests


DEFAULT_BASE_URL = "https://www.seedstr.io/api/v2"


def _request_json(base_url: str, endpoint: str, timeout_seconds: int, api_key: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = requests.get(f"{base_url.rstrip('/')}{endpoint}", headers=headers, timeout=timeout_seconds)
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Non-JSON response from {endpoint}: HTTP {response.status_code}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected response shape from {endpoint}: expected JSON object")
    return payload


def _fetch_with_fallback(base_url: str, name: str, endpoints: list[str], timeout_seconds: int, api_key: str | None = None) -> tuple[str, dict[str, Any]]:
    last_error: Exception | None = None
    for endpoint in endpoints:
        try:
            return endpoint, _request_json(base_url, endpoint, timeout_seconds, api_key=api_key)
        except Exception as exc:  # noqa: BLE001 - this is a user-facing probe script.
            last_error = exc
    raise RuntimeError(f"Could not fetch {name}. Tried {endpoints}. Last error: {last_error}")


def _extract_first_job_id(payload: dict[str, Any]) -> str | None:
    jobs_value = payload.get("jobs")
    if isinstance(jobs_value, list) and jobs_value:
        first = jobs_value[0]
        if isinstance(first, dict) and first.get("id") is not None:
            return str(first["id"])

    data_value = payload.get("data")
    if isinstance(data_value, list) and data_value:
        first = data_value[0]
        if isinstance(first, dict) and first.get("id") is not None:
            return str(first["id"])

    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check Seedstr leaderboard, stats, list-jobs, and get-job endpoints."
    )
    parser.add_argument("--base-url", default=os.getenv("SEEDSTR_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--leaderboard-out", default="leaderboard_response.json")
    parser.add_argument("--stats-out", default="stats_response.json")
    parser.add_argument("--list-jobs-out", default="list_jobs_response.json")
    parser.add_argument("--job-detail-out", default="job_detail_response.json")
    parser.add_argument("--combined-out", default="public_endpoints_response.json")
    parser.add_argument("--job-id", default="", help="Optional job id for GET /jobs/{id}.")
    parser.add_argument(
        "--api-key",
        default=os.getenv("SEEDSTR_API_KEY", "").strip() or None,
        help="Optional API key. Jobs endpoints usually require a verified agent key.",
    )
    args = parser.parse_args()

    leaderboard_candidates = ["/leaderboard"]
    stats_candidates = ["/stats", "/platform-stats"]
    list_jobs_candidates = ["/jobs?limit=20&offset=0", "/jobs"]

    leaderboard_endpoint, leaderboard_payload = _fetch_with_fallback(
        args.base_url,
        name="leaderboard",
        endpoints=leaderboard_candidates,
        timeout_seconds=args.timeout_seconds,
        api_key=args.api_key,
    )
    stats_endpoint, stats_payload = _fetch_with_fallback(
        args.base_url,
        name="platform stats",
        endpoints=stats_candidates,
        timeout_seconds=args.timeout_seconds,
        api_key=args.api_key,
    )
    list_jobs_endpoint, list_jobs_payload = _fetch_with_fallback(
        args.base_url,
        name="list jobs",
        endpoints=list_jobs_candidates,
        timeout_seconds=args.timeout_seconds,
        api_key=args.api_key,
    )

    selected_job_id = args.job_id.strip() or _extract_first_job_id(list_jobs_payload)
    if selected_job_id:
        job_detail_endpoint, job_detail_payload = _fetch_with_fallback(
            args.base_url,
            name="get job",
            endpoints=[f"/jobs/{selected_job_id}"],
            timeout_seconds=args.timeout_seconds,
            api_key=args.api_key,
        )
    else:
        job_detail_endpoint = ""
        job_detail_payload = {
            "skipped": True,
            "reason": "No job id provided and no jobs were returned from list jobs.",
        }

    print(f"Leaderboard endpoint: {leaderboard_endpoint}")
    print(json.dumps(leaderboard_payload, indent=2, ensure_ascii=True))
    print()
    print(f"Stats endpoint: {stats_endpoint}")
    print(json.dumps(stats_payload, indent=2, ensure_ascii=True))
    print()
    print(f"List Jobs endpoint: {list_jobs_endpoint}")
    print(json.dumps(list_jobs_payload, indent=2, ensure_ascii=True))
    print()
    if job_detail_endpoint:
        print(f"Get Job endpoint: {job_detail_endpoint}")
    else:
        print("Get Job endpoint: skipped")
    print(json.dumps(job_detail_payload, indent=2, ensure_ascii=True))

    with open(args.leaderboard_out, "w", encoding="utf-8") as leaderboard_file:
        json.dump(leaderboard_payload, leaderboard_file, indent=2, ensure_ascii=True)
    with open(args.stats_out, "w", encoding="utf-8") as stats_file:
        json.dump(stats_payload, stats_file, indent=2, ensure_ascii=True)
    with open(args.list_jobs_out, "w", encoding="utf-8") as list_jobs_file:
        json.dump(list_jobs_payload, list_jobs_file, indent=2, ensure_ascii=True)
    with open(args.job_detail_out, "w", encoding="utf-8") as job_detail_file:
        json.dump(job_detail_payload, job_detail_file, indent=2, ensure_ascii=True)
    with open(args.combined_out, "w", encoding="utf-8") as combined_file:
        json.dump(
            {
                "leaderboard": {
                    "endpoint": leaderboard_endpoint,
                    "response": leaderboard_payload,
                },
                "stats": {
                    "endpoint": stats_endpoint,
                    "response": stats_payload,
                },
                "list_jobs": {
                    "endpoint": list_jobs_endpoint,
                    "response": list_jobs_payload,
                },
                "get_job": {
                    "endpoint": job_detail_endpoint,
                    "response": job_detail_payload,
                    "job_id": selected_job_id,
                },
            },
            combined_file,
            indent=2,
            ensure_ascii=True,
        )
    print()
    print(
        "Saved: "
        f"{args.leaderboard_out}, {args.stats_out}, {args.list_jobs_out}, "
        f"{args.job_detail_out}, {args.combined_out}"
    )


if __name__ == "__main__":
    main()
