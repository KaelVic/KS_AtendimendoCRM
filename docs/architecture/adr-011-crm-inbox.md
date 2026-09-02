# ADR-011 — Inbox do CRM

## Status

Aceito para a Fase 1, com upload de anexos pendente de contrato de storage.

## Decisão

A inbox é uma tela Next.js que lê conversas e mensagens pela API FastAPI. O
servidor resolve e autoriza o `tenant_id` a partir do proprietário autenticado;
o valor de configuração enviado pelo navegador não é uma autorização.

Assumir e devolver são comandos confirmados pela API. A UI não altera o estado
local antes da resposta e desabilita o botão enquanto o comando está em voo.
Atualizações usam polling de cinco segundos, exibem reconexão e recuperam o
estado da API após falha.

Anexos podem ser selecionados somente para tornar a limitação visível ao
operador. Nenhum arquivo é enviado ou tratado como persistido nesta fase.

## Consequências

- O histórico principal permanece independente do gateway OpenWA.
- O fluxo pode ser testado sem sessão WhatsApp ou credenciais reais.
- SSE/WebSocket e upload seguro podem substituir o polling quando houver
  contrato, limites MIME/tamanho, antivírus e storage aprovados.
