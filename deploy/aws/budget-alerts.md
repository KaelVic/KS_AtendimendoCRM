# Budget alertas

Os comandos abaixo são somente um runbook. Eles criam recursos AWS e exigem
aprovação explícita do proprietário antes da execução.

```bash
export AWS_REGION=<região-aprovada>
export BACKUP_BUCKET=<bucket-privado-aprovado>
export BUDGET_NAME=ks-atendimento-pilot
export BUDGET_LIMIT_USD=<limite-mensal-aprovado>
export BUDGET_ALERT_EMAIL=<email-de-alerta-aprovado>
export PROJECT_TAG=KS-Atendimento-IA
export CONFIRM_AWS_MUTATION=I_APPROVE_AWS_BUDGET
bash deploy/aws/scripts/create-budget.sh
```

O script cria alertas de custo real em 80% e 100% do limite mensal, filtrados
pela tag `Project`. O assinante precisa confirmar o e-mail recebido pela AWS.
