# Deployment Guide

The production Compose file is a deployment template. It has not been applied to a cloud account or validated with a live domain, certificate, object bucket, or real credentials.

## Prerequisites

- A Linux host with Docker Engine and Docker Compose plugin.
- A DNS name pointed at the host, with inbound TCP ports 80 and 443 available for Caddy TLS.
- A private S3-compatible bucket and application credentials with object read/write/delete and version-list/delete permissions. Enable server-side encryption and block public access.
- An encrypted backup bucket in a separate account or failure domain, with a 35-day lifecycle for dated backup prefixes.
- A protected PostgreSQL backup/restore plan, encrypted host volumes, log retention rules, and monitoring.

## Configure and start

1. Copy `.env.production.example` to `.env` on the deployment host and replace every placeholder. Set `DATABASE_URL` credentials to match the Postgres variables. Use unique random values for the token, invitation, and metrics secrets. URL-encode reserved characters in the database URL password.
2. Set `LIFEOS_DOMAIN` to the DNS name, `S3_BUCKET` to the private object bucket, and `BACKUP_S3_URI` to a different encrypted bucket/prefix.
3. Before setting `MODEL_PROVIDER=openai`, provide a real `OPENAI_API_KEY`, current provider privacy URL, accurate retention/data disclosure, and current input/output price per million tokens for the configured model. The default zero prices keep external inference unavailable. Keep `MODEL_MAX_COST_PER_CALL_USD` at or below the approved budget.
4. Confirm `.env` is not committed and is readable only by the deployment operator.
5. Check Compose interpolation, then start the stack:

   ```sh
   docker compose -f docker-compose.production.yml config --quiet
   docker compose -f docker-compose.production.yml up --build --detach --wait
   curl --fail https://YOUR_DOMAIN/api/v1/health
   curl --fail https://YOUR_DOMAIN/api/v1/ready
   ```

   Keep `PROCESSING_MODE=worker`. The API process starts a database-backed worker thread for OCR and requested model jobs. The production template runs one Uvicorn process; PostgreSQL lease claims also coordinate jobs if more API processes are added later.

6. Confirm Caddy obtained a certificate; registration is invitation-only by default; `/api/v1/metrics` rejects requests without the metrics token; API and database ports are not publicly exposed; and the bucket rejects anonymous access.
7. Complete the [release checklist](release-checklist.md) and [backup/restore exercise](backup-restore.md) before using real data.

## Bucket requirements

The application uses private object keys and server-side `AES256` encryption for writes. Give the API only the permissions needed to get/put/delete objects, list a bucket and object versions, and remove object versions. Configure the bucket with public access blocked. If versioning is enabled, test that source deletion removes every version and delete marker for that source.

Do not attach a lifecycle rule that expires `.deletion-tombstones/`. Configure a 35-day expiration for date-stamped backup prefixes in the separate backup bucket, and keep tombstones long enough to outlive every restorable database snapshot. Daily full object snapshots may multiply storage costs; estimate the selected bucket size and backup cadence before launch.

## Rollback

Application rollback is safe only when the previous image can read the current schema. Take a database and object snapshot before migrations. Do not roll back a schema migration by restoring an older database without also restoring the matching object snapshot and replaying deletion tombstones. The API runs Alembic migrations before serving traffic and replays deletion tombstones during startup.

This template does not configure cloud IAM, bucket lifecycle, managed PostgreSQL, DNS, alert delivery, or a CI image registry. Those remain operator work and require evidence in the release record.
