# ChannelRouter — ownership e migração de sessão

`ChannelRouter` fica entre o domínio/outbox e os adapters de WhatsApp. A
interface `WhatsAppAdapter` não muda. O router resolve `tenant_id` + sessão no
servidor, seleciona o `gateway_id`, relê o ownership e só então chama o
adapter.

## Estado persistido

- `gateway_shards`: inventário do shard, engine, saúde, versão e epoch global.
- `channel_sessions`: vínculo tenant → shard → `external_session_id`, estado,
  epoch e versão otimista.
- `session_assignments`: histórico de owners e lease. Um índice único parcial
  permite somente uma linha `ACTIVE` por tenant/sessão.

O epoch da atribuição é o fencing token. Lease expirado, owner divergente,
tenant divergente, sessão desconectada ou shard diferente de `HEALTHY` falham
fechado. A implementação PostgreSQL usa `SELECT ... FOR UPDATE`; a de memória
é usada nos testes de concorrência.

## Piloto

O ambiente declara um único `OPENWA_GATEWAY_ID` e uma única
`OPENWA_SESSION_ID=kaelsolutions_pilot`. A sessão não é reivindicada
automaticamente: o owner deve ser provisionado em operação controlada, para
que o piloto sem número pareado permaneça inerte.

## Migração de shard

Uma migração só pode ser iniciada com todas as pré-condições verdadeiras:

1. pausar envios;
2. drenar a outbox;
3. confirmar backup da sessão e do CRM;
4. parar o owner anterior;
5. restaurar/relinkar a sessão no novo shard;
6. reivindicar com novo epoch;
7. executar smoke test e só então liberar envios.

`migrate_session` rejeita qualquer conjunto incompleto. Nunca iniciar duas
instâncias conectadas à mesma sessão.
