# Gate operacional e comercial do OpenWA

Este procedimento é obrigatório antes de `OPENWA_COMMERCIAL_USE=1`. Ele não
pareia número, não envia mensagem e não imprime QR nos logs.

## Evidência não sensível

Use `scripts/validate_openwa_gate.py` com um manifesto que contenha apenas
booleans e referências a evidências. Não coloque segredos, QR, cookies,
mensagens, telefones ou payloads no manifesto. O comando retorna
`APPROVED` somente com todos os controles e aprovação do proprietário.

```bash
python scripts/validate_openwa_gate.py <manifesto-sem-segredos>.json
```

O SHA-256 do manifesto aprovado deve ser colocado no cofre como
`OPENWA_GATE_EVIDENCE_SHA256`. O Compose verifica esse hash em conjunto com
`OPENWA_COMMERCIAL_GATE_APPROVED=1` e bloqueia uso comercial sem ambos.

## Sequência de aceitação

1. Aprovar o termo em `docs/legal/openwa-commercial-addendum.md`.
2. Registrar referência segura do número dedicado; nunca registrar o número no
   Git, tags, logs ou manifesto.
3. Criar chaves no cofre com role `operator`, sessão única e allowlist privada.
4. Executar `verify-storage-encryption.sh` com role somente leitura e guardar
   apenas o resultado agregado.
5. Executar backup, checksum e restore em ambiente isolado; conferir contagens
   e idempotency keys sem exportar conteúdo.
6. Executar contract tests contra a imagem/digest fixados, incluindo Chromium,
   receipts, mídia, restart e recuperação. O fake não é evidência suficiente.
7. Validar QR/relink somente na tela autenticada do proprietário. Uma sessão
   nunca pode ser iniciada em dois gateways.
8. Validar health, alertas, handoff, opt-out, pausa por indisponibilidade e
   rollback; liberar a fila gradualmente e observar duplicação/latência.
9. Assinar o manifesto, registrar correlação e aprovação; só então habilitar o
   uso comercial.

## Operação e suporte

- Owner operacional: proprietário da KaelSolutions até definição diferente.
- Incidente: pausar novas saídas, preservar inbound/outbox, registrar
  tenant/shard/versão/último webhook/receipt sanitizados e abrir pendência.
- Relink: fazer backup antes, parar qualquer owner concorrente e mostrar QR
  apenas ao proprietário autenticado.
- Restore/migração: exigir fencing token, drain, backup, owner anterior parado,
  smoke e rollback documentado.
- Sucesso de backup exige checksum e restore verificado; upload iniciado não é
  evidência de proteção.
- Auditoria multi-tenant: execute `python scripts/audit_openwa_gate.py`. O
  comando avalia todos os manifestos locais; se não houver tenant persistido,
  usa o piloto planejado da KaelSolutions sem criar dados de produção.
- A saída de cada falha contém somente evidência esperada, impacto, correção e
  responsável. `APROVED` interno é apresentado como `APROVADO COM RISCO
  EXPLÍCITO`; o gate permanece fechado para qualquer falha.
