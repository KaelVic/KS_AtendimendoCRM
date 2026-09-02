# ADR-006: Transcrição Local de Áudio com Faster-Whisper

## Status
Aceito em 31 de agosto de 2026.

## Contexto
Mensagens de voz constituem uma fração significativa do tráfego em atendimentos de WhatsApp no Brasil. O processamento de áudio em nuvem externa incorreria em custos por minuto e aumentaria a exposição de dados biométricos de voz.

## Decisão
Utilizar o **Faster-Whisper** executando localmente por padrão na máquina host/VM:
- Processamento assíncrono pelo worker com fila dedicada.
- Transcrição convertida em texto e armazenada vinculada à mensagem.
- Áudio original armazenado conforme política de retenção local/S3.

## Consequências
- Custo financeiro zero para transcrição de áudio no piloto.
- Privacidade ampliada e menor exposição de dados de voz a terceiros.
- Exige atenção ao uso de CPU/memória no ambiente de produção.
