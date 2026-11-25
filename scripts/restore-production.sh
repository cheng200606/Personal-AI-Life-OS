#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

BACKUP_ID="${1:-}"
[[ "$BACKUP_ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
  echo "Usage: $0 YYYYMMDDTHHMMSSZ" >&2
  exit 2
}
: "${S3_BUCKET:?Set S3_BUCKET in .env}"
: "${S3_DELETION_JOURNAL_BUCKET:?Set S3_DELETION_JOURNAL_BUCKET in .env}"
: "${BACKUP_S3_URI:?Set BACKUP_S3_URI in .env}"

command -v docker >/dev/null || { echo "docker is required." >&2; exit 1; }
command -v aws >/dev/null || { echo "AWS CLI is required." >&2; exit 1; }
[[ "$BACKUP_S3_URI" =~ ^s3://[^/]+(/.*)?$ ]] || { echo "BACKUP_S3_URI must be an S3 URI." >&2; exit 1; }
BACKUP_BUCKET="${BACKUP_S3_URI#s3://}"
BACKUP_BUCKET="${BACKUP_BUCKET%%/*}"
[[ "$BACKUP_BUCKET" != "$S3_BUCKET" ]] || { echo "Use a separate backup bucket." >&2; exit 1; }
[[ "$S3_DELETION_JOURNAL_BUCKET" != "$S3_BUCKET" && "$S3_DELETION_JOURNAL_BUCKET" != "$BACKUP_BUCKET" ]] || {
  echo "Use a separate deletion journal bucket." >&2
  exit 1
}

read -r -p "This replaces the production database and restores objects from $BACKUP_ID. Type the backup ID to continue: " CONFIRMATION
[[ "$CONFIRMATION" == "$BACKUP_ID" ]] || { echo "Restore cancelled."; exit 1; }

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
SOURCE="${BACKUP_S3_URI%/}/$BACKUP_ID"
aws s3 cp "$SOURCE/database.dump" "$TEMP_DIR/database.dump" --only-show-errors
aws s3 cp "$SOURCE/manifest.json" "$TEMP_DIR/manifest.json" --only-show-errors
if grep -Fq '"deletion_journal_bucket":' "$TEMP_DIR/manifest.json"; then
  grep -Fq "\"deletion_journal_bucket\": \"$S3_DELETION_JOURNAL_BUCKET\"" "$TEMP_DIR/manifest.json" || {
    echo "The selected backup refers to a different deletion journal. Reconcile it before recovery." >&2
    exit 1
  }
elif ! grep -Fq '"deletion_tombstones_included": true' "$TEMP_DIR/manifest.json"; then
  echo "The selected backup has no deletion recovery metadata." >&2
  exit 1
fi

docker compose -f docker-compose.production.yml stop caddy web api
docker compose -f docker-compose.production.yml up --detach --wait db

# Add or restore objects, but keep newer objects and tombstones already in the live bucket.
aws s3 sync "$SOURCE/objects/" "s3://$S3_BUCKET/" --sse AES256 --only-show-errors

docker compose -f docker-compose.production.yml exec -T db sh -c \
  'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$TEMP_DIR/database.dump"

# API startup replays deletion tombstones before /ready succeeds.
docker compose -f docker-compose.production.yml up --detach --wait
printf 'Restore commands completed for %s. Verify /api/v1/ready and deleted test records before reopening traffic.\n' "$BACKUP_ID"
