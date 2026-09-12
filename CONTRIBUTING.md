# Guia de Desenvolvimento Interno — KS Atendimento IA

Este documento reúne os padrões de engenharia e diretrizes de desenvolvimento interno para o time da **KaelSolutions** trabalhando no **KS Atendimento IA**.

---

## 1. Antes de Começar

1. Leia [`CLAUDE.md`](CLAUDE.md) — convenções de código e regras não-negociáveis.
2. Leia [`ARCHITECTURE.md`](ARCHITECTURE.md) — visão técnica da arquitetura e fluxos.
3. Identifique o épico ou tarefa de trabalho em [`docs/stories/epics/MASTER.md`](docs/stories/epics/MASTER.md).

---

## 2. Fluxo de Trabalho e Branches

### Padrão de Nomenclatura de Branches

```bash
feat/EPIC-XX-short-slug         # nova funcionalidade
fix/EPIC-XX-short-slug          # correção de bug
chore/short-slug                # manutenção, dependências, configs
docs/short-slug                 # documentação técnica
```

### Padrão de Commits

Utilizamos Conventional Commits com escopo explícito sempre que vinculado a um épico:

```
feat(EPIC-04): kanban drag-and-drop com fractional indexing
fix(EPIC-03): cron recover-stuck-messages marcando sending stuck >5min como failed
docs(EPIC-12): mark complete + wave log
```

Mensagens devem ser em português (PT-BR) ou inglês, com tom imperativo e linha de assunto com até 72 caracteres.

---

## 3. Gestão de Épicos e Tarefas

Tarefas estruturais seguem os arquivos em [`docs/stories/epics/`](docs/stories/epics/).

Ao finalizar um épico ou onda de entrega:
1. Atualizar o frontmatter: `status: pending → completed (partial: ...)` ou `status: completed`.
2. Registrar o log de conclusão no final do arquivo correspondente.
3. Atualizar a linha correspondente em `docs/stories/epics/MASTER.md`.

---

## 4. Processo de Pull Request e Definition of Done

1. Criar branch a partir da `main`.
2. Implementar com testes automatizados (unitários para regras de negócio e E2E para fluxos críticos).
3. **Validação Pré-PR:**

   **Verificações obrigatórias de CI:**
   ```bash
   pnpm typecheck && pnpm lint && pnpm lint:channels && pnpm test:unit && pnpm test:shell && pnpm build
   pnpm test:db   # exige Docker; provisiona Postgres limpo e aplica baseline
   ```

   **Critérios de Revisão Técnica (Checklist de Engenharia):**
   - RLS habilitada e policy `tenant_isolation_<tabela>_all` em toda tabela tenant-aware criada.
   - Registro de auditoria (`audit()`) em operações com mutações relevantes.
   - Rate limit configurado para rotas expostas ou públicas.
   - Validação estrita de payload com Zod em todas as rotas de entrada.
   - Proibido `console.log` em código mergeado (utilize sempre `lib/logger.ts`).
   - Novas variáveis de ambiente cadastradas em `.env.example` e em `lib/env.ts` com defaults seguros.
   - Alterações de banco de dados documentadas como tripla obrigatória:
     1. Migration versionada em `supabase/migrations/`
     2. Apêndice idempotente em `supabase/baseline.sql`
     3. Registro no manifesto `supabase/migrations/MANIFEST.md`
   - **Packaging e Deploy:** Alterações em `Dockerfile*`, `docker-compose*.yml` ou scripts de automação devem garantir compatibilidade com ambientes em produção sem exigir intervenções manuais em arquivos de configuração dos servidores.
   - Documentação de PRD/Spec atualizada caso haja alteração de contrato.

4. Submeter PR contra a branch de integração com descrição detalhada e evidências de testes.
5. Todos os status checks do CI (`verify`, `invariants`, `build-and-size`, `e2e`, `imagens-ok`) devem estar verdes.

---

## 5. Anti-patterns Proibidos

Para manter a segurança e integridade do sistema, são estritamente vetados:

- Triggers Postgres realizando chamadas HTTP externas síncronas.
- Uso de `service_role` em route handlers sem filtro explícito por `organization_id`.
- Uso de `getSession()` no backend (utilizar sempre `getUser()`).
- Chaves de API, credenciais ou tokens em query strings.
- Segredos ou tokens armazenados em texto plano no banco de dados.
- Logs com dados sensíveis de clientes (PII, tokens, dados bancários).

---

## 6. Ambiente Local e Suporte Interno

- Instruções para subir o ambiente local de desenvolvimento estão detalhadas em [`docs/SETUP.md`](docs/SETUP.md).
- Dúvidas técnicas ou questões de segurança devem ser direcionadas ao time de engenharia da **KaelSolutions** através dos canais internos ou pelo e-mail: `suporte@kaelsolutions.com.br`.
