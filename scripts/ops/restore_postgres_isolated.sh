#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${BACKUP_FILE:?set the encrypted backup file}"
: "${AGE_IDENTITY_FILE:?mount the age private identity as a secret file}"
: "${RESTORE_DATABASE_URL_FILE:?mount a dedicated isolated restore-target DSN}"
: "${RESTORE_CONFIRMATION:?set RESTORE_CONFIRMATION=RESTORE_TO_ISOLATED_EMPTY_DATABASE}"
[[ "$RESTORE_CONFIRMATION" == "RESTORE_TO_ISOLATED_EMPTY_DATABASE" ]] || {
  echo "Refusing restore: explicit isolated-target confirmation is required" >&2
  exit 2
}
[[ -f "$BACKUP_FILE" && -f "$BACKUP_FILE.sha256" && -f "$AGE_IDENTITY_FILE" ]] || {
  echo "Backup, checksum, or age identity file is missing" >&2
  exit 2
}
command -v pg_restore >/dev/null
command -v psql >/dev/null
command -v age >/dev/null
command -v sha256sum >/dev/null
command -v python >/dev/null

sha256sum --check "$BACKUP_FILE.sha256"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

age --decrypt --identity "$AGE_IDENTITY_FILE" --output "$work_dir/restore.dump" "$BACKUP_FILE"
pg_restore --list "$work_dir/restore.dump" >/dev/null

python scripts/ops/pg_service.py \
  --environment-name RESTORE_DATABASE_URL_FILE \
  --service-name ugai_restore \
  --output "$work_dir/pg_service.conf"
chmod 600 "$work_dir/pg_service.conf"
export PGSERVICEFILE="$work_dir/pg_service.conf"

table_count="$(psql --no-psqlrc --tuples-only --no-align --dbname="service=ugai_restore" \
  --command="SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema');")"
[[ "$table_count" =~ ^[0-9]+$ ]] || {
  echo "Could not verify that restore target is empty" >&2
  exit 3
}
[[ "$table_count" == "0" ]] || {
  echo "Refusing restore: target database is not empty" >&2
  exit 3
}

pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
  --dbname="service=ugai_restore" "$work_dir/restore.dump"
echo "Restore completed to the explicitly supplied empty isolated target."
