#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${DATABASE_URL_FILE:?mount the source PostgreSQL DSN as a secret file}"
: "${AGE_RECIPIENT:?set the age public recipient}"
: "${BACKUP_DIR:?set an encrypted backup destination}"
command -v pg_dump >/dev/null
command -v age >/dev/null
command -v sha256sum >/dev/null
command -v python >/dev/null

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

python scripts/ops/pg_service.py \
  --environment-name DATABASE_URL_FILE \
  --service-name ugai_backup \
  --output "$work_dir/pg_service.conf"
chmod 600 "$work_dir/pg_service.conf"
export PGSERVICEFILE="$work_dir/pg_service.conf"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
plain_dump="$work_dir/$timestamp.dump"
encrypted_dump="$BACKUP_DIR/$timestamp.dump.age"

pg_dump --dbname="service=ugai_backup" --format=custom --no-owner --no-acl --file="$plain_dump"
age --recipient "$AGE_RECIPIENT" --output "$encrypted_dump" "$plain_dump"
sha256sum "$encrypted_dump" > "$encrypted_dump.sha256"
chmod 600 "$encrypted_dump" "$encrypted_dump.sha256"

printf 'Encrypted backup written: %s\n' "$encrypted_dump"
printf 'Checksum written: %s.sha256\n' "$encrypted_dump"
