# Deploy econômico do piloto na AWS

Este runbook descreve uma implantação de baixo custo em uma única EC2 com
Docker Compose. Ele é um plano operacional: nenhum comando AWS abaixo deve ser
executado sem aprovação explícita do proprietário. Os comandos que criam ou
alteram recursos estão marcados como `[MUTAÇÃO AWS]`.

## Resultado e limites

O caminho público é somente `80/443 -> Caddy -> web/API`. PostgreSQL, Redis,
worker, ScrapeGraphAI e OpenWA ficam na rede Docker interna. O dashboard,
Swagger e API administrativa do OpenWA não possuem rota no Caddy. O OpenWA é
opt-in (`--profile openwa`), tem sessão em volume nomeado e não deve ser
pareado nesta etapa.

O gate da Fase 7 do plano mestre é “smoke test público e restore”. O material
local deste diretório comprova configuração, isolamento de portas e scripts;
o gate operacional só será aprovado após executar o smoke test e o restore em
uma conta AWS autorizada, com evidências de logs e checksum.

## Arquitetura econômica

```text
Internet :80/:443
       |
     Caddy (TLS automático, único serviço público)
       |-- web:3000
       `-- api:8000 -- postgres:5432
                    `-- redis:6379
worker -> redis/postgres       scrapegraph -> rede interna
openwa (profile opcional) -> rede interna + volume de sessão privado
```

Não usar RDS, NAT Gateway, ALB, Kubernetes ou microsserviços adicionais no
piloto. A EC2 usa saída direta para atualizações e SSM; o security group não
abre SSH. Em produção, considerar um bastion/SSM controlado apenas se o modelo
de operação exigir acesso administrativo adicional.

## Consumo e custo estimado

Estimativa mensal, sujeita à região, créditos e preços vigentes:

| Item | Configuração inicial | Ordem de grandeza |
|---|---|---:|
| EC2 | `t3.small`, Linux, 1 VM | ~730 horas/mês; aproximadamente US$ 15–25 |
| EBS | gp3 criptografado, 30–50 GiB | aproximadamente US$ 3–6 |
| S3 | backups incrementais/compactados, sem tráfego frequente | normalmente < US$ 2 |
| IPv4 público | 1 endereço, se necessário para TLS | preço regional vigente |
| Transferência | tráfego baixo do piloto | variável; monitorar |

Planejar uma margem de US$ 25–40/mês antes dos créditos, sem contar domínio,
chip ou uso de provedor externo. Validar a estimativa no AWS Pricing
Calculator da região escolhida e configurar budget alert antes de liberar
tráfego.

## Tags obrigatórias

Aplicar em EC2, EBS, security group, Elastic IP (se houver), bucket e budget:

```text
Project=KS-Atendimento-IA
Environment=pilot
Owner=KaelSolutions
CostCenter=pilot
ManagedBy=manual-compose
DataClass=confidential
```

Não colocar tokens, e-mails privados, IDs de sessão ou dados de contatos em
tags, nomes de recursos ou logs.

## Pré-requisitos e decisões pendentes

O proprietário deve escolher e registrar `AWS_REGION`, VPC/subnet, domínio,
tipo da instância, bucket privado e limites de budget. Também deve aprovar o
digest da imagem OpenWA após contract tests. Não inventar esses valores.

Na estação local:

```powershell
Copy-Item deploy/aws/.env.aws.example deploy/aws/.env.aws
```

Edite apenas configuração não secreta. O arquivo real `.env.aws` está no
`.gitignore`. Segredos entram por SSM/cofre e são materializados somente na VM
com permissão `0600`; nunca entram em Git, CI, imagem, screenshot ou log.

## Recursos AWS — somente após aprovação

Os comandos a seguir são exemplos parametrizados. Substitua os marcadores por
valores já aprovados; não os execute neste repositório sem autorização.

### Bucket privado e versionado para backup `[MUTAÇÃO AWS]`

