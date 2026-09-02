# ADR-019 — Agenda e reuniões em `America/Sao_Paulo`

## Status

Aceito para a fatia de agenda da Fase 6.

## Decisão

`CalendarAdapter` é a porta de integração. A leitura consulta os calendários
pessoal e `Onboarding KaelSolutions`; a escrita só usa o segundo. O adapter
Google recebe credenciais exclusivamente por ambiente e permanece bloqueado
até a configuração real. O `FakeCalendarAdapter` permite contract tests sem
acessar calendários reais.

O domínio oferece slots de 30 em 30 minutos entre 09:00 e 17:00, com duração
fixa de 45 minutos e término máximo às 18:00. Todos os instantes são
normalizados e persistidos em UTC com timezone declarada. A confirmação usa
lock distribuído por tenant (Redis em produção), relê os dois calendários sob
lock e usa chave idempotente também no adapter.

Estados de reunião: `SCHEDULED`, `COMPLETED`, `NO_SHOW` e `CANCELLED`. No-show
é uma ação explícita no CRM, auditada e executada apenas por operador; depois
dela a resposta informa que remarcação é permitida. Não existe no-show
automático.

O lembrete persistido é `2H` quando a confirmação ocorre ao menos duas horas
antes, ou `90M` quando a janela de duas horas já não é possível mas ainda há
90 minutos. A chave `meeting:{id}:reminder:{kind}` evita duplicação e o
provider fake exercita retry transitório.

## Migração e rollback

`0011_calendar_meetings` cria `meetings` e `meeting_reminders` com tenant,
constraints de intervalo/estado, FK composta e unicidade de idempotência.

```bash
alembic -c apps/api/alembic.ini upgrade head
alembic -c apps/api/alembic.ini downgrade 0010_commercial_flow
```

O rollback remove reservas e lembretes locais; antes dele, exportar agenda e
evidências necessárias. Não alterar ou remover eventos externos sem operação
explicitamente autorizada.
