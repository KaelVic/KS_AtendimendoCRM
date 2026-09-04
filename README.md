# KS Atendimento IA — Plataforma Autônoma de CRM, WhatsApp e IA

> **KaelSolutions** &bull; Piloto Comercial &bull; Fuso Horário: `America/Sao_Paulo`

Monorepo modular para atendimento inteligente, CRM, qualificação de leads, agendamento de reuniões e geração de propostas com inteligência artificial, construído para atender aos requisitos estritos definidos no [`AGENTS.md`](./AGENTS.md).

---

## 🏛️ Arquitetura e Decisões Registradas (ADRs)

| ADR | Título | Decisão Principal |
|---|---|---|
| [ADR-001](./docs/architecture/adr-001-modular-monolith.md) | Monólito Modular | Monorepo unificado (FastAPI + Next.js + Redis Worker) sem complexidade prematura de microsserviços. |
| [ADR-002](./docs/architecture/adr-002-postgresql-source-of-truth.md) | PostgreSQL como Fonte da Verdade | Banco transacional único com isolamento estrito de `tenant_id` e auditoria. |
| [ADR-003](./docs/architecture/adr-003-redis-ephemeral-state.md) | Redis para Estado Efêmero | Debounce de mensagens (7s a 25s), locks distribuídos e filas assíncronas. |
| [ADR-004](./docs/architecture/adr-004-code-state-machine.md) | Máquina de Estados em Código | Controle determinístico e auditável da conversa (`BOT_ACTIVE`, `HUMAN_ACTIVE`, etc.). |
| [ADR-005](./docs/architecture/adr-005-provider-adapters.md) | Adaptadores de Provedores | Portas e adaptadores para Gemini, WhatsApp, Calendário e E-mail com mocks contratuais. |
| [ADR-006](./docs/architecture/adr-006-local-transcription.md) | Transcrição Local | Faster-Whisper executando localmente a custo financeiro zero e privacidade ampliada. |
| [ADR-007](./docs/architecture/adr-007-isolated-scrapegraph.md) | ScrapeGraphAI Isolado | Serviço em contêiner separado com aprovação humana obrigatória antes de qualquer contato. |
| [ADR-008](./docs/architecture/adr-008-transactional-outbox.md) | Outbox Transacional | Persistência atômica pré-envio para entrega confiável *at-least-once*. |
| [ADR-009](./docs/architecture/adr-009-adopt-openwa-gateway.md) | OpenWA como Gateway Padrão | Gateway v0.23.3 isolado em rede interna Docker, sem exposição pública e sob profile. |
| [ADR-014](./docs/architecture/adr-014-secure-media-pipeline.md) | Pipeline seguro de mídia | MIME real, limites, storage tenant-scoped, transcrição local e derivada de imagem sem EXIF. |
| [ADR-015](./docs/architecture/adr-015-control-handoff.md) | Controle e handoff | FSM, CAS otimista, resumo humano, publisher realtime e gate de outbox. |
| [ADR-016](./docs/architecture/adr-016-pending-alerts.md) | Pendências e alertas | Alertas imediatos, janelas de 2h, retry, lease e resolução efetiva. |
| [ADR-017](./docs/architecture/adr-017-reproducible-proposals.md) | Propostas reproduzíveis | Catálogo validado, PDF determinístico, versionamento e idempotência. |
| [ADR-018](./docs/architecture/adr-018-acceptance-contract-payment.md) | Aceite e pagamento | Estados explícitos, allowlist versionada e webhook idempotente. |
| [ADR-019](./docs/architecture/adr-019-calendar-meetings.md) | Agenda e reuniões | Conflito duplo, lock, fuso local, lembretes e no-show auditável. |

---

Os ADRs 020 e 021 documentam a pesquisa pública com evidência e a fila de
aprovação da primeira abordagem fria, incluindo bloqueio de opt-out,
deduplicação, aprovação expirada e outbox.

## 🚀 Início Rápido

### Estado da Fase 0 — Fundação

A fundação possui API FastAPI com liveness/readiness, correlação por request,
health de PostgreSQL/Redis/worker e OpenWA opcional, além de baseline Alembic.
O gate só pode ser considerado aprovado após subir a stack essencial e confirmar
os health checks em ambiente Docker autorizado; nenhum número real ou integração
externa é necessário nesta fase.

### E2E e evidências

Métricas, readiness e runbooks operacionais estão em
[`docs/operations/observability.md`](./docs/operations/observability.md).
Para usar Neon como PostgreSQL externo, consulte
[`docs/operations/neon-postgres.md`](./docs/operations/neon-postgres.md).

Execute `pytest -q` para incluir API, worker, ScrapeGraph e E2E fake. Os quatro
cenários OpenWA usam gateway, sessão, volume e dados sintéticos. A matriz e os
comandos do smoke real opt-in estão em
[`docs/e2e-critical-scenarios.md`](./docs/e2e-critical-scenarios.md); nenhum
skip ambiental conta como gate aprovado.

### Avaliação anonimizada do agente

