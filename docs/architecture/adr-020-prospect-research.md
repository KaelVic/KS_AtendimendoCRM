# ADR-020: Pesquisa pública isolada e revisável

## Status

Aceito em 31 de agosto de 2026.

## Contexto

A Fase 6 precisa preparar pesquisas de clínicas de estética a partir de fontes
públicas. Uma página pode conter instruções maliciosas, redirecionar para redes
internas ou consumir recursos excessivos. A pesquisa também não pode iniciar
contato sem aprovação humana.

## Decisão

- `services/scrapegraph` é um serviço separado, com ScrapeGraphAI instalado,
  acessível somente pela rede Docker interna.
- A fronteira faz allowlist de HTTP/HTTPS, resolve DNS e bloqueia loopback,
  redes privadas, link-local, metadata endpoints, credenciais na URL e portas
  não permitidas. Redirects são limitados e validados novamente.
- O download é limitado por streaming a `SCRAPEGRAPH_MAX_PAGE_BYTES`, com
  timeout e rate limit por domínio. CAPTCHA, autenticação e bypass não fazem
  parte do contrato.
- O parser considera o HTML como `DATA`: scripts são ignorados, conteúdo com
  marcadores de instrução não vira nome/achado e nenhum texto da página é uma
  instrução de sistema.
- A API acessa o serviço via `ProspectResearchAdapter`. O resultado é validado,
  deduplicado por tenant e URL normalizada, cacheado por TTL e persistido como
  `PENDING_REVIEW`. Falhas persistem estado `FAILED` sem inventar evidência.
- Gemini, quando habilitado, recebe somente texto limitado e sanitizado; sua
  chave vem exclusivamente de `GEMINI_API_KEY`. Sem chave/configuração, a
  extração local limitada permanece disponível para desenvolvimento e revisão.

## Consequências

O histórico do CRM não depende do banco ou schema do ScrapeGraphAI, e o serviço
pode ser desligado sem afetar o atendimento. O parser local é conservador e
pode deixar campos vazios; isso é preferível a fabricar dados. A aprovação da
primeira abordagem é uma fase posterior e não é implementada aqui.

## Rollback

Remova o endpoint/worker de pesquisa e faça `alembic downgrade 0011_calendar_meetings`.
Os dados de CRM anteriores permanecem; pesquisas da tabela removida devem ser
exportadas somente por procedimento autorizado antes do downgrade.
