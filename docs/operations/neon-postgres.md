# PostgreSQL gerenciado no Neon

O projeto `ks-atendimento-ia` usa o Neon somente como PostgreSQL gerenciado.
API, worker, Redis, arquivos e o volume privado do OpenWA permanecem sob a
responsabilidade da implantacao da KaelSolutions.

## Configuracao

Use a URL PostgreSQL do branch `production` em `DATABASE_URL`. Ela e consumida
somente pelo backend e deve ficar no AWS SSM/Secrets Manager ou em um arquivo
local ignorado pelo Git. Nunca coloque a URL no GitHub, frontend, imagem ou log.

Para a API e o worker em Docker na EC2, use a conexao direta (sem `-pooler`).
O codigo normaliza `postgres://` e `postgresql://` para `postgresql+asyncpg://`
e aceita `DATABASE_SSL_MODE=auto` com `sslmode=require` na URL.

```env
DATABASE_BACKEND=neon
DATABASE_URL=<URL_DO_NEON>
DATABASE_SSL_MODE=auto
COMPOSE_PROFILES=
```

Nao use a senha do banco em codigo-fonte, chat, screenshot ou commit. Nao use
SDK de Data API ou credenciais administrativas no frontend.

## Migracao controlada

As migracoes Alembic do repositorio sao a fonte de verdade do schema. Com o
`.env` preenchido na VM, execute antes de liberar trafego:

```bash
bash deploy/aws/scripts/migrate.sh
```

O script recusa configuracoes locais e exige uma URL PostgreSQL valida. Nao
crie tabelas manualmente no SQL Editor e nao use o schema do OpenWA no Neon.

## Continuidade

O banco gerenciado nao cobre Redis, arquivos locais/S3 nem o volume da sessao
OpenWA. Backup e restauracao devem validar cada artefato separadamente, com
saidas pausadas e fencing token respeitado. Se o Neon estiver indisponivel,
readiness deve falhar e novas saidas devem continuar pausadas.
