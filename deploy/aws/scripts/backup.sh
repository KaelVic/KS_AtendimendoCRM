#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
: "${BACKUP_S3_URI:?BACKUP_S3_URI must point to a private S3 prefix}"
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  : "${OPENWA_VOLUME_NAME:?OPENWA_VOLUME_NAME must be the named OpenWA session volume}"
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/ks-atendimento}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose-env.sh
source "${SCRIPT_DIR}/compose-env.sh"
COMPOSE_FILES=("${KS_COMPOSE_FILES[@]}" "${KS_COMPOSE_PROFILE_ARGS[@]}")
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
WORK_DIR="$(mktemp -d "${BACKUP_DIR}/.backup-${STAMP}-XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT

docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c \
  'pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "${WORK_DIR}/postgres.dump"

docker compose "${COMPOSE_FILES[@]}" exec -T api sh -c \
  'tar -C /app -czf - var' > "${WORK_DIR}/app-data.tgz"

if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  docker run --rm -v "${OPENWA_VOLUME_NAME}:/source:ro" busybox:1.36.1 \
    tar -C /source -czf - . > "${WORK_DIR}/openwa-session.tgz"
fi

CHECKSUM_FILES=(postgres.dump app-data.tgz)
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  CHECKSUM_FILES+=(openwa-session.tgz)
fi
(cd "$WORK_DIR" && sha256sum "${CHECKSUM_FILES[@]}" > SHA256SUMS)
DEST="${BACKUP_S3_URI%/}/${STAMP}"
S3_PATH="${DEST#s3://}"
BUCKET="${S3_PATH%%/*}"
PREFIX="${S3_PATH#*/}"
ARTIFACTS=(postgres.dump app-data.tgz)
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  ARTIFACTS+=(openwa-session.tgz)
fi
ARTIFACTS+=(SHA256SUMS)
for artifact in "${ARTIFACTS[@]}"; do
  aws s3 cp "${WORK_DIR}/${artifact}" "${DEST}/${artifact}" --sse AES256 --only-show-errors
  encryption="$(aws s3api head-object --bucket "$BUCKET" --key "${PREFIX}/${artifact}" --query 'ServerSideEncryption' --output text)"
  if [[ "$encryption" != "AES256" && "$encryption" != "aws:kms" ]]; then
    echo "Backup verification failed: uploaded object is not encrypted." >&2
    exit 1
  fi
done

printf 'Backup uploaded and encryption verified: artifacts=%d\n' "${#ARTIFACTS[@]}"
