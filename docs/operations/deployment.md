# Deployment Guide

The production Compose file is a deployment template. It has not been applied to a cloud account or validated with a live domain, certificate, object bucket, or real credentials.

## Solo local use

One person, one machine, no hosted exposure. Running the API with `.env.example` defaults uses SQLite in `data/lifeos.db`, local object storage in `data/objects`, inline processing, and open registration; TLS, invitation codes, PostgreSQL, and S3 are not required. To use a cloud model, set `MODEL_PROVIDER=openai`, `OPENAI_API_KEY`, non-zero per-million-token prices, and `OPENAI_BASE_URL` when the provider is an OpenAI-compatible gateway rather than OpenAI itself. The checklist and hosting sections below apply only if the instance is exposed to other people.

Back up whichever mode you run:

- **Bare API process**: stop the API, then copy `data/` as one unit so the database and object files stay consistent.
- **Compose stack** (`-p lifeos-iteration -f docker-compose.yml`): dump PostgreSQL and copy the object volume. Stop the stack or accept a short inconsistency window between the two commands.

```powershell
# Database: dump inside the container, then copy the file out (byte-safe in PowerShell).
docker compose -p lifeos-iteration -f docker-compose.yml exec -T db `
  sh -c "pg_dump -Fc -U lifeos lifeos > /tmp/lifeos-backup.dump"
docker cp lifeos-iteration-db-1:/tmp/lifeos-backup.dump .\lifeos-backup.dump

# Objects: archive the volume to the current directory.
docker run --rm -v lifeos-iteration_lifeos_data:/data -v "${PWD}:/backup" alpine `
  tar czf /backup/lifeos-objects.tgz -C /data .
```

Restoring replaces the live database and object volume, so stop the stack first, then copy the files in and run `pg_restore` with `--no-owner` into a freshly created database, extract `lifeos-objects.tgz` into the volume, and start the stack again. Rehearse a restore into a scratch database (`createdb lifeos_restore_check`) before relying on the procedure. Do not run the Compose stack on top of the Codespaces overlay (`.codespaces.yml`) for personal use: that overlay forces `MODEL_PROVIDER=none` so synthetic acceptance never bills a provider.

### Scheduled folder sync

The CLI already reuses the source identity and SHA-256 deduplication, so repeated runs are idempotent. To run a daily folder sync without opening the UI:

```powershell
# Preview the registration without creating a task.
.\scripts\register-scheduled-sync.ps1 -Path C:\Notes -Time 09:00 -WhatIf

# Register for the current Windows account. Windows may prompt for elevation.
.\scripts\register-scheduled-sync.ps1 -Path C:\Notes -Time 09:00

# Remove the task.
.\scripts\register-scheduled-sync.ps1 -Remove
```

The task runs `uv run --project <repo> lifeos sync <path> --yes`, appends output to `data/logs/scheduled-sync.log`, and keeps the API URL from `LIFEOS_API_URL` (default `http://127.0.0.1:8000`). It reads only the selected folder and supported files. The API must be running, and the project checkout with `uv` must remain available; this is an operating-system task, not a hosted service.

### Scheduled weekly review

Set the weekday and local time in the Weekly review page. Scheduled generation runs inside the API worker, so `PROCESSING_MODE=worker` is required; the bare-API development default (`inline`) saves the schedule but does not generate reviews. The Compose development and production stacks use worker mode. Scheduled reviews use only active sources, skip periods with no items, and use the cited template when external consent, provider, or budget is unavailable. Due and overdue reminders are highlighted in the sidebar and in a "Due now" panel.

## Synthetic acceptance in Codespaces

The [Dev Container configuration](../../.devcontainer/devcontainer.json) starts the development Compose stack as `lifeos-iteration`. Keep port 5173 private in the Ports panel. The Web client sends API requests through the same forwarded origin. API and PostgreSQL ports stay available to the Codespace terminal on loopback. [GitHub port forwarding](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace)

Run these checks from the repository root after startup:

```bash
curl --fail http://127.0.0.1:8000/api/v1/ready
uv run pytest -q
(cd web && npm run test:e2e)
LIFEOS_WORKER_TEST_DATABASE_URL=postgresql+psycopg://lifeos:lifeos_dev@127.0.0.1:5432/lifeos uv run pytest -q tests/test_worker_claim.py
uv run python scripts/verify_photo_ocr.py /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc --font-index 2
uv run python scripts/verify_database_restore.py
LIFEOS_BENCHMARK_POSTGRES_URL=postgresql+psycopg://lifeos:lifeos_dev@127.0.0.1:5432/lifeos uv run python scripts/benchmark_mvp.py
```

