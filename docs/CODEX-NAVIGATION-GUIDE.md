# Guia de navegação e evidência para o Codex

Este documento complementa o `AGENTS.md`. Ele descreve onde encontrar a fonte
de verdade do projeto, quem é responsável por cada fronteira e como montar um
pacote de evidência reproduzível para uma alteração. Não substitui as regras
de segurança, privacidade, operação ou aprovação do `AGENTS.md`.

## Ordem de leitura

Antes de editar, leia integralmente:

1. [`AGENTS.md`](../AGENTS.md), que é a norma principal do repositório.
2. [`docs/KS-Atendimento-IA-Plano-Mestre-e-Prompts.docx`](./KS-Atendimento-IA-Plano-Mestre-e-Prompts.docx), para a fase e os critérios de aceite.
3. Os ADRs aplicáveis em [`docs/architecture/`](./architecture/).
4. [`README.md`](../README.md), changelog e o documento de fechamento da fase.
5. O estado real do Git, arquivos de configuração, migrações e testes
   relacionados à fatia.

Se a documentação divergir do código, registre a divergência no resultado da
inspeção e corrija documentação ou implementação conforme a hierarquia do
`AGENTS.md`. Não trate arquivos gerados, caches ou relatórios locais como
fonte normativa.

## Mapa do monorepo

| Área | Responsabilidade | Pontos de entrada |
|---|---|---|
| `apps/api/src/` | API FastAPI, domínio e integrações | `main.py`, `api/`, módulos de domínio e `integrations/` |
| `apps/api/src/integrations/` | Fronteiras substituíveis de provedores | `whatsapp.py` e `channel_router.py` |
| `apps/api/src/db/` | Modelos e acesso ao banco | `models.py` |
| `apps/api/alembic/versions/` | Evolução versionada do esquema | `0001` a `0014_channel_router` |
| `apps/worker/src/` | Debounce, jobs e processamento assíncrono | `worker.py`, `grouping.py` |
| `apps/web/src/` | CRM e inbox | `app/page.tsx`, `app/Inbox.tsx` |
| `packages/contracts/` | Contratos compartilhados | `ks_contracts/` e `types.ts` |
| `services/scrapegraph/` | Serviço isolado de pesquisa pública | `src/main.py` |
| `deploy/aws/` | Compose, Caddy, health check, backup e restore | `docker-compose.aws.yml`, `scripts/` |
| `tests/` | Integração, hardening, E2E fake e avaliação | arquivos `test_*.py`, `e2e/`, `eval/` |
| `docs/` | ADRs, runbooks, critérios e evidências | `architecture/`, `operations/` |

## Ownership das fronteiras críticas

- O domínio da KaelSolutions é dono de tenant, CRM, mensagens, outbox,
  auditoria, handoff e regras comerciais.
- `WhatsAppAdapter` é a interface de domínio para o WhatsApp. Código de
  domínio não deve importar OpenWA, `whatsapp-web.js` ou Baileys diretamente.
- `ChannelRouter` resolve o shard no servidor e é a última fronteira antes da
  entrega à outbox. Toda rota valida `tenant_id`, relê ownership e usa lease,
  epoch e fencing token.
- PostgreSQL é a fonte de verdade; Redis serve para estado efêmero, locks,
  debounce e filas. O schema do gateway não é consultado pelo domínio.
- O volume de sessão do OpenWA é dado sensível e pertence exclusivamente ao
  gateway. Nunca deve entrar no Git, em artefato de CI ou em suporte.
- Caddy é a única borda pública prevista no Compose AWS. API, dashboard,
  Swagger, OpenWA, banco e Redis permanecem em rede interna conforme o
  hardening documentado.

## Como investigar uma tarefa

1. Identifique a fase, o objetivo e os critérios de aceite no plano mestre e
   no fechamento da fase.
2. Localize o contrato público e a implementação com `rg`; siga as chamadas
   até a fronteira externa.
3. Verifique migrações, constraints, isolamento por tenant, idempotência,
   logs e auditoria antes de alterar código.
4. Escreva ou ajuste primeiro o teste que demonstra o risco da mudança.
5. Faça a menor fatia vertical que preserve os contratos existentes.
6. Execute testes focados e, quando viável, a suíte, lint, typecheck e
   auditoria de dependências.
7. Revise `git diff` para escopo, segredos, PII, portas públicas e mudanças de
   configuração.

Para alterações de banco, a migração deve ser criada junto com os modelos e
testes. Para alterações de gateway, consulte também
[`docs/openwa-hardening-checklist.md`](./openwa-hardening-checklist.md),
[`docs/channel-router.md`](./channel-router.md) e os ADRs 009 e 014.

## Pacote mínimo de evidência

O relatório de uma tarefa deve informar:

- fase, objetivo e critérios de aceite;
- arquivos alterados e motivo de cada alteração;
- migrações executadas ou pendentes;
- comandos exatos e resultado dos testes;
- verificações de configuração e de exposição de rede;
- divergências entre documentação e código;
- limitações, bloqueios e a primeira tarefa segura restante.

Use caminhos relativos no texto e preserve os artefatos reproduzíveis em
`docs/` ou `tests/`. Saídas temporárias ficam fora do Git: `analysis/`,
`graphify-out/`, `var/`, `test-results/`, caches, dependências instaladas e
builds do frontend.

## Git e limites de ação

O primeiro commit local do repositório é o baseline contra o qual mudanças
posteriores devem ser comparadas. Antes de criar ou atualizar um commit:

1. confirme `git status --short`;
2. verifique os arquivos ignorados e procure segredos/PII;
3. adicione somente código, testes, configuração e documentação aprovados;
4. execute `git diff --cached --check` e revise o diff staged;
5. confirme `git log --oneline -1` e `git diff HEAD` após o commit. Para
   inspecionar o conteúdo de um root commit, use `git diff --root HEAD`;
   `HEAD^` só existe depois que houver um commit pai.

Baseline local não autoriza push, pull request, deploy, alteração em AWS,
DNS, credenciais, serviços de terceiros ou pareamento de WhatsApp. Essas ações
exigem autorização explícita. Este repositório também não deve conter número
real, QR, credencial ou cópia de sessão.