```bash
export AWS_REGION='<regiao-aprovada>'
export BACKUP_BUCKET='<bucket-aprovado>'
aws s3api create-bucket --bucket "$BACKUP_BUCKET" --region "$AWS_REGION" \
  --create-bucket-configuration LocationConstraint="$AWS_REGION"
aws s3api put-public-access-block --bucket "$BACKUP_BUCKET" \
  --public-access-block-configuration \
BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BACKUP_BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BACKUP_BUCKET" \
  --server-side-encryption-configuration \
'{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

Aplicar as tags da seção anterior e uma lifecycle policy aprovada. O bucket
deve aceitar somente o prefixo `ks-atendimento/` pela role da instância.

### IAM/SSM `[MUTAÇÃO AWS]`

Anexar à role da EC2 apenas `ssm:GetParameter(s)` no caminho
`/ks-atendimento/production/*` e as ações S3 do arquivo
[`iam/backup-read-write-policy.json`](./iam/backup-read-write-policy.json),
restritas ao bucket/prefixo aprovados. Usar AWS Systems Manager Session
Manager, IMDSv2 e nenhum access key estático na VM.

Criar parâmetros SecureString fora do Git, sem imprimir os valores:

```bash
aws ssm put-parameter --name /ks-atendimento/production/POSTGRES_PASSWORD \
  --type SecureString --value "$POSTGRES_PASSWORD" --overwrite
aws ssm put-parameter --name /ks-atendimento/production/JWT_SECRET_KEY \
  --type SecureString --value "$JWT_SECRET_KEY" --overwrite
```

Os demais segredos seguem o mesmo padrão e devem ser fornecidos pelo ambiente
seguro do operador; não cole segredos no terminal compartilhado ou na conversa.

### Security group mínimo `[MUTAÇÃO AWS]`

Permitir ingress somente:

```text
TCP 80  0.0.0.0/0 e ::/0  (redirect/HTTP-01 do TLS)
TCP 443 0.0.0.0/0 e ::/0  (HTTPS)
```

Não permitir 22, 5432, 6379, 8000, 8080, 8081, 3000 ou painel/Swagger do
OpenWA. Egress pode ser inicialmente `443/tcp` e DNS/NTP conforme a política
da VPC; se a rede exigir egress amplo para atualização, monitorar e restringir
em seguida.

### EC2 com EBS criptografado e IMDSv2 `[MUTAÇÃO AWS]`

Usar AMI Amazon Linux 2023 aprovada, subnet pública sem IP adicional
desnecessário, `t3.small` e volume gp3 criptografado com a chave padrão da
conta (ou KMS aprovada). O lançamento deve exigir token IMDSv2 e aplicar tags:

```bash
aws ec2 run-instances \
  --image-id '<ami-al2023-aprovada>' --instance-type t3.small --count 1 \
  --subnet-id '<subnet-publica-aprovada>' --security-group-ids '<sg-aprovado>' \
  --iam-instance-profile Name='<instance-profile-ssm-aprovado>' \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":40,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Project,Value=KS-Atendimento-IA},{Key=Environment,Value=pilot},{Key=Owner,Value=KaelSolutions},{Key=CostCenter,Value=pilot},{Key=ManagedBy,Value=manual-compose},{Key=DataClass,Value=confidential}]'
```

O `user-data.yaml` instala Docker, AWS CLI, cria `ksapp` sem login e prepara
os diretórios. O serviço da aplicação roda como `ksapp`, não como root.

### Budget alerts `[MUTAÇÃO AWS]`

Defina `BUDGET_ALERT_EMAIL`, `BUDGET_LIMIT_USD`, `BUDGET_NAME` e `PROJECT_TAG`
no ambiente do operador. Revise o plano primeiro:

```bash
CONFIRM_AWS_MUTATION=I_APPROVE_AWS_BUDGET \
  bash deploy/aws/scripts/create-budget.sh
```

O script só cria o budget quando a confirmação explícita estiver presente e
notifica em 80% e 100% do limite. A conta deve possuir autorização para
Budgets; o endereço de alerta não fica hardcoded no domínio.

## Instalação na VM

Conecte-se por SSM, como `ksapp` quando possível. Não use SSH público.

```bash
sudo install -d -m 0750 -o ksapp -g docker /srv/ks-atendimento
sudo -u ksapp git clone '<origem-aprovada>' /srv/ks-atendimento
cd /srv/ks-atendimento
cp deploy/aws/.env.aws.example .env
chmod 600 .env
sudo install -m 0644 deploy/aws/ks-atendimento.service /etc/systemd/system/ks-atendimento.service
sudo systemctl daemon-reload
sudo systemctl enable ks-atendimento.service
```

Preencha configuração por SSM/cofre, incluindo `PUBLIC_DOMAIN` e
`BACKUP_S3_URI`. Antes de subir o OpenWA, `OPENWA_IMAGE` deve estar no formato
`ghcr.io/rmyndharis/openwa:0.23.3@sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec` e
`ENABLE_OPENWA=1`. Sem sessão real, mantenha `ENABLE_OPENWA=0`.

Valide e suba a stack web/API:

```bash
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml config --quiet
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml build
sudo systemctl start ks-atendimento.service
```

Para ativar o profile opcional, após aprovar o digest, altere apenas a
configuração não secreta no `.env` e reinicie pelo systemd:

```bash
# No /srv/ks-atendimento/.env:
ENABLE_OPENWA=1
OPENWA_IMAGE=ghcr.io/rmyndharis/openwa:0.23.3@sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec
sudo systemctl restart ks-atendimento.service
```

O Caddy obtém/renova TLS automaticamente para `PUBLIC_DOMAIN`. O DNS A/AAAA
deve apontar para a VM antes do primeiro start; não expor portas alternativas
para contornar o TLS.

## Health, logs e operação

```bash
PUBLIC_DOMAIN='<dominio-aprovado>' bash deploy/aws/scripts/healthcheck.sh
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml ps
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml logs --tail=200 caddy api worker
sudo systemctl status ks-atendimento.service
```

Os containers usam `restart: unless-stopped`; o systemd sobe a stack após
reinício da VM. Logs têm rotação JSON de 10 MiB x 5. Nunca usar `logs` para
coletar payloads, tokens, QR ou mensagens pessoais; redigir evidência com
correlation ID e contagens.

Com OpenWA ativo, a tela de saúde deve mostrar versão, conexão, owner único,
último webhook, último receipt e necessidade de relink. A API valida HMAC sobre
os bytes exatos e replay antes de enfileirar evento. Se a sessão estiver
insegura, sem owner ou desconectada, manter envio pausado; não ativar outra
instância com o mesmo volume.

## Backup, restore e retenção

O backup inclui dump PostgreSQL, `app_data` e, se OpenWA estiver ativo, o
volume nomeado de sessão. Os artefatos são compactados, recebem SHA-256 e são
enviados ao prefixo S3 com SSE-S3. O volume EBS e o bucket são criptografados.

```bash
export BACKUP_S3_URI='s3://<bucket-aprovado>/ks-atendimento'
export OPENWA_VOLUME_NAME=ks_openwa_sessions
bash deploy/aws/scripts/backup.sh
```

Faça restore somente em janela aprovada, com a fila pausada e backup atual:

```bash
export BACKUP_STAMP='<timestamp-do-backup-aprovado>'
export CONFIRM_RESTORE=I_UNDERSTAND_RESTORE_OVERWRITES_DATA
bash deploy/aws/scripts/restore.sh
PUBLIC_DOMAIN='<dominio-aprovado>' bash deploy/aws/scripts/healthcheck.sh
```

O restore interrompe serviços, valida checksum antes de tocar nos volumes e
usa `pg_restore --exit-on-error`. Teste primeiro em uma VM/volumes de
homologação; a evidência mínima é checksum válido, `pg_isready`, health HTTPS,
contagem de registros e reconciliação de idempotency keys. Backup sem restore
verificado não conta como proteção.

## Atualização e rollback

Antes de atualizar: ler changelog, rodar contract tests, drenar outbox, pausar
envios, fazer backup incluindo sessão e registrar versão/epoch do owner.

```bash
git fetch --tags
git checkout '<release-aprovada>'
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml build
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml up -d
PUBLIC_DOMAIN='<dominio-aprovado>' bash deploy/aws/scripts/healthcheck.sh
```

Se o health ou reconciliação falhar, pause envio e volte à release anterior,
sem remover volumes:

```bash
git checkout '<release-anterior-aprovada>'
docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml up -d
```

Para mudança de imagem OpenWA, preservar o volume de sessão, parar o owner
anterior, executar smoke/contract tests e só então iniciar a versão nova.
Nunca iniciar duas instâncias da mesma sessão simultaneamente. Se houver
relink necessário, fazê-lo apenas na tela autenticada do proprietário.

## Evidência pós-deploy do gate

Registrar em `test-results/e2e/` ou no sistema de evidências autorizado:

1. timestamp UTC, release, instance ID mascarado e correlation ID;
2. `docker compose ps` e health HTTPS público;
3. fluxo web -> API -> PostgreSQL com dado de teste descartável;
4. backup enviado, SHA-256 conferido e restore em ambiente isolado;
5. portas públicas observadas somente em 80/443;
6. se OpenWA estiver habilitado: health/restart controlado, versão fixa,
   owner único e nenhum QR/segredo nos logs.

Contatos reais, primeira mensagem externa, QR real e dados de produção não
podem ser usados em testes automatizados. A ausência de AWS/Docker autorizado
é uma limitação explícita, não um resultado de sucesso.
