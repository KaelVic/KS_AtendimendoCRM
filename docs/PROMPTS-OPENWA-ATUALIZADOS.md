# Prompts atualizados — OpenWA no KS Atendimento IA

> Revisão 1.2 — 31 de agosto de 2026. Todos os prompts estão prontos para copiar e colar sem alterar campos. Leia `AGENTS.md` integralmente e execute o Prompt 00 do plano mestre antes de qualquer prompt deste arquivo. Nunca cole segredos.

Este pacote contém os prompts alterados ou adicionados após a escolha do OpenWA como gateway padrão do piloto e dos primeiros clientes comerciais. A biblioteca completa permanece no documento Word `KS-Atendimento-IA-Plano-Mestre-e-Prompts.docx`.

## Prompt 03 — Scaffold do monorepo com profile OpenWA

```text
Crie o monorepo do KS Atendimento IA com apps/web, apps/api, apps/worker, services/scrapegraph, packages/contracts, docs/architecture e tests/e2e.

Requisitos:
- Next.js/TypeScript no web e FastAPI/Python na API;
- PostgreSQL e Redis via Docker Compose;
- worker Redis, health checks e configuração validada;
- profile `openwa` preparado com imagem v0.23.3 fixada, rede interna e volumes nomeados, mas sem sessão real;
- .gitignore cobrindo .env, sessões, mídia e credenciais;
- .env.example sem valores secretos;
- comandos únicos para instalar, subir, testar, lintar e parar;
- CI mínima;
- README com início rápido;
- ADRs 001–009.

Não adicione Gemini nem pareie WhatsApp real nesta tarefa. Entregue um smoke test que prove web → API → banco e, no profile opcional, health do OpenWA sem expor sua API publicamente.
```

## Prompt 10 — Adapter OpenWA/WhatsApp

```text
Implemente o WhatsAppAdapter para OpenWA v0.23.3, preservando independência completa do domínio. Fixe a imagem por versão e, quando possível, digest; nunca use `latest`.

Mapeie QR/sessão, relink, status de conexão, webhook inbound, deduplicação, texto, imagem, áudio, documento, receipt e erro. Valide HMAC sobre os bytes exatos, rejeite replay e persista o evento antes de processar. Use outbox para envio e idempotency key. Não use automações/autorespostas internas do OpenWA. Nunca inclua disparo massivo, aquecimento, evasão ou rotação. Exponha health, versão e ownership da sessão no CRM e interrompa envio se ela estiver insegura, sem owner ou desconectada.

Execute inicialmente com whatsapp-web.js e uma única instância proprietária da sessão. Mantenha Baileys como fallback condicionado a contract tests. Adicione fake gateway e contract tests para payloads, erros, mídia, HMAC, reentrega e reconexão. Documente risco de bloqueio e substituição do adapter.
```

## Prompt 22 — Testes E2E incluindo OpenWA

```text
Implemente e execute os cenários críticos do AGENTS.md usando serviços fake quando necessário e pelo menos um smoke test real controlado.

Inclua especificamente:
1. HMAC inválido, expirado ou repetido é rejeitado.
2. Webhook duplicado não duplica mensagem nem resposta.
3. Reinício recupera sessão sem perder histórico.
4. HUMAN_ACTIVE impede envio que já estava em processamento.
5. QR/relink aparece somente para proprietário autenticado.
6. Texto, áudio, imagem e PDF funcionam nos dois sentidos.
7. Uma sessão não pode possuir dois owners ativos.
8. Rollback preserva sessão, mídia e histórico principal.

Capture passos, dados, resultado, tempo e logs correlacionados. Não use contatos reais em testes automatizados nem envie primeira mensagem externa.
```

## Prompt 23 — Deploy econômico com OpenWA na AWS

```text
Planeje e implemente deploy econômico do piloto na AWS usando créditos existentes e uma única VM com Docker Compose, sem RDS, NAT Gateway, ALB ou serviços caros.

Inclua estimativa de consumo, tags, budget alerts, disco criptografado, TLS, firewall mínimo, usuário não-root, secrets fora do Git, backup para S3, restore, health checks, restart, logs e rollback. Mantenha OpenWA, seu dashboard e Swagger somente na rede interna; proteja o volume de sessão, valide HMAC e fixe versão/digest. Não crie nem modifique recurso remoto sem aprovação explícita do proprietário. Produza runbook com comandos exatos e validação pós-deploy.
```

## Prompt 24 — Observabilidade OpenWA

```text
Implemente observabilidade mínima para API, banco, Redis, worker, Gemini, OpenWA, sessão WhatsApp, e-mail e calendário.

Use correlation_id do webhook ao envio. Meça latência p50/p95, erro, fila, sucesso de ferramentas, escalonamento, duplicação e uso de modelo sem registrar conteúdo sensível. Por sessão OpenWA, meça owner/shard, conexão, relink, último webhook, último receipt, reinício, memória e versão.

Crie health/readiness, alertas acionáveis e runbooks para: sessão desconectada, relink, conflito de owner, Gemini sem cota, worker parado, banco cheio, envio duplicado e backup falho.
```

## Prompt 28 — Hardening do OpenWA