O conjunto `tests/eval` contém 30 cenários sintéticos em dois splits (24 de
desenvolvimento e 6 holdout), cobrindo os fluxos conversacionais e comerciais
críticos do `AGENTS.md`. A rubrica pontua naturalidade, fidelidade factual,
aderência comercial, segurança, concisão, próximo passo e escalonamento de 0 a
4. O gate reprova qualquer bloqueador, média geral abaixo de 3,0, dimensão
abaixo de 2 ou dimensão crítica abaixo de 3.

Valide a estrutura sem chamar serviços externos:

```bash
python scripts/evaluate_agent.py --validate-dataset
```

Use apenas `dev` para ajustar o agente. Depois de congelar a versão do prompt,
registre-a no arquivo de julgamentos e execute o holdout somente como medição
final, com `--allow-holdout`; o procedimento completo e o formato dos scores
estão em [`tests/eval/README.md`](./tests/eval/README.md).

### 1. Pré-requisitos
- Docker & Docker Compose (v2+)
- Python 3.12+
- Node.js 20+

### 2. Configuração de Ambiente
Copie o modelo de ambiente sem segredos:
```bash
cp .env.example .env
```

### Inbox do CRM (Fase 1)

Em `http://localhost:3000`, a inbox lista conversas, mostra mensagens recebidas,
permite assumir/devolver o controle e enviar texto somente quando `HUMAN_ACTIVE`.
As ações críticas aguardam confirmação da API; a tela sinaliza carregamento,
erro, vazio e reconexão. A seleção de arquivo é apenas um marcador de upload
pendente: storage e anexos persistidos estão fora desta fatia. O contrato e as
decisões estão em [ADR-011](./docs/architecture/adr-011-crm-inbox.md).

O smoke browser opcional pode ser executado com `WEB_URL=http://localhost:3000
pytest -m e2e tests/e2e/test_inbox_ui.py`; ele mocka a API no navegador e não
usa WhatsApp, contatos reais ou segredos.
*(Nunca versione chaves reais no repositório).*

### Fechamento da Fase 8 — Piloto

A Fase 8 foi fechada em 1º de setembro de 2026 como **NÃO APROVADA**: os
artefatos e testes fake existem, mas o gate exige evidência real de stack,
backup/restore, UI e recuperação OpenWA. Consulte a [matriz de fechamento](./docs/phase-8-closure.md)
e o [changelog](./CHANGELOG.md). Nenhuma ação externa foi executada.

### 3. Comandos Principais

O runbook do deploy econômico na AWS está em
[`deploy/aws/README.md`](./deploy/aws/README.md). Ele é somente operacional:
nenhum recurso remoto é criado sem aprovação explícita.

| Ação | Comando Docker / Make | Comando NPM |
|---|---|---|
| **Subir Stack Essencial** | `docker compose up -d` ou `make up` | `npm run up` |
| **Subir com OpenWA (Opcional)** | `docker compose --profile openwa up -d` | `npm run up:openwa` |
| **Parar Contêineres** | `docker compose down` ou `make down` | `npm run down` |
| **Ver Logs Unificados** | `docker compose logs -f` ou `make logs` | `npm run logs` |
| **Executar Testes** | `pytest apps/api/tests` ou `make test` | `npm test` |
| **Lint e Formatação** | `ruff check apps/api` ou `make lint` | `npm run lint` |

### Validação da fundação

```bash
alembic -c apps/api/alembic.ini upgrade head
pytest apps/api/tests tests/e2e/test_smoke.py
ruff check apps/api
mypy apps/api/src
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
docker compose up -d
docker compose ps
```

O profile `openwa` não faz parte do gate da Fase 0. O endpoint `/health` deve
mostrar PostgreSQL, Redis e worker saudáveis; OpenWA pode permanecer inativo.

### API inicial da Fase 1

Configure `OWNER_AUTH_TOKEN` somente no ambiente local/cofre. O adapter local
expõe `POST /auth/login`, `GET /auth/me`, `POST /simulator/messages` e
`GET /simulator/conversations/{conversation_id}/messages`. O simulador exige
Bearer token, valida o `tenant_id` contra o proprietário, persiste a mensagem
e audit log e trata reentrega pelo mesmo `idempotency_key` sem duplicar dados.

### Schema do núcleo CRM

A migração `0002_core_crm` cria `tenants`, `users`, `contacts`, `conversations`,
`conversation_control` e `messages`. O diagrama, as regras de deleção, os
índices e os comandos de upgrade/rollback estão em
[`ADR-010`](./docs/architecture/adr-010-core-crm-schema.md).

### Pendências e alertas (Fase 4)

Pendências são persistidas em `pending_items` e seus alertas em
`pending_notifications`. A criação agenda o alerta imediato; o worker repete a
cada duas horas até resposta efetiva ou resolução explícita. Claims usam lease
e `SKIP LOCKED`, e a janela `(tenant_id, pending_item_id, window_index)` é
idempotente, inclusive depois de downtime. Abrir um e-mail nunca resolve a
pendência. Configure `OWNER_ALERT_EMAIL` somente no ambiente local/cofre; o
desenvolvimento usa `FakeEmailProvider` e não envia e-mail real. Detalhes,
rollback da migração e bloqueio do provedor estão no
[ADR-016](./docs/architecture/adr-016-pending-alerts.md).

