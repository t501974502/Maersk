from __future__ import annotations

import mimetypes
import os
import smtplib
from email import encoders
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path


def env(name: str, required: bool = True, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def find_latest_csv() -> Path:
    explicit = os.getenv("EXPORT_FILE_PATH", "").strip()
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise SystemExit(f"Configured export file does not exist: {path}")
        return path

    output_dir = Path(env("OUTPUT_DIR", required=False, default="output"))
    files = sorted(output_dir.glob("*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(f"No CSV files found in {output_dir}")
    return files[0]


def parse_recipients(value: str) -> list[str]:
    recipients = [item.strip() for item in value.replace(";", ",").split(",")]
    recipients = [item for item in recipients if item]
    if not recipients:
        raise SystemExit("No email recipients configured")
    return recipients


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
    file_path = find_latest_csv()
    message = build_message(file_path)
    send_message(message)
    print(f"Sent email with attachment {file_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
