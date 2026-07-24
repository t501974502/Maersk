from __future__ import annotations

import io
import mimetypes
import os
import smtplib
import zipfile
from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

import requests

CST = timezone(timedelta(hours=8))
MORNING_START = time(7, 30)
MORNING_END = time(9, 30)


def env(name: str, required: bool = True, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def find_latest_local_csv() -> Path | None:
    explicit = os.getenv("EXPORT_FILE_PATH", "").strip()
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise SystemExit(f"Configured export file does not exist: {path}")

    output_dir = Path(env("OUTPUT_DIR", required=False, default="output"))
    files = sorted(output_dir.glob("*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def parse_recipients(value: str) -> list[str]:
    recipients = [item.strip() for item in value.replace(";", ",").split(",")]
    recipients = [item for item in recipients if item]
    if not recipients:
        raise SystemExit("No email recipients configured")
    return recipients


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def in_morning_window_cst(dt_utc: datetime, today_cst: datetime.date) -> bool:
    dt_cst = dt_utc.astimezone(CST)
    return dt_cst.date() == today_cst and MORNING_START <= dt_cst.time() <= MORNING_END


def parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def list_candidate_runs() -> list[dict]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    workflow_name = os.getenv("GITHUB_WORKFLOW", "").strip()
    current_run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    branch = os.getenv("GITHUB_REF_NAME", "").strip() or "main"

    if not token or not repo:
        return []

    owner, name = repo.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/actions/runs"
    response = requests.get(
        url,
        headers=github_headers(token),
        params={"event": "schedule", "branch": branch, "per_page": 100},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    runs = payload.get("workflow_runs", [])
    if not isinstance(runs, list):
        return []

    today_cst = datetime.now(timezone.utc).astimezone(CST).date()
    candidates: list[dict] = []

    for run in runs:
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        if workflow_name and run.get("name") != workflow_name:
            continue
        run_id = str(run.get("id", ""))
        if current_run_id and run_id == current_run_id:
            continue

        created_at = run.get("created_at")
        if not created_at:
            continue

        created_dt_utc = parse_utc(str(created_at))
        if not in_morning_window_cst(created_dt_utc, today_cst):
            continue

        candidates.append(run)

    candidates.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return candidates


def download_artifact_csv_from_run(run_id: int) -> Path | None:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    owner, name = repo.split("/", 1)

    artifacts_url = f"https://api.github.com/repos/{owner}/{name}/actions/runs/{run_id}/artifacts"
    artifacts_response = requests.get(artifacts_url, headers=github_headers(token), timeout=60)
    artifacts_response.raise_for_status()
    artifacts_payload = artifacts_response.json()
    artifacts = artifacts_payload.get("artifacts", [])
    if not isinstance(artifacts, list):
        return None

    artifact = next(
        (
            item
            for item in artifacts
            if item.get("name") == "dremio-export" and not item.get("expired", False)
        ),
        None,
    )
    if not artifact:
        return None

    archive_url = artifact.get("archive_download_url")
    if not archive_url:
        return None

    archive_response = requests.get(archive_url, headers=github_headers(token), timeout=120)
    archive_response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as zf:
        csv_names = sorted([name for name in zf.namelist() if name.lower().endswith(".csv")])
        if not csv_names:
            return None
        selected_name = csv_names[-1]
        data = zf.read(selected_name)

    output_dir = Path(env("OUTPUT_DIR", required=False, default="output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"fallback_{Path(selected_name).name}"
    target.write_bytes(data)
    return target


def find_fallback_csv_from_morning_runs() -> Path | None:
    for run in list_candidate_runs():
        run_id = run.get("id")
        if not run_id:
            continue
        file_path = download_artifact_csv_from_run(int(run_id))
        if file_path:
            print(f"Using fallback artifact from successful run {run_id}: {file_path.name}")
            return file_path
    return None


def pick_csv_for_email() -> Path:
    local = find_latest_local_csv()
    if local:
        return local

    fallback = find_fallback_csv_from_morning_runs()
    if fallback:
        return fallback

    raise SystemExit("No CSV file available for email (no local file and no fallback artifact found).")


def build_message(file_path: Path) -> EmailMessage:
    mail_from = env("SMTP_FROM")
    mail_to = parse_recipients(env("SMTP_TO"))
    subject = os.getenv("SMTP_SUBJECT", f"Dremio export: {file_path.name}").strip()
    body = os.getenv(
        "SMTP_BODY",
        f"Attached is the latest Dremio export file: {file_path.name}",
    ).strip()

    message = EmailMessage()
    message["From"] = mail_from
    message["To"] = ", ".join(mail_to)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message.set_content(body)

    mime_type, _ = mimetypes.guess_type(file_path.name)
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    with file_path.open("rb") as f:
        message.add_attachment(
            f.read(),
            maintype=maintype,
            subtype=subtype,
            filename=file_path.name,
        )

    return message


def send_message(message: EmailMessage) -> None:
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
        server.login(username, password)
        server.send_message(message)


def main() -> int:
    file_path = pick_csv_for_email()
    message = build_message(file_path)
    send_message(message)
    print(f"Sent email with attachment {file_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
