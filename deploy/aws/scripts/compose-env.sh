#!/usr/bin/env bash
set -Eeuo pipefail

# Must be sourced from the repository root. The profile is opt-in so the
# essential deployment never starts an unpaired or unapproved WhatsApp session.
KS_COMPOSE_PROFILE_ARGS=()
if [[ "${ENABLE_OPENWA:-0}" == "1" ]]; then
  : "${OPENWA_IMAGE:?OPENWA_IMAGE is required when ENABLE_OPENWA=1}"
  if [[ ! "$OPENWA_IMAGE" =~ ^ghcr\.io/rmyndharis/openwa:0\.23\.3@sha256:[0-9a-fA-F]{64}$ ]]; then
    echo 'Refusing OpenWA: use the official OpenWA 0.23.3 image pinned by a verified sha256 digest.' >&2
    exit 2
  fi
  : "${OPENWA_API_KEY:?OPENWA_API_KEY is required when ENABLE_OPENWA=1}"
  : "${OPENWA_API_MASTER_KEY:?OPENWA_API_MASTER_KEY is required when ENABLE_OPENWA=1}"
  : "${OPENWA_API_KEY_PEPPER:?OPENWA_API_KEY_PEPPER is required when ENABLE_OPENWA=1}"
  : "${OPENWA_WEBHOOK_SECRET:?OPENWA_WEBHOOK_SECRET is required when ENABLE_OPENWA=1}"
  : "${OPENWA_SESSION_ID:?OPENWA_SESSION_ID is required when ENABLE_OPENWA=1}"
  : "${OPENWA_ALLOWED_SESSIONS:?OPENWA_ALLOWED_SESSIONS is required when ENABLE_OPENWA=1}"
  : "${OPENWA_ALLOWED_IPS:?OPENWA_ALLOWED_IPS is required when ENABLE_OPENWA=1}"
  if [[ "${OPENWA_API_KEY_ROLE:-}" != "operator" ]]; then
    echo 'Refusing OpenWA: integration key must use the operator role.' >&2
    exit 2
  fi
  if [[ "${OPENWA_ALLOWED_SESSIONS}" != "${OPENWA_SESSION_ID}" ]]; then
    echo 'Refusing OpenWA: allowed sessions must contain only the configured session.' >&2
    exit 2
  fi
  if (( ${#OPENWA_API_MASTER_KEY} < 32 )); then
    echo 'Refusing OpenWA: API master key must have at least 32 characters.' >&2
    exit 2
  fi
  if (( ${#OPENWA_API_KEY_PEPPER} < 32 )); then
    echo 'Refusing OpenWA: API key pepper must have at least 32 characters.' >&2
    exit 2
  fi
  if (( ${#OPENWA_API_KEY} < 32 )); then
    echo 'Refusing OpenWA: integration key must have at least 32 characters.' >&2
    exit 2
  fi
  KS_COMPOSE_PROFILE_ARGS=(--profile openwa)
fi

KS_COMPOSE_FILES=(-f docker-compose.yml -f deploy/aws/docker-compose.aws.yml)
