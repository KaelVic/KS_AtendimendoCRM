# Checklist verificavel - OpenWA v0.23.3

Este checklist nao autoriza pareamento, envio externo ou deploy. O piloto usa
somente uma sessao sintetica em testes.

## Controles versionados

- [x] Imagem oficial `ghcr.io/rmyndharis/openwa:0.23.3` fixada no digest
  multiarch `sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec`;
  `latest` e rejeitado pelo helper AWS.
- [x] OpenWA nao possui `ports` nem `expose`; a porta 2785 fica apenas na
  rede interna `ks-openwa`, acessivel pelo backend.
- [x] API e OpenWA sao os unicos membros de `ks-openwa`, que e `internal: true`.
- [x] Swagger e dashboard sao desabilitados no gateway e os caminhos
  `/api/docs*`, `/api/openapi.json` e `/dashboard*` retornam 404 no Caddy.
- [x] A configuracao exige API master key, API key, pepper e webhook secret
  fora do Git; as tres chaves operacionais tem minimo de 32 caracteres.
- [x] A chave de integracao usa role `operator`, uma sessao exata e a CIDR
  privada `172.30.0.0/24`.
- [x] Autorespostas, MCP, plugins, redirects inseguros e Docker socket estao
  desabilitados.
- [x] Root filesystem read-only, tmpfs restrito, no-new-privileges, capacidades
  oficiais minimas para bootstrap, limite de PID/memoria/shm e log rotation.
- [x] Volume de sessao exclusivo em `/app/data`; nenhum outro servico o monta.
- [x] Body, payload de webhook, concorrencia, rate limits HTTP e WebSocket sao
  configurados explicitamente.
- [x] HMAC-SHA256 constant-time cobre os bytes exatos. O formato oficial
  body-only e aceito; o envelope interno KS cobre `timestamp.nonce.body`,
  valida janela de 5 minutos e nonce com replay store.
- [x] O adapter usa `/api/health/live`, `/api/health/ready`,
  `/api/sessions/{id}` e `/api/sessions/{id}/messages/send-*`, com `X-API-Key`.
  Texto respeita o limite oficial de 4096 bytes e receipt exige `messageId`.
- [x] Logs do backend redigem segredos, sessoes, QR, telefones e excecoes;
  mensagens e payloads nao sao registrados.

## Testes e evidencias

- [x] Contract tests estaticos validam imagem, digest, portas, redes, flags,
  endpoints, headers, payloads, HMAC, replay e receipts.
- [x] Testes ChannelRouter cobrem corrida, lease expirado, indisponibilidade,
  tenant divergente, reatribuicao e split-brain com fencing.
- [x] `tests/e2e/test_smoke.py` verifica que a interface publica nao responde
  na porta interna 2785; com `E2E_REAL=1` ele deve ser executado em ambiente
  descartavel autorizado.

## Pendencias operacionais que nao podem ser marcadas como concluidas

- [ ] Criar chaves reais em cofre com permissao minima; nenhum segredo real
  entra nesta tarefa.
- [ ] Provar em ambiente descartavel o boot/restart real do Chromium com o
  volume `/app/data`, backup/restore, QR/relink, receipts e recuperacao.
- [ ] Provar criptografia do volume e dos backups na infraestrutura escolhida.
- [x] `OPENWA_LOG_LEVEL=error` foi configurado para suprimir o `warn` de
  bootstrap que imprimia a API master key; smoke descartavel confirmou
  `SECRET_LOG_LEAK=False`. Revalidar esse controle em toda troca de imagem.

Evidencia automatizada local:

```text
python -m pytest -q tests/test_openwa_hardening.py tests/test_deploy_aws.py apps/api/tests/test_whatsapp_adapter.py apps/api/tests/test_channel_router.py
```
