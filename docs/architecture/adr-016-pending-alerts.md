# ADR-016 — Pendências e alertas idempotentes

## Status

Aceito para a Fase 4, com o provedor de e-mail real pendente de decisão do proprietário.

## Decisão

Pendências vivem no PostgreSQL, sempre com `tenant_id` e vínculo composto à conversa. A criação grava uma notificação imediata na janela `0`; o worker cria apenas a janela de duas horas atualmente vencida, usando `floor((agora - created_at) / 2h)`. Após downtime não são materializadas todas as janelas históricas, evitando avalanche.

`pending_notifications` tem chave única por `(tenant_id, pending_item_id, window_index)` e por idempotency key. O dispatcher usa `FOR UPDATE SKIP LOCKED`, lease de processamento e retry com backoff. Um e-mail enviado não muda o estado da pendência. Resolução ou resposta efetiva cancela lembretes ainda não enviados; nova atividade usa nova chave de idempotência e cria nova pendência.

O destinatário é somente `OWNER_ALERT_EMAIL`, injetado por ambiente. O fake é o único provider habilitado no desenvolvimento; SMTP/API real entra depois que o proprietário definir provedor e credenciais no cofre.

## Diagrama textual

```text
evento de negócio
  -> PendingItem OPEN (PostgreSQL)
  -> PendingNotification window=0 PENDING
  -> worker: claim lease + SKIP LOCKED
  -> EmailProvider(to=OWNER_ALERT_EMAIL)
  -> SENT / FAILED(backoff) + AuditEvent

resposta efetiva ou ação Resolver
  -> PendingItem RESOLVED (CAS)
  -> PENDING/FAILED -> CANCELLED
```

## Retenção e deleção

Excluir um tenant exclui pendências, notificações e auditoria pelo FK `CASCADE`. Excluir uma conversa exclui suas pendências e notificações. Usuário removido preserva a pendência e apenas torna `resolved_by_user_id` nulo. Nenhum segredo ou conteúdo da conversa é armazenado no alerta.

## Upgrade e rollback

Em banco vazio ou ja no `0007_control_state_machine`, aplicar
`alembic -c apps/api/alembic.ini upgrade 0008_pending_items`. O rollback
reversivel e `alembic -c apps/api/alembic.ini downgrade 0007_control_state_machine`;
ele deve ocorrer somente apos pausar o worker e confirmar que nao ha pendencias
em processamento. A migracao foi validada em SQL offline; a validacao contra
PostgreSQL real depende de `TEST_DATABASE_URL`/Docker autorizado.

## Bloqueio conhecido

Não há provedor de e-mail definitivo configurado. O fake e a interface contratual permitem validar o fluxo sem enviar comunicação externa; com `OWNER_ALERT_EMAIL` ausente o job falha fechado e audita a configuração faltante.
