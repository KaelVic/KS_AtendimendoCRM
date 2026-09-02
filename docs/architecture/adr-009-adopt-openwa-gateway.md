# ADR-009: Adotar OpenWA como gateway padrão de WhatsApp

## Status

Aceito em 31 de agosto de 2026.

## Contexto

O KS Atendimento IA precisa receber e enviar texto, áudio, imagem e PDF usando um número de WhatsApp dedicado, sem utilizar a API oficial no piloto. O gateway precisa ser auto-hospedado, integrar-se ao CRM em tempo real e permitir que toda lógica de IA, debounce, handoff, aprovação e auditoria permaneça sob controle da KaelSolutions.

Restrições relevantes:

- orçamento imediato de R$ 0;
- um número no piloto e primeiros clientes após validação;
- prazo curto;
- integração não oficial aceita pelo proprietário, com ciência do risco de bloqueio;
- necessidade futura de múltiplos tenants e sessões;
- nenhum gateway pode se tornar dependência direta do domínio.

## Opções consideradas

| Opção | Benefícios | Custos/riscos | Decisão |
|---|---|---|---|
| OpenWA auto-hospedado | REST, webhooks, QR, multimídia, múltiplas sessões, PostgreSQL/Redis/S3, motores intercambiáveis e licença MIT | Projeto pré-1.0, mudanças rápidas, patches nos motores, integração não oficial e sessão sensível | Escolhido |
| Integrar `whatsapp-web.js` diretamente | Controle total e menos uma camada | Manutenção de protocolo, sessão, API, webhooks, segurança e mídia passa a ser nossa | Rejeitado |
| Integrar Baileys diretamente | Menor consumo e sem navegador | Mesmo custo de construir gateway e maior acoplamento ao protocolo | Rejeitado |
| Outro gateway não oficial | Pode fornecer alternativa futura | Introduzir dois gateways no piloto aumenta testes e operação | Adiado |
| WhatsApp Cloud API oficial | Maior alinhamento e suporte oficial | Contraria a restrição atual e muda o modelo operacional/custos | Reavaliar no futuro |

## Decisão

Adotar OpenWA como gateway padrão do piloto e dos primeiros clientes comerciais, sempre atrás de `WhatsAppAdapter` e `ChannelRouter` próprios.

Baseline inicial:

- OpenWA `v0.23.3`, fixado por tag e preferencialmente digest;
- `whatsapp-web.js` como motor inicial;
- Baileys somente como fallback após contract tests;
- uma única instância proprietária por sessão;
- API e dashboard apenas na rede interna;
- nenhuma autoresposta ou regra comercial executada pelo OpenWA;
- webhooks HMAC, proteção contra replay, outbox e idempotência no backend KS;
- sessão em volume persistente privado e criptografado na infraestrutura;
- banco/Redis separados logicamente do domínio KS;
- vínculo único `tenant_id` ↔ sessão ↔ shard.

## Racional

O OpenWA entrega o transporte necessário dentro do prazo e do orçamento, possui atividade recente, testes automatizados e contrato REST que evita integrar diretamente duas bibliotecas de WhatsApp. O adapter próprio preserva independência e permite substituir ou acrescentar gateway futuro sem reescrever CRM, agente ou fluxos comerciais.

## Trade-offs aceitos

- A conexão continua não oficial e pode desconectar ou ser bloqueada.
- O projeto ainda está abaixo da versão 1.0 e exige atualização controlada.
- O motor `whatsapp-web.js` consome mais memória por sessão.
- Credenciais de sessão e certos dados do gateway dependem de proteção da infraestrutura em repouso.
- Não haverá alta disponibilidade ativa/ativa para a mesma sessão.

Esses riscos são aceitáveis no piloto porque haverá um número dedicado, baixo volume, proprietário único, monitoramento e possibilidade de relink. Eles devem constar do contrato comercial antes de cliente pagante.

## Consequências

### Positivas

- entrega mais rápida de QR, sessão, webhooks e mídia;
- gateway auto-hospedado e sem custo de licença;
- suporte a primeiros clientes sem reconstruir transporte;
- possibilidade de sharding por sessão;
- independência do domínio através do adapter.

### Negativas

- novo serviço e banco lógico para operar;
- necessidade de monitorar sessão, memória e mudanças do protocolo;
- risco de quebra em upgrades e de bloqueio do número;
- runbooks específicos de QR, relink, backup e rollback.

### Mitigações obrigatórias

- nunca usar imagem `latest`;
- contract tests antes de atualizar;
- backup e rollback testados;
- API não pública, chaves restritas e HMAC;
- ownership único com fencing token ao escalar;
- histórico principal persistido no CRM, independente do gateway;
- limites conservadores, aprovação de primeira abordagem e opt-out;
- alternativa futura pelo mesmo `WhatsAppAdapter`.

## Gatilhos para revisão

Revisar esta decisão quando ocorrer qualquer um:

- falhas recorrentes ou incompatibilidade crítica do OpenWA;
- exigência de SLA incompatível com gateway não oficial;
- bloqueios de números mesmo sob operação conservadora;
- requisito regulatório ou contratual de API oficial;
- crescimento que exija escala além do sharding seguro por sessão;
- ausência de manutenção ou correções de segurança;
- alternativa com menor risco total e migração viável.

## Fontes avaliadas

- Repositório: https://github.com/rmyndharis/OpenWA
- Matriz de capacidades: https://github.com/rmyndharis/OpenWA/blob/main/docs/29-engine-capability-matrix.md
- Arquitetura de segurança: https://github.com/rmyndharis/OpenWA/blob/main/docs/04-security-design.md
- Política de segurança: https://github.com/rmyndharis/OpenWA/blob/main/SECURITY.md
