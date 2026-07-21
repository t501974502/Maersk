from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_SCOPE = "https://graph.microsoft.com/.default"
REQUEST_TIMEOUT_SECONDS = int(os.getenv("GRAPH_REQUEST_TIMEOUT_SECONDS", "60"))


def env(name: str, required: bool = True, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def get_access_token() -> str:
    tenant_id = env("SHAREPOINT_TENANT_ID")
    client_id = env("SHAREPOINT_CLIENT_ID")
    client_secret = env("SHAREPOINT_CLIENT_SECRET")

    response = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": TOKEN_SCOPE,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise RuntimeError(f"Access token not returned: {payload}")
    return str(access_token)


def graph_request(
    method: str,
    url: str,
    token: str,
    *,
    expected_statuses: tuple[int, ...] = (200,),
    **kwargs: Any,
) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
    if response.status_code not in expected_statuses:
        response.raise_for_status()
    return response


def normalize_site_path(path: str) -> str:
    cleaned = path.strip()
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return cleaned.rstrip("/")


def normalize_folder_path(path: str) -> str:
    return path.strip().strip("/")


def get_site_id(token: str) -> str:
    hostname = env("SHAREPOINT_HOSTNAME")
    site_path = normalize_site_path(env("SHAREPOINT_SITE_PATH"))
    response = graph_request(
        "GET",
        f"{GRAPH_BASE_URL}/sites/{hostname}:{site_path}",
        token,
    )
    payload = response.json()
    site_id = payload.get("id")
    if not site_id:
        raise RuntimeError(f"SharePoint site id not returned: {payload}")
    return str(site_id)


def get_drive_id(site_id: str, token: str) -> str:
    drive_id = os.getenv("SHAREPOINT_DRIVE_ID", "").strip()
    if drive_id:
        return drive_id

    requested_name = os.getenv("SHAREPOINT_DRIVE_NAME", "Documents").strip().lower()
    response = graph_request("GET", f"{GRAPH_BASE_URL}/sites/{site_id}/drives", token)
    payload = response.json()
    drives = payload.get("value", [])
    if not isinstance(drives, list) or not drives:
        raise RuntimeError(f"No drives found for SharePoint site {site_id}: {payload}")

    for drive in drives:
        if str(drive.get("name", "")).lower() == requested_name:
            matched_drive_id = drive.get("id")
            if matched_drive_id:
                return str(matched_drive_id)

    if len(drives) == 1 and drives[0].get("id"):
        return str(drives[0]["id"])

    available = ", ".join(str(drive.get("name", "<unnamed>")) for drive in drives)
    raise RuntimeError(
        f"Could not find SharePoint drive named '{requested_name}'. Available drives: {available}"
    )


def item_exists(drive_id: str, item_path: str, token: str) -> bool:
    encoded_path = quote(item_path, safe="/")
    response = graph_request(
        "GET",
        f"{GRAPH_BASE_URL}/drives/{drive_id}/root:/{encoded_path}",
        token,
        expected_statuses=(200, 404),
    )
    return response.status_code == 200


def ensure_folder(drive_id: str, folder_path: str, token: str) -> None:
    normalized = normalize_folder_path(folder_path)
    if not normalized:
        return

    parts = [part for part in normalized.split("/") if part]
    current_parts: list[str] = []

    for part in parts:
        current_parts.append(part)
        current_path = "/".join(current_parts)
        if item_exists(drive_id, current_path, token):
            continue

        parent_path = "/".join(current_parts[:-1])
        if parent_path:
            parent_url = f"{GRAPH_BASE_URL}/drives/{drive_id}/root:/{quote(parent_path, safe='/')}:/children"
        else:
            parent_url = f"{GRAPH_BASE_URL}/drives/{drive_id}/root/children"

        graph_request(
            "POST",
            parent_url,
            token,
            expected_statuses=(200, 201),
            headers={"Content-Type": "application/json"},
            json={
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "replace",
            },
        )


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


def upload_file(drive_id: str, folder_path: str, file_path: Path, token: str) -> str:
    ensure_folder(drive_id, folder_path, token)

    target_parts = [part for part in [normalize_folder_path(folder_path), file_path.name] if part]
    target_path = "/".join(target_parts)
    encoded_path = quote(target_path, safe="/")

    with file_path.open("rb") as f:
        response = graph_request(
            "PUT",
            f"{GRAPH_BASE_URL}/drives/{drive_id}/root:/{encoded_path}:/content",
            token,
            expected_statuses=(200, 201),
            headers={"Content-Type": "text/csv"},
            data=f,
        )

    payload = response.json()
    web_url = payload.get("webUrl")
    if not web_url:
        raise RuntimeError(f"SharePoint upload succeeded but webUrl was missing: {payload}")
    return str(web_url)


def main() -> int:
    token = get_access_token()
    site_id = get_site_id(token)
    drive_id = get_drive_id(site_id, token)
    folder_path = os.getenv("SHAREPOINT_FOLDER_PATH", "").strip()
    file_path = find_latest_csv()
    web_url = upload_file(drive_id, folder_path, file_path, token)

    print(f"Uploaded {file_path.name} to SharePoint")
    print(f"SharePoint URL: {web_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
