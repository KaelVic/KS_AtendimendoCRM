# ADR-008: Padrão Outbox Transacional para Envio Confiável

## Status
Aceito em 31 de agosto de 2026.

## Contexto
Falhas de rede ou reinícios de contêiner durante o processamento de respostas do robô poderiam causar inconsistências graves: mensagens salvas no banco mas não entregues ao WhatsApp, ou mensagens enviadas ao gateway sem registro auditável no CRM.

## Decisão
Implementar o **Padrão Outbox Transacional**:
- Toda mensagem a ser enviada ao cliente é primeiramente persistida na tabela `outbox_events` na mesma transação atômica do banco de dados que registra a mensagem no histórico do CRM.
- Um worker especializado processa registros pendentes da outbox com controle de idempotência (`idempotency_key`), retentativas com backoff exponencial e detecção de duplicidades.
- Somente após confirmação do gateway o registro da outbox é marcado como `DELIVERED`.

## Consequências
- Garantia de entrega *at-least-once* sem risco de mensagens "fantasmas" no CRM.
- Resiliência total contra desconexões temporárias entre o backend e o gateway OpenWA.
