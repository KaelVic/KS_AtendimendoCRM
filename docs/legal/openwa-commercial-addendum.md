# Termo comercial — conector WhatsApp via OpenWA

> Modelo operacional. Deve ser revisado e aprovado pelo proprietário e por
> assessoramento jurídico antes de ser incorporado a qualquer contrato.

## Natureza da conexão

O serviço utiliza WhatsApp Web por meio de um gateway auto-hospedado não
oficial. A conexão não é a API oficial do WhatsApp. A plataforma pode
desconectar, limitar ou bloquear a sessão ou o número, inclusive sem aviso
prévio. A KaelSolutions não promete disponibilidade contínua, desbloqueio ou
risco zero de bloqueio.

## Número e escopo

Cada implantação deve usar número dedicado, sob responsabilidade definida no
contrato, e uma sessão vinculada a exatamente um `tenant_id` e um shard. Não é
permitido compartilhar credencial, sessão ou número entre tenants.

## Mensagens e opt-out

O cliente pode solicitar interrupção a qualquer momento. O pedido é registrado
e impede novas mensagens automatizadas. A primeira mensagem de prospecção exige
aprovação humana; são proibidos disparo massivo, aquecimento, evasão de limites
e rotação para evitar bloqueio.

## Limites e continuidade

Aplicam-se limites conservadores de frequência, payload, mídia e concorrência.
Em desconexão, relink, conflito de owner ou falha de health, os envios são
pausados. A continuidade depende de backup verificável, restore testado,
relink autorizado e disponibilidade do proprietário para QR/pairing.

## Dados e histórico

O CRM da KaelSolutions mantém o histórico principal, auditoria, outbox e
idempotência independentemente do gateway. Sessão, QR, cookies, credenciais e
webhook secrets são dados sensíveis e não entram em logs, suporte ou artefatos.

## Suporte e aprovação

O canal, horário, severidade, SLA e responsável de suporte devem ser
preenchidos antes da assinatura. O cliente declara ciência da natureza não
oficial, do risco de bloqueio e dos limites acima.

| Campo | Preenchimento obrigatório |
|---|---|
| Cliente/tenant | [a preencher] |
| Número dedicado / referência segura | [a preencher; não inserir o número em repositório] |
| Responsável operacional | [a preencher] |
| Canal de suporte e SLA | [a preencher] |
| Versão/digest aprovado | `v0.23.3` + digest verificado |
| Aprovação do proprietário | [nome, data e assinatura] |
