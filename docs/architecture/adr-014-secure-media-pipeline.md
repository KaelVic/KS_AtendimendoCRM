# ADR-014: Pipeline seguro de mídia

## Status

Aceito para a Fase 3, com retenção final ainda pendente de decisão do proprietário.

## Decisão

O domínio recebe somente bytes já limitados e MIME declarado. O pipeline detecta o
tipo por assinatura, valida o formato completo e a duração do áudio, e rejeita
divergências antes de persistir o artefato. O nome informado pelo cliente nunca é
usado como caminho: o storage gera uma chave aleatória sob `media/<tenant_id>/`.

Áudio é transcrito pelo adapter local `FasterWhisperTranscriber`, carregado apenas
no worker. A implementação aceita WAV, OGG e MP3 quando o parser consegue obter a
duração; o modelo não recebe o nome original. `FakeTranscriber` cobre testes sem
download ou credencial.

Imagem é verificada com Pillow, limitada por bytes e pixels, orientada a partir do
EXIF apenas durante o processamento e regravada como JPEG sem EXIF, com dimensão
máxima configurável. O provider recebe somente `provider_storage_key` da derivada;
texto visual não é OCR nem instrução de sistema. Transcrição é dado não confiável e
deve ser delimitada por `transcript_as_untrusted_context` antes de entrar no LLM.

O PostgreSQL é a fonte da verdade: `media_assets` registra hash, MIME detectado,
duração, estado (`RECEIVED`, `PROCESSING`, `READY`, `FAILED`), erro e referências.
`(tenant_id, idempotency_key)` é único e a reivindicação usa `ON CONFLICT DO NOTHING`.
Mensagem e tenant excluem o registro em cascata; a limpeza dos objetos é feita pelo
serviço de storage, nunca por input do cliente.

## Retenção, upgrade e rollback

`MEDIA_RETAIN_ORIGINALS=true` é apenas o default seguro de desenvolvimento. A
política comercial de retenção e exclusão deve ser definida antes de produção.
Quando falso, o original transitório é removido após sucesso; a derivada da imagem
permanece. Não há segredo no banco, apenas chaves opacas de storage.

```text
alembic -c apps/api/alembic.ini upgrade 0006_media_assets
alembic -c apps/api/alembic.ini downgrade 0005_whatsapp_gateway
```

Antes do rollback em ambiente com dados, pausar ingestão, exportar o histórico
necessário e remover/arquivar os objetos por job autenticado. A migração é reversível
e o downgrade remove somente `media_assets`; mensagens e demais tabelas permanecem.

## Consequências e riscos residuais

Faster-Whisper exige modelo e recursos locais; indisponibilidade gera estado
`FAILED` sem resposta inventada e pode ser reprocessada por uma operação idempotente.
A estimativa de duração MP3 é conservadora para o limite operacional; formatos sem
parser de duração são rejeitados. A retenção e o antivírus são gates de produção
separados.
