# PostgreSQL gerenciado no Supabase

O Supabase pode hospedar somente o PostgreSQL do KS Atendimento IA. A API e o
worker continuam responsáveis pelo domínio, isolamento por `tenant_id`,
idempotência, outbox e auditoria. Redis, arquivos e o volume privado do OpenWA
continuam fora do Supabase.

## Configuração

Use a URL PostgreSQL fornecida pelo projeto Supabase em `DATABASE_URL`. Ela é
consumida apenas pelo backend e deve permanecer no SSM/cofre da AWS, nunca no
GitHub, frontend, imagem ou log. O código aceita URLs `postgres://`,
`postgresql://` e `postgresql+asyncpg://` e remove `sslmode` da URL antes de
passá-la ao `asyncpg`; `DATABASE_SSL_MODE=auto` preserva o modo SSL informado
pela URL.

Não use `supabase-js`, a Data API ou a chave `service_role` no navegador. O
backend usa conexão SQL privada. Se tabelas forem expostas pela Data API, RLS
deve ser habilitado e as políticas precisam restringir o tenant; autenticação
não substitui autorização de linha.

## Migração controlada

As migrações Alembic existentes continuam sendo a fonte de verdade. Na VM,
com o `.env` preenchido e permissões de rede para o banco, execute:

```bash
bash deploy/aws/scripts/migrate.sh
```

O comando usa a imagem da API, que inclui `alembic.ini` e a pasta `alembic/`, e
aplica a cadeia até `0015_contact_preferences`. Execute-o antes de liberar
tráfego e registre a versão aplicada. Não use o schema do OpenWA no Supabase.

## Continuidade

O backup do Supabase não cobre Redis, arquivos locais/S3 nem o volume da sessão
OpenWA. O restore deve validar o banco e esses artefatos separadamente, com as
saídas pausadas e fencing token respeitado. Se o Supabase estiver indisponível,
readiness deve falhar, novas saídas devem permanecer pausadas e nenhum evento
deve ser tratado como processado sem persistência.
