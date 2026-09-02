# Observabilidade e resposta operacional

Esta implementação é deliberadamente pequena: a API expõe métricas em
`/metrics` para um scraper interno/autorizado e o endpoint `/health/ready`
resume dependências. Não há Prometheus, Grafana ou outro serviço novo no
piloto. Os labels são enums, status classes, nomes de componentes e
identificadores de sessão; nunca são mensagens, telefones, e-mails, tokens,
URLs completas ou argumentos de ferramentas.

## Sinais

| Sinal | Métrica/endpoint | Ação inicial |
|---|---|---|
| latência p50/p95 | `ks_operation_latency_ms_p50/p95{operation=...}` | verificar dependência e fila |
| erros | `ks_http_errors_total`, `ks_integration_calls_total{outcome="error"}` | abrir incidente se persistente |
| fila | `ks_queue_depth{queue="grouping_due"}` | reduzir entrada e investigar worker |
| ferramenta | `ks_tool_success_total{tool=...,success=...}` | bloquear ferramenta se falhar |
| escalonamento | `ks_escalations_total{source="llm"}` | revisar pendências, sem expor texto |
| duplicação | `ks_duplicates_total{kind=...,provider=...}` | pausar reentrega e conferir idempotência |
| modelo | `ks_model_usage_total{provider=...,outcome=...}` | verificar cota/timeout/fallback |
| componente | `ks_component_status{component=...}` | usar `/health/ready` para diagnóstico |

O worker publica heartbeat com profundidade real do sorted set de debounce.
OpenWA publica por sessão versão, conexão, owner state, shard state, último
webhook e último receipt quando esses eventos passam pelo adapter. A REST API
do OpenWA v0.23.3 não fornece memória do processo nem contador de reinícios;
esses campos aparecem como `unknown` e não são fabricados. O operador pode
observar essas duas propriedades no runtime do host, sem conceder Docker
socket à aplicação, e alimentar um coletor futuro.

## Health/readiness

```bash
PUBLIC_DOMAIN='<dominio-aprovado>' bash deploy/aws/scripts/healthcheck.sh
curl --fail --silent --show-error "https://${PUBLIC_DOMAIN}/health/live"
curl --fail --silent --show-error "https://${PUBLIC_DOMAIN}/health/ready"
```

`/health/live` só prova que a API está viva. `/health/ready` verifica
PostgreSQL, Redis e heartbeat do worker; também exibe estado de Gemini,
OpenWA/sessão, e-mail e calendário. Adapters fake aparecem como `degraded`;
integrações ausentes aparecem como `unhealthy`, mas não tornam o núcleo
indisponível quando são opcionais. O Caddy não roteia `/metrics` publicamente.

## Alertas acionáveis

Configurar o scraper autorizado com estas regras e uma janela de avaliação de
5 minutos:

```text
ks_component_status{component="postgres"} == 0 for 2m
ks_component_status{component="redis"} == 0 for 2m
ks_component_status{component="worker"} == 0 for 2m
ks_queue_depth{queue="grouping_due"} > 100 for 5m
ks_operation_latency_ms_p95{operation="llm"} > 12000 for 5m
increase(ks_integration_calls_total{component="gemini",outcome="error"}[5m]) > 3
increase(ks_duplicates_total[5m]) > 0
ks_openwa_session_info{connection!="CONNECTED"} == 0 for 2m
```

Para disco, usar também o check do host/volume PostgreSQL e alertar em 80%
(aviso) e 90% (crítico). Para backup, alertar quando o job não gerar um
artefato com checksum dentro da janela diária. Alertas devem conter somente
componente, ambiente, timestamp e correlation ID; não anexar payloads.

## Runbooks

Todos os comandos são executados na VM por SSM, com a fila de envio pausada
quando indicado. Não apagar volumes, não iniciar uma segunda sessão OpenWA e
não enviar mensagem manual para “testar”.

### 1. Sessão desconectada

Sintoma: `whatsapp_session.connection=DISCONNECTED`, health OpenWA falho ou
`ks_openwa_session_info` sem `CONNECTED`.

```bash
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml ps
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml logs --tail=200 openwa
```

