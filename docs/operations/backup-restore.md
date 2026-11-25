# Backup and Restore

These scripts use a date-stamped database dump and a matching S3 object snapshot. They require Bash, Docker Compose, AWS CLI, and the production `.env`. Run them on the deployment host or a controlled operator workstation with access to the production bucket and backup bucket.

## Backup

The backup includes a custom-format PostgreSQL dump and the current contents of the configured object bucket, including the deletion-tombstone prefix. The backup destination must be a separate private bucket with default encryption, access logging, and a 35-day lifecycle for the production prefix.

```sh
bash scripts/backup-production.sh
```

The script prints the UTC backup ID. Store that ID and the deployed image tag in the operator's change record. Do not store credentials or source content in the change record.

## Restore

Restore requires a selected backup ID in `YYYYMMDDTHHMMSSZ` format. The script pauses the public services, copies the matching bucket snapshot without deleting current objects/tombstones, restores PostgreSQL, and restarts the stack. On startup, the API replays all available deletion tombstones before becoming healthy.

```sh
bash scripts/restore-production.sh 20261125T120000Z
```

After restore, confirm health/readiness, login, timeline and archive behavior using a synthetic account. Confirm each known deleted account/source remains absent and its object prefix has no readable versions. Review logs for deletion replay and migration errors. Record recovery time and data-loss window.

For a database-only rehearsal on a disposable development Compose project, start the API and database with `docker compose -p lifeos-iteration up --build --detach --wait api` and run `uv run python scripts/verify_database_restore.py` from the repository root. It restores into a freshly created test database and checks both a deletion made after the snapshot and an untouched object against the live development object store.

## Important recovery boundary

The API persists deletion tombstones in the configured object bucket and replays them after a **database-only restore**, which is covered by automated synthetic tests. The scripts also snapshot and restore S3 objects. If both the database and primary bucket are lost, tombstones created after the restored bucket snapshot may be absent. Before a real-user launch, configure continuous cross-failure-domain preservation of the deletion ledger (or an equivalent independent deletion journal), and exercise that failure mode. A daily snapshot alone does not guarantee that deletions after its timestamp will be replayed.

The sample 35-day backup expiry is an operator policy. It is not imposed by the API or scripts. Do not report deletion as complete from all backups until the published retention window has elapsed and the configured lifecycle has been verified.
