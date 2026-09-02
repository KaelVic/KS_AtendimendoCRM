# ADR-002: PostgreSQL como Fonte Única da Verdade

## Status
Aceito em 31 de agosto de 2026.

## Contexto
A plataforma gerencia dados estruturados de clientes, histórico de conversas, transições de estado, propostas comerciais e auditoria com requisitos estritos de rastreabilidade e isolamento por tenant.

## Decisão
Utilizar o **PostgreSQL** como o único banco de dados transacional e fonte primária da verdade:
- Todas as tabelas de domínio contêm chave primária UUID, `tenant_id` e timestamps.
- Integridade referencial estrita e migrações versionadas (Alembic).
- Nenhuma dependência externa ou gateway pode atualizar o estado do sistema contornando a persistência no PostgreSQL.

## Consequências
- Garantia de consistência relacional e rastreabilidade total.
- Consultas analíticas e operacionais unificadas sem necessidade de sincronização entre bancos distintos no MVP.
