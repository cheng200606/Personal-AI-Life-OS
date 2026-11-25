# Backup and Restore

These scripts use a date-stamped database dump and a matching S3 object snapshot. They require Bash, Docker Compose, AWS CLI, and the production `.env`. Run them on the deployment host or a controlled operator workstation with access to the production bucket and backup bucket.

## Backup

The backup includes a custom-format PostgreSQL dump and the current contents of the primary object bucket. Its manifest identifies the independent deletion journal. The backup destination is a separate private bucket with default encryption, access logging, and a 35-day lifecycle for the production prefix.

```sh
bash scripts/backup-production.sh
```

The script prints the UTC backup ID. Store that ID and the deployed image tag in the operator's change record. Do not store credentials or source content in the change record.

## Restore

Restore requires a selected backup ID in `YYYYMMDDTHHMMSSZ` format. The script pauses the public services, copies the matching bucket snapshot to the configured primary bucket, restores PostgreSQL, and restarts the stack. For simultaneous database and primary bucket loss, configure the replacement primary bucket but keep the independently preserved journal. The API reads that journal and replays deletions before becoming healthy.

```sh
bash scripts/restore-production.sh 20261125T120000Z
```

After restore, confirm health/readiness, login, timeline and archive behavior using a synthetic account. Confirm each known deleted account/source remains absent and its object prefix has no readable versions. Review logs for deletion replay and migration errors. Record recovery time and data-loss window.

For a database-only rehearsal on a disposable development Compose project, start the API and database with `docker compose -p lifeos-iteration up --build --detach --wait api` and run `uv run python scripts/verify_database_restore.py` from the repository root. It restores into a freshly created test database and checks both a deletion made after the snapshot and an untouched object against the live development object store.

## Important recovery boundary

The production API requires an independent live deletion journal. It records requests before carrying out deletion, and recovery uses the same journal to replay requests recorded after the selected backup. Before accepting real data, verify the journal's failure-domain separation and retain it for the entire backup recovery window. If the journal was unavailable during the incident, reconcile it before restoring access.

For an isolated rehearsal with PostgreSQL and a local S3 emulator, start the development database with `docker compose -p lifeos-iteration up --detach --wait db`. Run `uv run --locked --with 'moto[server]' moto_server -H 127.0.0.1 -p 15666` in one terminal and `uv run python scripts/verify_joint_restore.py` in another. The rehearsal makes post-snapshot source and account deletions, removes the synthetic primary bucket and database, restores both into replacements, and checks deleted and retained objects before reporting results. The exercise uses the [Moto emulator](https://docs.getmoto.org/en/latest/docs/server_mode.html).

The sample 35-day backup expiry is an operator policy. It is not imposed by the API or scripts. Do not report deletion as complete from all backups until the published retention window has elapsed and the configured lifecycle has been verified.
