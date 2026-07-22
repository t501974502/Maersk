# Maersk

## Dremio export automation

This repository includes a GitHub Actions workflow that runs a scheduled Dremio SQL export, uploads the generated CSV as a workflow artifact, and can optionally upload the same CSV to SharePoint or email it as an attachment.

### Default SQL
The checked-in default query is:

```sql
SELECT * FROM "fbm-ecl".views."NAM_OPS"."ops_v_raw_gts_events"
```

The workflow uses `dremio_query.sql` by default. If you set the `DREMIO_SQL` secret, that secret overrides the checked-in SQL.

### Required GitHub repository secrets for Dremio
- `DREMIO_URL`: for example `https://enterprisedremio.maersk-digital.net`
- `DREMIO_AUTH_HEADER` (recommended): the full Authorization header value, such as `_dremio<your-personal-access-token>` or `Bearer <token>`
- Optional fallback secrets if you prefer to build the header from pieces:
  - `DREMIO_AUTH_SCHEME` (default: `_dremio`)
  - `DREMIO_TOKEN`

### Optional Dremio secrets
- `DREMIO_SQL`: optional override for the checked-in SQL
- `DREMIO_PAGE_SIZE`: optional page size for results retrieval. Values above 500 are automatically clamped because Dremio accepts at most 500 rows per results request.

### Optional SharePoint upload secrets
To enable SharePoint upload, add these repository secrets and rerun the workflow:
- `SHAREPOINT_TENANT_ID`
- `SHAREPOINT_CLIENT_ID`
- `SHAREPOINT_CLIENT_SECRET`
- `SHAREPOINT_HOSTNAME`: for example `contoso.sharepoint.com`
- `SHAREPOINT_SITE_PATH`: for example `/sites/Operations`
- Optional:
  - `SHAREPOINT_DRIVE_ID`
  - `SHAREPOINT_DRIVE_NAME` (defaults to `Documents`)
  - `SHAREPOINT_FOLDER_PATH` (for example `Dremio/Exports`)

The Microsoft Entra app used above needs Microsoft Graph application permissions that can upload files to SharePoint, such as `Sites.ReadWrite.All`, with admin consent granted.

### Optional SMTP email secrets
To email the export as an attachment, add these repository secrets:
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_TO` (comma-separated recipients are supported)
- Optional:
  - `SMTP_SECURITY` (`starttls`, `ssl`, or `none`; default: `starttls`)
  - `SMTP_SUBJECT`
  - `SMTP_BODY`

### Output naming
The export file defaults to `ops_v_raw_gts_events_YYYYMMDD_HHMMSS.csv`.

### Schedule
The workflow runs daily at 00:30 UTC, which is 08:30 China Standard Time.

### Manual run
You can also trigger the workflow manually from the Actions tab using `workflow_dispatch`.
