# ADR-001: Adoção de Monólito Modular

## Status
Aceito em 31 de agosto de 2026.

## Contexto
O KS Atendimento IA precisa integrar CRM, inbox de WhatsApp, agente autônomo, agendamento de reuniões, geração de propostas e prospecção em uma plataforma unificada. O piloto é operado por uma única pessoa (proprietário da KaelSolutions), com prazo agressivo (8 de setembro de 2026) e orçamento inicial de R$ 0.

## Decisão
Adotar um **monólito modular** organizado como monorepo:
- Backend unificado em FastAPI (Python).
- Frontend CRM em Next.js (TypeScript).
- Worker assíncrono em Python consumindo filas Redis.
- Módulos de domínio com fronteiras estritas e separação lógica por `tenant_id`.

Microsserviços, Kafka, Kubernetes e arquiteturas distribuídas complexas estão explicitamente proibidos no MVP.

## Consequências
- Simplicidade operacional máxima durante o desenvolvimento local e piloto em VM única da AWS.
- Transações ACID garantidas pelo PostgreSQL em operações críticas de CRM e mensagens.
- Fronteiras de domínio preparadas para extração futura se houver necessidade comprovada de escalabilidade.
