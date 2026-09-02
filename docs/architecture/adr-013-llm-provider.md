# ADR-013 — Provider LLM tipado e seguro

## Status

Aceito para o piloto.

## Decisão

O domínio usa `LLMProvider`, com `FakeProvider` para testes e
`GeminiProvider` como adapter HTTP. A chave é lida exclusivamente de
`GEMINI_API_KEY`; quando `LLM_PROVIDER=gemini`, sua ausência interrompe o
startup com mensagem sem segredo. O padrão local é `fake`.

Entradas exigem tenant, conversa, estado de controle, versão de política e
partes `TEXT`, `TRANSCRIPT` ou `IMAGE_DESCRIPTION`. Essas partes são dados não
confiáveis delimitados no prompt e nunca autorizam ferramentas.

Saídas são validadas por Pydantic. JSON inválido permite uma única tentativa de
reparo; se continuar inválido, retorna fallback sem mensagem/ferramenta,
marca `pending` e usa `LLM_OUTPUT_INVALID` para criação de pendência pelo
orquestrador. O adapter aplica timeout, retry limitado a falhas transitórias,
rate limit local e logs somente com metadados não sensíveis.
