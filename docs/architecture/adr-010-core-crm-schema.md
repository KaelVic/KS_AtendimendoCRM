# ADR-010: Núcleo persistente tenant-scoped

## Status

Aceito para a Fase 1 — CRM vertical.

## Escopo

A migração `0002_core_crm` cria somente o núcleo necessário para persistir o
primeiro fluxo de CRM. Não armazena tokens, senhas, cookies, chaves de API ou
credenciais; `auth_subject_ref` é apenas uma referência externa ao provedor de
identidade.

## Diagrama textual

```text
tenants
  ├── users
  ├── contacts
  │     └── conversations
  │            ├── conversation_control (1:1)
  │            └── messages
  └── (raiz de isolamento por tenant_id)
```

Todas as relações de domínio carregam `tenant_id`. As relações entre
`conversations`/`contacts`, `conversation_control`/`conversations` e
`messages`/`conversations` usam FKs compostas `(tenant_id, id)`, impedindo que
um registro de um tenant seja associado a outro mesmo se o UUID for conhecido.

## Regras de deleção

- `tenants` → usuários, contatos e conversas: `CASCADE`, para remoção completa
  de um tenant isolado.
- `conversations` → controle e mensagens: `CASCADE`, pois são histórico
  subordinado à conversa.
- `contacts` → conversas: `RESTRICT`, preservando histórico; anonimização será
  tratada por política LGPD futura.
- `users` → `conversation_control.changed_by_user_id`: `SET NULL`, preservando
  a transição sem manter usuário removido.
- A migração não executa deleções de dados existentes fora das tabelas criadas.

## Índices e constraints

- `users (tenant_id, email)`: unicidade de identidade dentro do tenant.
- `contacts (tenant_id, normalized_phone)`: evita contato duplicado por tenant.
- `conversations (tenant_id, channel, external_conversation_id)`: deduplicação
  de conversas recebidas do canal.
- `messages (tenant_id, idempotency_key)`: idempotência de entrada/saída.
- `messages (tenant_id, channel, external_message_id)`: deduplicação externa.
- Índices por tenant + `updated_at`, contato e conversa suportam inbox e
  histórico sem varrer dados de outros tenants.
- `conversation_control.version` suporta atualização otimista; uma transição
  válida altera somente quando `version` ainda coincide.

## Upgrade e rollback

Com `DATABASE_URL` fornecida pelo ambiente:

```bash
python -m alembic -c apps/api/alembic.ini upgrade 0002_core_crm
python -m alembic -c apps/api/alembic.ini downgrade 0001_foundation_baseline
```

Para validar uma instalação vazia, use um banco de teste descartável, execute
`upgrade head`, confira as seis tabelas e então execute o downgrade. Para
validar uma versão anterior, aplique primeiro `upgrade 0001_foundation_baseline`
e depois `upgrade 0002_core_crm`. O downgrade é destrutivo somente para as
tabelas criadas por `0002`; faça backup antes de usar em dados reais.
