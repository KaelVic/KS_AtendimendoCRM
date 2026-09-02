# ADR-018 — Aceite, contrato e pagamento com estados explícitos

## Status

Aceito para a extensão comercial da Fase 5.

## Decisão

O aceite referencia uma proposta `RENDERED` e usa o preço persistido no
snapshot validado do catálogo. O cliente não fornece preço, desconto, prazo,
escopo ou URL de pagamento. Uma ordem comercial tenant-scoped é criada uma
única vez por proposta e por chave de idempotência.

Estados implementados:

- `CONTRACT_PENDING`: não existe template de contrato configurado; cria
  pendência `CONTRACT`.
- `PAYMENT_LINK_PENDING`: o template está configurado, mas não existe link
  exato para produto e valor na allowlist versionada; cria pendência `PAYMENT`.
- `PAYMENT_PENDING`: contrato e link aprovado estão disponíveis.
- `ONBOARDING_READY`: somente webhook assinado, confirmado, idempotente e com
  valor/moeda compatíveis libera onboarding.
- `CANCELLED` e `REFUNDED` existem como estados terminais reservados para
  operação humana; não há endpoint automático para essas ações.

Links são aceitos apenas como correspondência exata de
`product_id + amount_cents` em `PAYMENT_LINK_ALLOWLIST_JSON`, com HTTPS e
`PAYMENT_LINK_CONFIG_VERSION`. O corpo bruto do webhook não é persistido;
somente hash e campos mínimos saneados são gravados. A assinatura HMAC usa os
bytes exatos recebidos e a unicidade `(tenant_id, provider, external_event_id)`
protege contra replay/reentrega.

## Contratos

```text
POST /commercial/proposals/{proposal_id}/accept
  {"idempotency_key": "..."}

POST /commercial/webhooks/payments/{provider}
  {external_event_id, payment_reference, event_type,
   amount_cents, currency}
  X-Payment-Signature: sha256=<hmac>
```

Campos desconhecidos são rejeitados. `PAYMENT_FAILED`, assinatura inválida,
valor divergente, estado incompatível e evento conflitante não liberam
onboarding.

## Migração e rollback

A migração `0010_commercial_flow` depende de `0009_proposals` e cria
`commercial_orders` e `payment_events` com FKs compostas, constraints de estado,
unicidade de aceite/evento e timestamps. Validar upgrade:

```bash
alembic -c apps/api/alembic.ini upgrade head
```

Rollback seguro da fatia:

```bash
alembic -c apps/api/alembic.ini downgrade 0009_proposals
```

Antes do rollback, exportar pendências comerciais e evidências necessárias.
Como o downgrade remove os registros de aceite/pagamento, não deve ser usado
depois de liberar onboarding em produção sem backup e decisão operacional.
