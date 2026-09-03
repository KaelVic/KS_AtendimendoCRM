#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/compose-env.sh"

COMPOSE_FILES=("${KS_COMPOSE_FILES[@]}" "${KS_COMPOSE_PROFILE_ARGS[@]}")

if [[ "${DATABASE_BACKEND:-local}" != "supabase" ]]; then
  echo "Refusing external migration: DATABASE_BACKEND must be supabase." >&2
  exit 2
fi

: "${DATABASE_URL:?DATABASE_URL must be set to the Supabase PostgreSQL URL}"
if [[ ! "${DATABASE_URL}" =~ ^postgres(ql)?(\+asyncpg)?:// ]]; then
  echo "Refusing migration: DATABASE_URL is not a PostgreSQL URL." >&2
  exit 2
fi

docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps api alembic upgrade head
