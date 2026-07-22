from __future__ import annotations

import csv
import mimetypes
import os
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

MAX_PAGE_SIZE = 500
PAGE_SIZE = min(int(os.getenv("DREMIO_PAGE_SIZE", str(MAX_PAGE_SIZE))), MAX_PAGE_SIZE)
JOB_POLL_SECONDS = float(os.getenv("DREMIO_JOB_POLL_SECONDS", "5"))
JOB_TIMEOUT_SECONDS = int(os.getenv("DREMIO_JOB_TIMEOUT_SECONDS", "1800"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("DREMIO_REQUEST_TIMEOUT_SECONDS", "60"))
DEFAULT_OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
DEFAULT_ENV_FILE = os.getenv("REPORT_ENV_FILE", ".env").strip() or ".env"


def env(name: str, required: bool = True, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def load_dotenv_file(path: str) -> None:
    dotenv = Path(path)
    if not dotenv.is_file():
        return

    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_sql() -> str:
    sql = os.getenv("DREMIO_SQL", "").strip()
    if sql:
        return sql

    sql_file = os.getenv("DREMIO_SQL_FILE", "dremio_query.sql").strip()
    path = Path(sql_file)
    if not path.is_file():
        raise SystemExit(
            "Missing DREMIO_SQL and SQL file was not found. Set DREMIO_SQL or commit the SQL file."
        )

    sql = path.read_text(encoding="utf-8").strip()
    if not sql:
        raise SystemExit(f"SQL file is empty: {path}")
    return sql


def build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}

    auth_header = os.getenv("DREMIO_AUTH_HEADER", "").strip()
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


def wait_for_job(base_url: str, job_id: str, headers: dict[str, str]) -> None:
    start_time = time.time()
    deadline = start_time + JOB_TIMEOUT_SECONDS
    last_state = None

    while True:
        payload = get_job_state(base_url, job_id, headers)
        state = str(payload.get("jobState", "")).upper()
        if state != last_state:
            elapsed = int(time.time() - start_time)
            print(f"Job {job_id} state: {state or 'UNKNOWN'} after {elapsed}s")
            last_state = state
        if state == "COMPLETED":
            return
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


def parse_recipients(value: str) -> list[str]:
    recipients = [item.strip() for item in value.replace(";", ",").split(",")]
    recipients = [item for item in recipients if item]
    if not recipients:
        raise SystemExit("No email recipients configured")
    return recipients


def build_email(file_path: Path) -> EmailMessage:
    mail_from = env("SMTP_FROM")
    mail_to = parse_recipients(env("SMTP_TO"))
    subject = os.getenv("SMTP_SUBJECT", f"Dremio report: {file_path.name}").strip()
    body = os.getenv(
        "SMTP_BODY",
        f"Attached is the latest Dremio report file: {file_path.name}",
    ).strip()

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)

    mime_type, _ = mimetypes.guess_type(file_path.name)
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    with file_path.open("rb") as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=file_path.name)

    return msg


def send_email(msg: EmailMessage) -> None:
    host = env("SMTP_HOST")
    port = int(env("SMTP_PORT"))
    username = env("SMTP_USERNAME")
    password = env("SMTP_PASSWORD")
    security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()

    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port)
    else:
        server = smtplib.SMTP(host, port)

    with server:
        server.ehlo()
        if security in {"starttls", "tls"}:
            server.starttls()
            server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(msg)


def main() -> int:
    load_dotenv_file(DEFAULT_ENV_FILE)

    base_url = env("DREMIO_URL").rstrip("/")
    sql = load_sql()
    output_dir = Path(env("OUTPUT_DIR", required=False, default=str(DEFAULT_OUTPUT_DIR)))
    output_basename = os.getenv("OUTPUT_BASENAME", "dremio_export").strip() or "dremio_export"
    output_name = os.getenv(
        "OUTPUT_FILENAME",
        f"{output_basename}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
    )
    output_path = output_dir / output_name

    headers = build_headers()
    job_id = submit_query(base_url, sql, headers)
    print(f"Submitted Dremio job: {job_id}")

    wait_for_job(base_url, job_id, headers)
    columns, rows = fetch_rows(base_url, job_id, headers)
    write_csv(output_path, columns, rows)
    print(f"Exported {len(rows)} rows to {output_path}")

    email_msg = build_email(output_path)
    send_email(email_msg)
    print(f"Sent email with attachment {output_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
