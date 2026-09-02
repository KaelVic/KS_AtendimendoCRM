#!/usr/bin/env bash
set -Eeuo pipefail

: "${PUBLIC_DOMAIN:?PUBLIC_DOMAIN must be the configured HTTPS hostname}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose-env.sh
source "${SCRIPT_DIR}/compose-env.sh"
COMPOSE_FILES=("${KS_COMPOSE_FILES[@]}" "${KS_COMPOSE_PROFILE_ARGS[@]}")

docker compose "${COMPOSE_FILES[@]}" ps
curl --fail --silent --show-error "https://${PUBLIC_DOMAIN}/health/live" > /dev/null
docker compose "${COMPOSE_FILES[@]}" exec -T postgres pg_isready \
  -U "$(docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c 'printf %s "$POSTGRES_USER"')" > /dev/null
test "$(docker compose "${COMPOSE_FILES[@]}" exec -T redis redis-cli ping | tr -d '\r')" = PONG
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  docker compose "${COMPOSE_FILES[@]}" exec -T openwa node -e \
    "require('http').get('http://127.0.0.1:2785/api/health/ready', r => process.exit(r.statusCode < 400 ? 0 : 1)).on('error', () => process.exit(1))"
  printf 'Health checks passed for web, API, PostgreSQL, Redis and OpenWA.\n'
else
  printf 'Health checks passed for web, API, PostgreSQL and Redis (OpenWA disabled).\n'
fi
