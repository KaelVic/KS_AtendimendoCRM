#!/usr/bin/env bash
set -Eeuo pipefail

: "${BUDGET_ALERT_EMAIL:?BUDGET_ALERT_EMAIL must be supplied outside Git}"
: "${BUDGET_LIMIT_USD:?BUDGET_LIMIT_USD must be configured}"
: "${BUDGET_NAME:?BUDGET_NAME must be configured}"
if [[ "${CONFIRM_AWS_MUTATION:-}" != "I_APPROVE_AWS_BUDGET" ]]; then
  echo 'Plan only. Set CONFIRM_AWS_MUTATION=I_APPROVE_AWS_BUDGET to create the budget.'
  exit 2
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
PROJECT_TAG="${PROJECT_TAG:-KS-Atendimento-IA}"
if [[ ! "$PROJECT_TAG" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
  echo 'Refusing budget: PROJECT_TAG must contain only tag-safe characters.' >&2
  exit 2
fi
if [[ ! "$BUDGET_NAME" =~ ^[A-Za-z0-9._-]{1,100}$ ]]; then
  echo 'Refusing budget: BUDGET_NAME must contain only tag-safe characters.' >&2
  exit 2
fi
if [[ ! "$BUDGET_LIMIT_USD" =~ ^[0-9]+([.][0-9]{1,2})?$ ]]; then
  echo 'Refusing budget: BUDGET_LIMIT_USD must be a positive decimal.' >&2
  exit 2
fi
TAG_FILTER="user:Project\$${PROJECT_TAG}"
aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget "{\"BudgetName\":\"${BUDGET_NAME}\",\"BudgetLimit\":{\"Amount\":\"${BUDGET_LIMIT_USD}\",\"Unit\":\"USD\"},\"CostFilters\":{\"TagKeyValue\":[\"${TAG_FILTER}\"]},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}"
for threshold in 80 100; do
  aws budgets create-notification-with-subscriber \
    --account-id "$ACCOUNT_ID" \
    --budget-name "$BUDGET_NAME" \
    --notification "{\"NotificationType\":\"ACTUAL\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":${threshold},\"ThresholdType\":\"PERCENTAGE\"}" \
    --subscriber "{\"SubscriptionType\":\"EMAIL\",\"Address\":\"${BUDGET_ALERT_EMAIL}\"}"
done
