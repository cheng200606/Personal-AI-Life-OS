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

: "${S3_BUCKET:?Set S3_BUCKET in .env}"
: "${BACKUP_S3_URI:?Set BACKUP_S3_URI in .env}"
: "${POSTGRES_DB:?Set POSTGRES_DB in .env}"
: "${POSTGRES_USER:?Set POSTGRES_USER in .env}"

command -v docker >/dev/null || { echo "docker is required." >&2; exit 1; }
command -v aws >/dev/null || { echo "AWS CLI is required." >&2; exit 1; }
[[ "$BACKUP_S3_URI" =~ ^s3://[^/]+(/.*)?$ ]] || { echo "BACKUP_S3_URI must be an S3 URI." >&2; exit 1; }
BACKUP_BUCKET="${BACKUP_S3_URI#s3://}"
BACKUP_BUCKET="${BACKUP_BUCKET%%/*}"
[[ "$BACKUP_BUCKET" != "$S3_BUCKET" ]] || { echo "Use a separate backup bucket." >&2; exit 1; }

BACKUP_ID="$(date -u +%Y%m%dT%H%M%SZ)"
DESTINATION="${BACKUP_S3_URI%/}/$BACKUP_ID"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

docker compose -f docker-compose.production.yml exec -T db sh -c \
  'pg_dump --format=custom --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "$TEMP_DIR/database.dump"
test -s "$TEMP_DIR/database.dump"

aws s3 cp "$TEMP_DIR/database.dump" "$DESTINATION/database.dump" --sse AES256 --only-show-errors
aws s3 sync "s3://$S3_BUCKET/" "$DESTINATION/objects/" --sse AES256 --only-show-errors

cat > "$TEMP_DIR/manifest.json" <<EOF
{
  "backup_id": "$BACKUP_ID",
  "created_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "database_format": "pg_dump custom",
  "object_bucket": "$S3_BUCKET",
  "deletion_tombstones_included": true
}
EOF
aws s3 cp "$TEMP_DIR/manifest.json" "$DESTINATION/manifest.json" --sse AES256 --only-show-errors

printf 'Backup complete: %s\n' "$BACKUP_ID"
printf 'Record this ID with the deployed image tag. Verify the 35-day lifecycle on the backup prefix.\n'
