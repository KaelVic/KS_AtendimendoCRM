# ADR-015: Controle humano, retomada e envio seguro

## Status

Aceito para a Fase 4 incremental.

## Decisão

`ControlService` é o único dono das transições. O banco executa `UPDATE` com
`tenant_id`, estado anterior e `version` esperada; zero linhas significa conflito
otimista e não altera nada. Cada transição grava `actor_user_id`, motivo, versão,
política e timestamps em `audit_events`.

Assumir leva a `HUMAN_ACTIVE`. Devolver primeiro leva a `BOT_RESUMING`, resume
somente mensagens desde `human_started_at`, atualiza `context_summary` e
`commercial_state`, e só então leva a `BOT_ACTIVE`. Se a versão mudar durante a
retomada, a finalização falha fechada; mensagens novas continuam sendo processadas
na avaliação seguinte. O resumo não recebe o contexto anterior como intervalo a
resumir, evitando repetir perguntas já respondidas.

`AI_ASSISTED_PENDING` aceita conteúdo humano ou um rascunho aprovado. O rascunho
carrega hash dos fatos e `policy_version`; hash ou versão divergente são rejeitados.
O formatter pode adequar o tom, mas não pode retornar fatos diferentes.

O envio automático passa por `SafeAutomaticSender`, que usa o mesmo gate por
conversa do handoff, relê `ConversationControl` duas vezes e envia somente se a
última leitura for `BOT_ACTIVE`. `OutboxDispatcher` falha fechado quando esse
sender não foi configurado; mensagens humanas seguem o caminho manual.

Eventos `CONVERSATION_CONTROL_CHANGED` são publicados após commit em canal Redis
tenant-scoped. `InMemoryControlEventPublisher` cobre testes. Falha do Redis não
desfaz o estado persistido; o polling do CRM continua sendo fallback.

## Migração e rollback

`0007_control_state_machine` adiciona o resumo/estado comercial da conversa e os
timestamps do intervalo humano. O downgrade remove somente essas colunas:

```text
alembic -c apps/api/alembic.ini upgrade 0007_control_state_machine
alembic -c apps/api/alembic.ini downgrade 0006_media_assets
```

Não há chamada externa durante a transação do handoff e nenhuma credencial é
armazenada. O limite do gate Redis é 60 segundos; timeout/indisponibilidade resulta
em `CONTROL_BUSY` ou envio bloqueado.
