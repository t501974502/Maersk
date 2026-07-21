from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

PAGE_SIZE = int(os.getenv("DREMIO_PAGE_SIZE", "5000"))
JOB_POLL_SECONDS = float(os.getenv("DREMIO_JOB_POLL_SECONDS", "2"))
JOB_TIMEOUT_SECONDS = int(os.getenv("DREMIO_JOB_TIMEOUT_SECONDS", "600"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("DREMIO_REQUEST_TIMEOUT_SECONDS", "60"))


def env(name: str, required: bool = True, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def strip_outer_quotes(value: str) -> str:
    return value.strip().strip("\"'")


def normalize_authorization_value(value: str) -> str:
    normalized = strip_outer_quotes(value)
    if ":" in normalized and normalized.lower().startswith("authorization:"):
        normalized = normalized.split(":", 1)[1].strip()
    elif "=" in normalized and normalized.lower().startswith("authorization="):
        normalized = normalized.split("=", 1)[1].strip()
    return strip_outer_quotes(normalized)


def build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}

    auth_header = normalize_authorization_value(os.getenv("DREMIO_AUTH_HEADER", ""))
    if auth_header:
        headers["Authorization"] = auth_header
        return headers

    token = os.getenv("DREMIO_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Set DREMIO_AUTH_HEADER, or set DREMIO_TOKEN with DREMIO_AUTH_SCHEME (default: _dremio)."
        )

    scheme = os.getenv("DREMIO_AUTH_SCHEME", "_dremio").strip()
    if not scheme:
        headers["Authorization"] = token
    elif scheme == "_dremio" or scheme.endswith(" "):
        headers["Authorization"] = f"{scheme}{token}"
    else:
        headers["Authorization"] = f"{scheme} {token}"
    return headers


def submit_query(base_url: str, sql: str, headers: dict[str, str]) -> str:
    response = requests.post(
        f"{base_url}/api/v3/sql",
        headers=headers,
        json={"sql": sql},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    job_id = payload.get("id") or payload.get("jobId") or payload.get("job_id")
    if not job_id:
        raise RuntimeError(f"Dremio did not return a job id: {payload}")
    return str(job_id)


def get_job_state(base_url: str, job_id: str, headers: dict[str, str]) -> dict[str, Any]:
    response = requests.get(
        f"{base_url}/api/v3/job/{job_id}",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def wait_for_job(base_url: str, job_id: str, headers: dict[str, str]) -> dict[str, Any]:
    deadline = time.time() + JOB_TIMEOUT_SECONDS
    while True:
        payload = get_job_state(base_url, job_id, headers)
        state = str(payload.get("jobState", "")).upper()
        if state == "COMPLETED":
            return payload
        if state in {"FAILED", "CANCELED", "CANCELLED"}:
            raise RuntimeError(f"Dremio job {job_id} ended with state {state}: {payload}")
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for Dremio job {job_id} to complete")
        time.sleep(JOB_POLL_SECONDS)


def fetch_rows(base_url: str, job_id: str, headers: dict[str, str]) -> tuple[list[str], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    schema: list[str] = []
    offset = 0

    while True:
        response = requests.get(
            f"{base_url}/api/v3/job/{job_id}/results",
            headers=headers,
            params={"offset": offset, "limit": PAGE_SIZE},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        if not schema:
            raw_schema = payload.get("schema", [])
            if raw_schema and isinstance(raw_schema, list):
                schema = [column.get("name", "") for column in raw_schema if isinstance(column, dict)]
                schema = [name for name in schema if name]

        batch = payload.get("rows", [])
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected rows payload from Dremio: {payload}")
        if not batch:
            break

        for row in batch:
            if isinstance(row, dict):
                rows.append(row)
            else:
                raise RuntimeError(f"Unexpected row format from Dremio: {row!r}")

        offset += len(batch)
        if len(batch) < PAGE_SIZE:
            break

    if not schema and rows:
        schema = list(rows[0].keys())

    return schema, rows


def write_csv(output_path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    base_url = env("DREMIO_URL").rstrip("/")
    sql = env("DREMIO_SQL")
    output_dir = Path(env("OUTPUT_DIR", required=False, default="output"))
    output_name = os.getenv(
        "OUTPUT_FILENAME",
        f"dremio_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
    )
    output_path = output_dir / output_name

    headers = build_headers()
    job_id = submit_query(base_url, sql, headers)
    print(f"Submitted Dremio job: {job_id}")

    wait_for_job(base_url, job_id, headers)
    columns, rows = fetch_rows(base_url, job_id, headers)
    write_csv(output_path, columns, rows)

    print(f"Exported {len(rows)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
