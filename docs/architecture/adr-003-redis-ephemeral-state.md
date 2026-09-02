# ADR-003: Redis para Estado Efêmero, Debounce, Locks e Filas

## Status
Aceito em 31 de agosto de 2026.

## Contexto
O atendimento via WhatsApp frequentemente envolve usuários enviando mensagens fragmentadas em sequência rápida. É indispensável acumular fragmentos (debounce de 7s a 25s), impedir respostas concorrentes através de locks distribuídos e enfileirar processamento assíncrono.

## Decisão
Adotar o **Redis** para:
- Acumulação de fragmentos e timers de debounce por conversa.
- Locks distribuídos (Redlock / SET NX EX) para garantir processamento atômico e impedir corridas entre robô e operador humano.
- Filas de tarefas em segundo plano para o worker assíncrono.
- Armazenamento de cache volátil e heartbeats de instâncias.

O Redis não armazena dados de longa duração ou histórico de conversas, atuando unicamente como acelerador e coordenador efêmero.

## Consequências
- Baixa latência nas operações de sincronização em tempo real.
- Falha no Redis pode ser mitigada via reinício limpo sem perda de dados históricos transacionais.