Pause o outbox, preserve `openwa_sessions`, confirme owner único e aguarde
reconexão. Se houver erro persistente, marque `RELINK_REQUIRED` no CRM e
prossiga para o runbook de relink. Não remova a sessão nem faça aquecimento.

### 2. Relink/QR necessário

Confirme no CRM autenticado do proprietário a versão, sessão e necessidade de
QR. Pare qualquer processo concorrente, faça backup do volume e gere QR apenas
na tela do proprietário. Depois do pareamento, confirme `CONNECTED`, owner
correto, último webhook/receipt e execute somente o smoke fake/controlado.
Mantenha o envio pausado até essas verificações passarem.

### 3. Conflito de owner/shard

Sintoma: `owner_state="conflict"` ou dois processos alegam a mesma sessão.

```bash
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml ps
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml logs --tail=200 openwa
```

Não mate o processo sem registrar o epoch/owner no CRM. Pare o processo
secundário, mantenha o owner que possui o volume e valide que há uma única
instância. Se a atribuição persistida estiver divergente, bloqueie envio e
corrija a atribuição por operação auditada antes de reiniciar.

### 4. Gemini sem cota, timeout ou fallback

Sintoma: aumento de `ks_model_usage_total{outcome="fallback"}` ou erros Gemini.
O fallback seguro cria pendência; ele não envia resposta inventada.

```bash
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml logs --tail=200 api worker
curl --fail --silent --show-error "https://${PUBLIC_DOMAIN}/health/ready"
```

Confirme cota no console autorizado sem copiar a chave para logs. Reduza a
fila/limite configurado ou mantenha `LLM_PROVIDER=fake`/pendência até a cota
voltar. Não aumente retry indefinidamente e não troque provedor sem decisão
registrada.

### 5. Worker parado

Sintoma: `/health/ready` marca worker unhealthy ou heartbeat expirado.

```bash
sudo systemctl status ks-atendimento.service
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml ps worker
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml logs --tail=200 worker
sudo systemctl restart ks-atendimento.service
```

Confirme novo heartbeat e `queue_depth` antes de liberar envio. Reentregas são
aceitas pela idempotência; não execute jobs manualmente em paralelo.

### 6. Banco cheio

```bash
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml exec -T postgres df -h /var/lib/postgresql/data
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'select pg_size_pretty(pg_database_size(current_database()));'
```

Pause ingressos e envio, faça backup se houver espaço, identifique retenção
aprovada e aumente EBS somente com aprovação. Não apague histórico, WAL ou
arquivos de sessão sem política de retenção e backup restaurável.

### 7. Envio duplicado

Pause o outbox e preserve correlation/idempotency keys. Consulte o registro
de outbox e receipt no CRM, confirme a constraint única e conte duplicações:

```bash
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml exec -T api \
  curl --fail --silent --show-error http://127.0.0.1:8000/metrics | \
  grep 'ks_duplicates_total'
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml logs --tail=200 api worker
```

Não reenvie manualmente. Se a chave for a mesma, reconcilie o receipt; se for
chave diferente, bloqueie a sessão e abra incidente. Só libere após testar
reentrega fake e confirmar que HUMAN_ACTIVE continua bloqueando envio.

### 8. Backup falho

```bash
df -h /var/backups/ks-atendimento
aws s3 ls "$BACKUP_S3_URI" --recursive --human-readable --summarize
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml logs --tail=200 postgres api openwa
bash deploy/aws/scripts/backup.sh
```

O comando só é executado com role S3 aprovada. Verifique espaço, permissões,
IAM e checksum; não considere “upload iniciado” como backup concluído. Se o
volume de sessão estiver ativo, confirme que `openwa-session.tgz` também foi
gerado. Até um restore de teste passar, manter a operação em modo seguro e
registrar a pendência.

## Evidência e limites

Guardar timestamp, versão, nomes de componentes, status, latências, contagens
e correlation IDs saneados. Não guardar mensagens, prompts, anexos, QR,
cookies, tokens ou e-mails completos. Alertas de e-mail/calendário refletem
configuração e chamadas instrumentadas; confirmação de entrega continua sendo
responsabilidade do adapter/fake contratual. Memória/restart de OpenWA exigem
endpoint/telemetria do gateway que ainda não faz parte do contrato; não usar
valores inventados para aprovar o piloto.