```text
Faça o hardening do OpenWA v0.23.3 conforme AGENTS.md.

Requisitos obrigatórios:
- imagem fixada por tag e, se disponível, digest; nunca `latest`;
- serviço sem porta pública, acessível somente pelo backend na rede interna;
- dashboard e Swagger desabilitados ou inacessíveis externamente;
- API_MASTER_KEY forte, API_KEY_PEPPER, chave de integração com role mínimo, allowedSessions e allowedIps;
- HMAC-SHA256 nos webhooks, comparação constant-time, timestamp/nonce e proteção contra replay;
- autorespostas, plugins e Docker socket desabilitados quando não necessários;
- PostgreSQL/Redis separados por database, usuário e namespace;
- volume exclusivo de sessão, permissões mínimas, criptografia de infraestrutura e backup protegido;
- limites de payload, mídia, webhooks e rate limiting revisados;
- logs sem chave, sessão, QR, telefone completo ou conteúdo desnecessário.

Produza checklist verificável, testes automatizados de configuração e evidência de que API/dashboard não respondem pela interface pública. Não pareie número real nesta tarefa.
```

## Prompt 29 — ChannelRouter e ownership de sessão

```text
Implemente ChannelRouter sem alterar a interface de domínio do WhatsAppAdapter.

Modele gateway_shards, channel_sessions e session_assignments com tenant_id, gateway_id, external_session_id, engine, status, owner_epoch, lease_expires_at e versão. Cada sessão pode ter somente um owner ativo. Toda rota de envio resolve o shard no servidor, valida tenant e relê ownership antes de entregar à outbox.

Implemente lease/lock, fencing token, transição auditada, health do shard e falha segura. Não tente manter a mesma sessão conectada em duas instâncias. Migração exige pausa de envio, drain da outbox, backup, parada do owner anterior, restauração/relink, novo epoch e smoke test.

Adicione testes de corrida, lease expirado, shard indisponível, tenant divergente, reatribuição e split-brain. Para o piloto, configure apenas um shard e uma sessão.
```

## Prompt 30 — Upgrade e rollback do OpenWA

```text
Identifique no Docker Compose e nos arquivos de configuração a versão/digest do OpenWA atualmente fixada. Consulte somente as fontes oficiais do projeto para descobrir a versão estável mais recente. Planeje a atualização entre essas duas versões, mas não altere produção nem o arquivo fixado nesta tarefa.

Leia release notes, changelog, matriz de capacidades, security policy e alterações de OpenAPI. Compare os endpoints/payloads realmente usados pelo nosso WhatsAppAdapter. Liste breaking changes, migrações, alterações dos motores e riscos de sessão.

Crie ambiente descartável com cópia protegida/anônima da configuração, rode contract tests, mídia, HMAC, QR/relink, receipts, restart e recuperação. Defina backup, janela, drain, verificação pós-upgrade e rollback para a versão/digest anterior. A atualização só pode ser aprovada se preservar histórico do CRM, idempotência e recuperação da sessão.
```

## Prompt 31 — Recuperação de sessão OpenWA

```text
Identifique pela tela de saúde, banco e logs estruturados a sessão OpenWA configurada que esteja desconectada, em relink_required ou com falha. Execute o runbook de recuperação sem expor credenciais ou QR em logs. Se nenhuma sessão real estiver configurada ou com falha, execute o mesmo fluxo como exercício usando o fake gateway e dados de teste.

1. Pause novas saídas e mantenha inbound/outbox em estado recuperável.
2. Registre incidente, tenant, shard, versão, último webhook e último receipt.
3. Verifique owner único, health, volume e causa provável.
4. Tente restart controlado apenas uma vez quando seguro.
5. Se houver relink_required, gere QR/pairing somente na tela autenticada do proprietário.
6. Confirme READY, execute smoke test controlado e reconcilie eventos por idempotency key.
7. Libere a fila gradualmente e monitore duplicação/latência.
8. Se falhar, restaure backup ou migre de shard seguindo fencing token e rollback.

Nunca inicialize simultaneamente a mesma credencial em dois gateways. Produza linha do tempo, evidências, mensagens afetadas e ação preventiva.
```

## Prompt 32 — Gate comercial do conector

```text
Avalie todos os tenants configurados que ainda não possuam gate comercial aprovado. Se ainda não houver tenant persistido, avalie a configuração planejada da KaelSolutions como tenant piloto sem criar dados de produção.

Verifique: contrato informa natureza não oficial e risco de bloqueio; número dedicado; opt-out; limites; tenant/session isolation; chave restrita; HMAC; volume criptografado; backup e restauração; QR/relink; owner único; health/alertas; versão fixada; contract tests; histórico independente do gateway; suporte e runbook; teste de mídia; handoff; duplicação; indisponibilidade.

Retorne APROVADO, APROVADO COM RISCO EXPLÍCITO ou NÃO APROVADO. Para cada falha, inclua evidência, impacto, correção e responsável. Não ative sessão, envie mensagem ou altere infraestrutura durante esta auditoria.
```

## Ordem recomendada

1. Prompt 03 — scaffold.
2. Prompt 28 — hardening sem número real.
3. Prompt 10 — adapter e fake gateway.
4. Prompt 22 — testes E2E/contract tests.
5. Parear o número dedicado.
6. Prompt 24 — observabilidade.
7. Prompt 23 — deploy, somente após aprovação explícita.
8. Prompt 32 — gate comercial para cada cliente.
9. Prompts 29–31 quando houver vários clientes, upgrade ou incidente.
