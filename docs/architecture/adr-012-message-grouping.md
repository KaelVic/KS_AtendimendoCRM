# ADR-012 — Agrupamento de mensagens fragmentadas

## Status

Em implementação incremental.

## Decisão

O PostgreSQL persistirá cada `message` e o `message_turn` formado. Redis manterá
somente a janela temporária (`7s`, limitada a `25s`) e o lock distribuído por
conversa, com token e TTL. A montagem ordena fragmentos por `created_at` e ID.

`HUMAN_ACTIVE` é verificado novamente antes de qualquer envio. Reentregas são
deduplicadas pela chave única da mensagem; uma mensagem nova durante o
processamento permanece no banco e agenda nova avaliação.

O consumidor de turnos e a integração com o caminho de ingestão ainda são
pendências desta implementação incremental; nenhuma resposta externa é gerada
até que esse consumidor exista.