### Propostas reproduzíveis (Fase 5 — fatia em execução)

`POST /proposals` recebe um `ProposalDraft` tipado, mas preço, prazo, revisões,
escopo e itens são sempre resolvidos pelo catálogo ativo no servidor. Divergência
vira `HUMAN_APPROVAL_REQUIRED`, sem PDF ou envio. Propostas válidas guardam
hash, versões e dados usados; reenvio com a mesma chave é idempotente e a mesma
 chave com dados diferentes falha. Consulte o [ADR-017](./docs/architecture/adr-017-reproducible-proposals.md).

O aceite comercial está em `POST /commercial/proposals/{proposal_id}/accept`.
Sem template/link configurados, o pedido permanece em `CONTRACT_PENDING` ou
`PAYMENT_LINK_PENDING` e cria pendência. Apenas webhook de pagamento assinado,
com valor compatível e evento idempotente, libera `ONBOARDING_READY`. Consulte
o [ADR-018](./docs/architecture/adr-018-acceptance-contract-payment.md).

### Pesquisa pública de prospecção (Fase 6)

`POST /prospects/research` recebe somente URL pública, segmento
`ESTHETIC_CLINIC` e chave de idempotência. A API nunca confia no `tenant_id` do
cliente, consulta o serviço interno `scrapegraph`, persiste o resultado
estruturado e o marca `PENDING_REVIEW`; nenhuma primeira mensagem é enviada por
esta fase. O serviço limita DNS/SSRF, redirects, bytes, timeout e requisições
por domínio. Páginas são dados não confiáveis, não instruções.

O cache tenant-scoped usa a URL normalizada e TTL configurável. O adapter pode
usar Gemini somente quando `SCRAPEGRAPH_LLM_PROVIDER=gemini` e
`GEMINI_API_KEY` estiverem configurados no ambiente; a chave nunca vai para
Git, resposta ou log. Sem integração configurada, o fake/testes e a extração
local limitada permitem validar o contrato. Consulte o
[ADR-020](./docs/architecture/adr-020-prospect-research.md).

### Fila de aprovação de prospecção

`POST /outreach/drafts` cria um rascunho a partir de uma pesquisa revisável.
Empresa, origem, evidências, até três achados e contato são copiados do
resultado persistido; o cliente não consegue sobrescrever esses campos. A
fila oferece listagem, edição, aprovação explícita, rejeição, opt-out e envio.

O envio exige uma aprovação vigente e hashes iguais da pesquisa, mensagem e
número. Opt-out, aprovação expirada, alteração do número, erro de sessão,
duplicidade ou limite conservador bloqueiam/pauseiam no backend. O outbox é
persistido antes do gateway e a chave de envio é idempotente. O provider padrão
é fake; OpenWA real é opt-in e permanece interno. Detalhes no
[ADR-021](./docs/architecture/adr-021-cold-outreach-approval.md).

---

## 🔒 Segurança do Gateway OpenWA

Conforme estabelecido no [`AGENTS.md`](./AGENTS.md) e no [ADR-009](./docs/architecture/adr-009-adopt-openwa-gateway.md):
- O checklist verificável de hardening está em [`docs/openwa-hardening-checklist.md`](./docs/openwa-hardening-checklist.md).
- A configuração declara `ghcr.io/rmyndharis/openwa:0.23.3@sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec`; a ativação AWS exige
  digest SHA-256 oficial; o contrato v0.23.3 foi validado localmente.
  registry GHCR oficial consultado; a imagem esta disponivel.
  O smoke real continua pendente por nao haver deploy autorizado.
- O contêiner opera unicamente na rede bridge interna (`ks-internal`), **sem mapear portas públicas no host** (portas de API/Swagger inacessíveis externamente).
- O gateway cuida unicamente de sessão, recepção de webhooks e envio; inteligência, regras de negócio e controle humano permanecem isolados na API da KaelSolutions.

O roteamento por shard, ownership exclusivo, lease e fencing token está
documentado em [`docs/channel-router.md`](./docs/channel-router.md).

---

## 📦 Estrutura do Repositório

```text
├── apps/
│   ├── api/             # FastAPI, Pydantic Settings, SQLAlchemy e rotas de saúde
│   ├── web/             # Next.js 14, React 18, TypeScript, Dashboard de status
│   └── worker/          # Processamento de filas Redis assíncrono com heartbeat
├── services/
│   └── scrapegraph/     # Serviço isolado para prospecção pública
├── packages/
│   └── contracts/       # Schemas de eventos, enums e contratos tipados
├── docs/
│   └── architecture/    # ADRs de 001 a 016
└── tests/
    └── e2e/             # Smoke tests e testes de ponta a ponta
```
