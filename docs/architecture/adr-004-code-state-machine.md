# ADR-004: Máquina de Estados Finita e Determinística em Código

## Status
Aceito em 31 de agosto de 2026.

## Contexto
O controle da conversa entre automação de IA e operadores humanos, bem como o fluxo de propostas e aprovações, exige previsibilidade, segurança e auditoria rigorosa. Ferramentas complexas de fluxo como LangGraph introduzem opacidade e sobrecarga desnecessária na fase inicial.

## Decisão
Implementar o ciclo de vida das conversas e processos comerciais como **Máquinas de Estados Finitas (FSM)** explícitas implementadas em código TypeScript e Python:
- Estados de conversa estritamente tipados: `BOT_ACTIVE`, `HUMAN_REQUESTED`, `HUMAN_ACTIVE`, `AI_ASSISTED_PENDING`, `BOT_RESUMING`, `CLOSED`.
- Transições atômicas no banco com registro de auditoria (`audit_events`).
- Toda ação do worker valida o estado atual antes do envio final.

## Consequências
- Comportamento determinístico e fácil de testar unitariamente.
- Risco zero de o robô responder quando a conversa está sob intervenção humana (`HUMAN_ACTIVE`).
