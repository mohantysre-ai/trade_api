# LLM provider routing

Ticker-news summaries, Desk IC explanations, and Terminal Intelligence use one
sequential provider router. A request stops after the first successful response;
providers are never called in parallel.

## Supported endpoints

Set only the providers you have enabled:

```env
LLM_PROVIDER_ORDER=nvidia,groq,cerebras,sambanova,huggingface,openrouter,gemini
LLM_PROVIDER_ATTEMPTS=3
LLM_FREE_FAILOVER_MAX=4

NVIDIA_API_KEY=nvapi-placeholder
NVIDIA_NEWS_MODEL=nvidia/nemotron-3-nano-30b-a3b
NVIDIA_REASONING_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1

GROQ_API_KEY=placeholder
GROQ_NEWS_MODEL=llama-3.1-8b-instant
GROQ_REASONING_MODEL=llama-3.3-70b-versatile

CEREBRAS_API_KEY=placeholder
SAMBANOVA_API_KEY=placeholder
HUGGINGFACE_API_KEY=placeholder

LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-placeholder
LLM_API_URL=https://openrouter.ai/api/v1/chat/completions
LLM_MODEL=openrouter/free

GEMINI_API_KEY=placeholder
```

Provider-specific `*_NEWS_MODEL` and `*_REASONING_MODEL` values override the
default model for compact ticker summaries and deeper terminal analysis. Endpoint
URLs can also be overridden with `NVIDIA_API_URL`, `GROQ_API_URL`,
`CEREBRAS_API_URL`, `SAMBANOVA_API_URL`, or `HUGGINGFACE_API_URL`.

OpenRouter discovers the live `:free` model catalog, but tries at most four model
endpoints per OpenRouter attempt by default. This avoids turning one ticker into
dozens of quota-consuming calls. Each provider has an independent cooldown, so an
OpenRouter daily-limit response does not disable NVIDIA, Groq, Gemini, or another
configured endpoint.

API keys must remain server-side and must never use a `NEXT_PUBLIC_` variable.
Free hosted endpoints are rate-limited and are not production SLAs.
