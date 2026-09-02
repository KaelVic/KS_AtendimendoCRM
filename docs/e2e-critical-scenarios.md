# Evidência dos cenários críticos

Este documento registra como executar os cenários críticos com dados sintéticos.
Os testes não usam contatos reais, não pareiam WhatsApp e não enviam mensagens
externas.

## Execução

```bash
pytest -q apps/api/tests apps/worker/tests services/scrapegraph/tests tests/e2e
```

Os testes em `tests/e2e` escrevem um JSON por caso em `test-results/e2e/` com
`correlation_id`, passos, duração, resultado, logs saneados e indicação de
screenshot. Esse diretório é ignorado pelo Git. O workflow de CI publica os
artefatos mesmo quando um teste falha.

O smoke real é opt-in e controlado:

```bash
E2E_REAL=1 API_URL=http://localhost:8000 WEB_URL=http://localhost:3000 \
  pytest -q tests/e2e/test_smoke.py
```

Ele verifica liveness, PostgreSQL/Redis/worker, caminho web → API → banco e,
quando `OPENWA_URL` é informado, saúde do profile OpenWA. O teste de exposição
nega acesso ao endpoint no host. Nenhuma sessão ou contato real é necessário.

## Matriz de cobertura

| Cenário do AGENTS.md | Evidência | Dados/limite |
|---|---|---|
| Fragmentos, teto de 25 s e lock | `apps/worker/tests/test_grouping.py` | Redis fake, relógio determinístico |
| Áudio, imagem e prompt injection em mídia | `apps/api/tests/test_media_pipeline.py` | bytes, EXIF e transcrição sintéticos |
| Controle humano durante geração/outbox | `apps/api/tests/test_control_state_machine.py` | store/gateway fake, concorrência |
| LLM inválido, reparo e fallback | `apps/api/tests/test_llm.py` | provider fake, sem chave |
| Pendência imediata/2 h/retry/downtime | `apps/api/tests/test_pending.py` | e-mail fake, janelas idempotentes |
| Proposta reproduzível e PDF golden | `apps/api/tests/test_proposals.py`, `test_proposal_service.py` | catálogo/template fixos |
| Aceite, pagamento e webhook | `apps/api/tests/test_commercial_flow.py` | assinatura e eventos sintéticos |
| Agenda, DST, corrida e lembrete | `apps/api/tests/test_calendar.py` | calendário fake, `America/Sao_Paulo` |
| Scraping/SSRF/redirect/página grande | `services/scrapegraph/tests/test_main.py` | fontes públicas sintéticas |
| Aprovação de primeira mensagem/opt-out | `apps/api/tests/test_outreach_approval.py`, `test_api_outreach.py` | contato sintético |
| HMAC, replay e persistência antes do processamento | `tests/e2e/test_openwa_flows.py` | gateway OpenWA fake |
| Restart, sessão persistente e reentrega idempotente | `tests/e2e/test_openwa_flows.py` | volume/receipt sintéticos |
| Owner único e concorrência de sessão | `tests/e2e/test_openwa_flows.py` | dois adapters, mesma sessão |
| Upgrade/rollback preservando histórico | `tests/e2e/test_openwa_flows.py` | volume, mídia e CRM fake |
| Inbox receber/enviar/assumir/devolver | `tests/e2e/test_inbox_ui.py` | API mockada no browser |

Os testes de domínio listados acima são a evidência determinística para os
fluxos ainda sem stack externa. A cobertura E2E real permanece condicionada ao
ambiente: `E2E_REAL=1`, Docker/serviços saudáveis e browser Playwright instalado.
Um skip controlado não é contado como gate aprovado.

## Resultado observado nesta execução

- Suíte Python: passou com os testes de API, worker, ScrapeGraph e E2E fake.
- OpenWA fake: 4 cenários passaram.
- Smoke real: não executado, pois o Docker Engine local não estava acessível.
- Inbox UI: ficou skip controlado porque o browser Playwright não estava
  disponível; portanto nenhum screenshot UI foi produzido.

Para repetir com evidência real, subir a stack em ambiente autorizado, instalar
o browser Playwright e executar o comando opt-in acima. A sessão OpenWA deve
continuar no profile interno, sem porta publicada e sem pareamento.
