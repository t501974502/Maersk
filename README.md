# Maersk

## Dremio export automation

This repository includes a GitHub Actions workflow that runs a scheduled Dremio SQL export and uploads the generated CSV as a workflow artifact.

### Required GitHub repository secrets
- `DREMIO_URL`: for example `https://enterprisedremio.maersk-digital.net`
- `DREMIO_SQL`: for example `SELECT * FROM "@patrick.tian@lns.maersk.com".test`
- `DREMIO_AUTH_HEADER` (recommended): the full Authorization header value, such as `_dremio<personal-access-token>` or `Bearer <token>`
- Optional fallback secrets if you prefer to build the header from pieces:
  - `DREMIO_AUTH_SCHEME` (default: `_dremio`)
  - `DREMIO_TOKEN`

### Schedule
The workflow runs daily at 00:00 UTC, which is 08:00 China Standard Time.

### Manual run
You can also trigger the workflow manually from the Actions tab using `workflow_dispatch`.
