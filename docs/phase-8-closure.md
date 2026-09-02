# Fechamento da Fase 8 - Piloto

**Data da verificacao:** 2 de setembro de 2026
**Status:** **NAO APROVADA**
**Fonte normativa:** `AGENTS.md`, plano mestre v1.2 e ADRs aceitos.

## Estado reconstruido

A Fase 8 e a fase atual. As fases 0 a 7 possuem implementacoes locais e
testes, mas nao houve deploy, pareamento, envio externo ou uso de numero real.
O primeiro trabalho seguro pendente era corrigir a divergencia entre a imagem
OpenWA e o contrato oficial; essa correcao foi aplicada nesta sessao.

## Correcao OpenWA aplicada

- Imagem oficial GHCR `ghcr.io/rmyndharis/openwa:0.23.3` fixada pelo digest
  multiarch `sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec`.
- Porta interna 2785, volume exclusivo `/app/data`, sem `ports` ou `expose`.
- Health e adapter alinhados a `/api/health/live`, `/api/health/ready`,
  `/api/sessions/{id}`, `messages/send-*` e header `X-API-Key`.
- Receipts exigem `messageId`; texto respeita 4096 bytes; POST nao e repetido
  automaticamente apos timeout.
- HMAC oficial body-only e envelope KS `timestamp.nonce.body` sao validados
  sobre bytes exatos, com constant-time e replay store.
- `ChannelRouter` permanece a fronteira final: dispatcher nao pode bypassar
  fencing usando `automatic_sender`.
- Capacidades oficiais minimas foram reintroduzidas para permitir chown/drop
  de privilegios no bootstrap com rootfs read-only.

## Evidencia local

- `python -m pytest -q --basetemp .pytest-tmp-full-final`: **150 passed, 8 skipped**.
- Suite focalizada OpenWA/Router: **36 passed**.
- `ruff check` nos fontes/testes afetados: passou.
- `mypy --explicit-package-bases apps/api/src apps/worker/src`: passou.
- `docker compose config --quiet` e `docker compose --profile openwa config --quiet`:
  passaram com configuracao sintetica local.
- Imagem descartavel: readiness 200; `/api/docs`, `/api/openapi.json`,
  `/dashboard` e `/` retornaram 404; `docker port` ficou vazio.
- Restart descartavel no mesmo volume: readiness 200 antes e depois do
  restart; nenhuma porta publicada.
- Com `OPENWA_LOG_LEVEL=error`, `SECRET_LOG_LEAK=False` no smoke descartavel.

## O que continua pendente

- 8 skips sao ambientais: nao representam falha de codigo, mas impedem gate
  completo enquanto nao houver ambiente autorizado.
- Backup/restore real, criptografia de volume, QR/relink e smoke da interface
  publica AWS ainda nao foram executados.
- Chaves reais, tenant/sessao reais, deploy, DNS e AWS continuam proibidos sem
  autorizacao explicita. Nenhum numero real foi pareado.
- `docs/CODEX-NAVIGATION-GUIDE.md` foi criado e versionado neste baseline para
  atender ao suplemento de `AGENTS.md`; a divergencia documental foi resolvida.

O proximo passo seguro e preparar, somente quando autorizado, um ambiente
descartavel com copia protegida e anonima da configuracao para backup/restore
e contract tests adicionais. A fase nao deve ser promovida antes dessas
evidencias operacionais.