For the joint database and bucket rehearsal, start the S3 emulator on `127.0.0.1:15666` with `uv run --locked --with 'moto[server]' moto_server -H 127.0.0.1 -p 15666` in a second terminal, then run `uv run python scripts/verify_joint_restore.py`. Set `LIFEOS_REHEARSAL_S3_ENDPOINT` (with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`) to target another S3-compatible server instead. Availability and pause drills are operator actions: set `IMPORTS_ENABLED=false` and recreate the API to confirm imports return 503 `imports_paused` while reads continue, stop the `api` service to confirm the Web origin returns a visible failure and recovers after restart, and build the previous revision's image from a `git worktree` to confirm it starts against the current schema before promoting a rollback.

The worker tests create and remove dedicated PostgreSQL schemas. The restore rehearsal uses a separate database within the development project. Record cloud session evidence against the branch and revision in the [iteration record](../roadmap/next-iteration.md). The real-data beta uses the separately approved environment and release checklist.

## Prerequisites

- A Linux host with Docker Engine and Docker Compose plugin.
- A DNS name pointed at the host, with inbound TCP ports 80 and 443 available for Caddy TLS.
- A private S3-compatible bucket and application credentials with object read/write/delete and version-list/delete permissions. Enable server-side encryption and block public access.
- An encrypted backup bucket in a separate account or failure domain, with a 35-day lifecycle for dated backup prefixes.
- A private encrypted deletion journal bucket outside the primary storage failure domain. Give the API list, read and write access to the journal prefix, and reserve its deletion permissions for a separate operator.
- A protected PostgreSQL backup/restore plan, encrypted host volumes, log retention rules, and monitoring.

## Configure and start

Record the operator handoff before starting hosted acceptance. Use the release record for the following fields and keep credentials in the selected secret store.

| Field | Evidence to record |
| --- | --- |
| Ownership | Deployment owner, backup/restore operator, release reviewer, and approved budget |
| Candidate | Source revision, image identifiers, migration head, and evidence location |
| Network | Staging hostname, certificate issuer, and private database endpoint or network reference |
| Object data | Primary and backup bucket identifiers, encryption, version and expiry policies, and independent deletion-journal location |
| Exposure | Invitation-only setting, synthetic test accounts, external AI state, and authority to enable real-data enrollment |

1. Copy `.env.production.example` to `.env` on the deployment host and replace every placeholder. Set `DATABASE_URL` credentials to match the Postgres variables. Use unique random values for the token, invitation, and metrics secrets. URL-encode reserved characters in the database URL password.
2. Set `LIFEOS_DOMAIN` to the DNS name, `S3_BUCKET` to the private object bucket, `BACKUP_S3_URI` to a different encrypted bucket/prefix, and `S3_DELETION_JOURNAL_BUCKET` to the third bucket. Set the journal region or endpoint overrides if the journal needs a different connection.
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

Keep the journal's `.deletion-tombstones/` prefix available for every restorable backup. Configure a 35-day expiration for dated backup prefixes in the backup bucket. On the first startup with the journal configured, existing tombstones in the primary bucket are copied into the journal before serving requests. Verify the journal's placement and permissions as part of deployment. Estimate storage costs for the selected bucket size and backup cadence.

## Rollback

Application rollback is safe only when the previous image can read the current schema. Take a database and object snapshot before migrations. Do not roll back a schema migration by restoring an older database without also restoring the matching object snapshot and replaying deletion tombstones. The API runs Alembic migrations before serving traffic and replays deletion tombstones during startup.

The v0.5 graph and Q&A work adds revisions `d2f5a8c14e73` (graph tables), `f4a9d7b36c21` (source cloud consent), `b8e2c4d6f901` (question threads and ontology versions), and `d7f1a3b5c902` (insights, agent actions, and plugins). Each revision has a downgrade path; downgrading drops only the tables or columns introduced by that revision and does not restore deleted user data. Prefer forward fixes or a snapshot restore over downgrading in place, and verify `uv run alembic check` reports no model drift before deploying.

This template does not configure cloud IAM, bucket lifecycle, managed PostgreSQL, DNS, alert delivery, or a CI image registry. Those remain operator work and require evidence in the release record.
