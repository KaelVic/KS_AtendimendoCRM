# ADR-005: Adaptadores Fortemente Tipados para Serviços Externos

## Status
Aceito em 31 de agosto de 2026.

## Contexto
O sistema depende de múltiplos serviços externos (WhatsApp/OpenWA, Gemini AI, Google Calendar, envio de e-mail). O acoplamento direto das regras de negócio aos SDKs externos tornaria o sistema frágil e impediria a substituição de provedores ou testes automatizados confiáveis.

## Decisão
Isolar toda integração de terceiros atrás de **Interfaces de Adaptador (Ports and Adapters)**:
- `WhatsAppAdapter`: abstrai o transporte de WhatsApp (OpenWA, fake gateway ou Cloud API futura).
- `LLMAdapter`: abstrai a inteligência artificial (Gemini Developer API, mocks de teste).
- `CalendarAdapter`: abstrai a sincronização de agendas.
- `EmailAdapter`: abstrai o envio de alertas operacionais.

Para cada adaptador, é obrigatória a existência de uma implementação `Fake` ou `Mock` contratual para execução de suítes de teste sem depender de serviços externos.

## Consequências
- Regras de negócio 100% testáveis sem chamadas de rede reais.
- Facilidade de substituição de infraestrutura sem refatoração do domínio do CRM.
