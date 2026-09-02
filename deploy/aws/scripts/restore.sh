#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
: "${BACKUP_S3_URI:?BACKUP_S3_URI must point to a private S3 prefix}"
: "${BACKUP_STAMP:?BACKUP_STAMP must identify one backup directory}"
if [[ "${CONFIRM_RESTORE:-}" != "I_UNDERSTAND_RESTORE_OVERWRITES_DATA" ]]; then
  echo 'Refusing restore: set CONFIRM_RESTORE=I_UNDERSTAND_RESTORE_OVERWRITES_DATA.' >&2
  exit 2
fi
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  : "${OPENWA_VOLUME_NAME:?OPENWA_VOLUME_NAME must be the named OpenWA session volume}"
  if [[ ! "$OPENWA_VOLUME_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]]; then
    echo 'Refusing restore: invalid Docker volume name.' >&2
    exit 2
  fi
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/ks-atendimento}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose-env.sh
source "${SCRIPT_DIR}/compose-env.sh"
COMPOSE_FILES=("${KS_COMPOSE_FILES[@]}" "${KS_COMPOSE_PROFILE_ARGS[@]}")
WORK_DIR="$(mktemp -d "${BACKUP_DIR}/.restore-XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT
mkdir -p "$BACKUP_DIR"
SOURCE="${BACKUP_S3_URI%/}/${BACKUP_STAMP}"
ARTIFACTS=(postgres.dump app-data.tgz)
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  ARTIFACTS+=(openwa-session.tgz)
fi
ARTIFACTS+=(SHA256SUMS)
for artifact in "${ARTIFACTS[@]}"; do
  aws s3 cp "${SOURCE}/${artifact}" "${WORK_DIR}/${artifact}" --only-show-errors
done
(cd "$WORK_DIR" && sha256sum -c SHA256SUMS)

STOP_SERVICES=(caddy web worker api)
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  STOP_SERVICES+=(openwa)
fi
docker compose "${COMPOSE_FILES[@]}" stop "${STOP_SERVICES[@]}"
docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c \
  'pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "${WORK_DIR}/postgres.dump"
docker compose "${COMPOSE_FILES[@]}" run --rm -T api sh -c 'tar -C /app -xzf -' \
  < "${WORK_DIR}/app-data.tgz"
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  docker run --rm -v "${OPENWA_VOLUME_NAME}:/target" busybox:1.36.1 \
    sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
  docker run --rm -i -v "${OPENWA_VOLUME_NAME}:/target" busybox:1.36.1 \
    tar -C /target -xzf - < "${WORK_DIR}/openwa-session.tgz"
fi
docker compose "${COMPOSE_FILES[@]}" up -d

printf 'Restore completed from: %s\n' "$SOURCE"
