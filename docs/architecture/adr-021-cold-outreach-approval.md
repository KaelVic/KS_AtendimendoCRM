# ADR-021: Fila de aprovação para primeira abordagem

## Status

Aceito em 31 de agosto de 2026.

## Decisão

- A API cria um único `OutreachDraft` por pesquisa e tenant. Empresa, fonte,
  evidências, achados e contato são snapshots derivados de
  `ProspectResearch`; o cliente envia somente texto e motivo.
- O rascunho começa em `PENDING_APPROVAL`. A aprovação exige confirmação
  humana explícita e captura hashes da pesquisa, mensagem e destinatário, com
  validade configurável (24 horas no padrão).
- Editar texto, motivo ou número limpa a aprovação e volta a
  `PENDING_APPROVAL`. Mudança da pesquisa, expiração, opt-out ou número
  divergente torna a aprovação inválida no servidor. A edição de número
  também é rejeitada se o mesmo tenant já tiver um rascunho para o
  destinatário normalizado.
- O envio passa novamente pela política, sessão e tenant, grava outbox antes
  do gateway e usa chave idempotente. Sucesso marca o outbox como entregue e o
  rascunho como `SENT`; reentrega da mesma chave retorna o mesmo resultado.
- Opt-out, erro de sessão e limite conservador pausam o rascunho. Nenhuma
  mensagem é enviada automaticamente a partir da pesquisa.

## Contratos HTTP

`POST /outreach/drafts`, `GET /outreach/drafts`,
`PUT /outreach/drafts/{id}`, `POST .../approve`, `POST .../reject`,
`POST .../opt-out` e `POST .../send` exigem autenticação do proprietário.
O tenant é obtido do token; campos extras são rejeitados. O endpoint de envio
aplica a mesma política do serviço e não depende de qualquer controle da
interface web; uma chamada direta sem aprovação retorna `APPROVAL_REQUIRED` e
não alcança o gateway.

## Limitações e evolução

O provider padrão é `fake`. OpenWA só é selecionado explicitamente quando
credenciais por ambiente existem e continua atrás do adapter. O limite
conservador atual é mantido em memória por processo; antes de múltiplos
workers de prospecção, deve migrar para contador Redis ou consulta transacional
compartilhada, mantendo o mesmo contrato.

Os testes de serviço cobrem expiração, mudança de pesquisa/número, opt-out,
duplicidade, sessão insegura e isolamento de tenant. Testes HTTP cobrem
autenticação, rejeição de `tenant_id` enviado pelo cliente, derivação do tenant
do token e tentativa direta de envio sem aprovação.

## Rollback

`alembic downgrade 0013_outreach_approval:0012_prospect_research` remove apenas
`outreach_drafts`; pesquisas e CRM anterior permanecem.
