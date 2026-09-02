# ADR-007: ScrapeGraphAI Auto-hospedado em Serviço Isolado

## Status
Aceito em 31 de agosto de 2026.

## Contexto
A prospecção assistida de estabelecimentos comerciais (inicialmente clínicas de estética) requer extração estruturada de informações a partir de páginas web públicas. ScrapeGraphAI possui dependências pesadas de scraping e navegadores headless (Playwright/Chromium) que podem onerar ou desestabilizar a API principal.

## Decisão
Auto-hospedar o **ScrapeGraphAI em contêiner/serviço isolado (`services/scrapegraph`)**:
- Acesso exclusivamente via contrato interno REST autenticado.
- Nenhum disparo de prospecção pode ser automático: toda primeira mensagem gerada é enfileirada para aprovação humana obrigatória.
- Proibição estrita de bypass de CAPTCHA evasivo, disparo massivo ou coleta de dados privados.

## Consequências
- A carga de raspagem de dados web não afeta o desempenho e a latência do CRM em tempo real.
- Facilidade de desligamento ou pausa do serviço de prospecção sem impacto no atendimento aos clientes existentes.
