# ADR-017 — Propostas reproduzíveis e versionadas

## Status

Aceito para a fatia de propostas da Fase 5.

## Decisão

O modelo pode produzir somente um `ProposalDraft` JSON. A API valida o draft
contra o snapshot ativo de catálogo (`catalog-v1`) e deriva preço, prazo,
revisões, escopo e itens no servidor. Divergências persistem como
`HUMAN_APPROVAL_REQUIRED` e não geram PDF.

Propostas válidas são renderizadas por código em um template determinístico,
com `catalog_version`, `template_version`, `data_hash` e `data_used` persistidos.
O PDF recebe somente valores derivados do catálogo e é guardado em storage
tenant-scoped. A chave de idempotência é única por tenant; uma repetição do
mesmo conteúdo retorna a proposta existente e a reutilização com conteúdo
diferente falha com erro estável.

Não há envio externo nesta fase. Pagamento, contrato, assinatura, aprovação
humana e identidade visual final permanecem estados/integrações posteriores.

## Consequências e rollback

A migração `0009_proposals` cria `proposals` e `proposal_items`, com FK
composta tenant-scoped, itens em cascata e downgrade reversível. Para atualizar:

```bash
alembic -c apps/api/alembic.ini upgrade head
```

Para rollback da fatia, depois de exportar os PDFs necessários:

```bash
alembic -c apps/api/alembic.ini downgrade 0008_pending_items
```

O downgrade remove apenas as tabelas de propostas; o histórico de mensagens e
as outras tabelas não são alterados. A imagem/arquivo PDF deve ser removida
conforme a política de retenção aprovada, nunca por uma rotina ampla não
confirmada.

## Gate binário da fatia

A fatia passa somente se os testes de contrato, validação, determinismo,
idempotência e isolamento passarem e `0009_proposals` puder subir após
`0008_pending_items` e retornar a `0008_pending_items` sem erro. Nenhuma
proposta é enviada automaticamente.
