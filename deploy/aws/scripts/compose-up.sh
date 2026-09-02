#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose-env.sh
source "${SCRIPT_DIR}/compose-env.sh"
docker compose "${KS_COMPOSE_FILES[@]}" "${KS_COMPOSE_PROFILE_ARGS[@]}" up -d
