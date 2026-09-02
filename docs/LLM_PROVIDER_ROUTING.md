# LLM provider routing

Ticker-news summaries, Desk IC explanations, and Terminal Intelligence use one
sequential provider router. A request stops after the first successful response;
providers are never called in parallel.

## Supported endpoints

Set only the providers you have enabled:

```env
LLM_PROVIDER_ORDER=nvidia,groq,cerebras,sambanova,huggingface,openrouter,omniroute,gemini
LLM_PROVIDER_ATTEMPTS=3
LLM_FREE_FAILOVER_MAX=4

NVIDIA_API_KEY=nvapi-placeholder
NVIDIA_NEWS_MODEL=nvidia/nemotron-3-nano-30b-a3b
NVIDIA_REASONING_MODEL=nvidia/nemotron-3-super-120b-a12b

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

# Optional self-hosted final gateway before the TinyFish evidence digest.
TICKER_NEWS_LLM=router
OMNIROUTE_ENABLED=1
OMNIROUTE_API_URL=http://host.docker.internal:20128/v1/chat/completions
OMNIROUTE_API_KEY=local-key-if-enabled
OMNIROUTE_NEWS_MODEL=auto/best-free
OMNIROUTE_REASONING_MODEL=auto/best-reasoning
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

NVIDIA retired the hosted 49B v1/v1.5 endpoints on 2026-08-25. Old NVIDIA
model environment overrides are migrated to `nvidia/nemotron-3-super-120b-a12b`
on the standard hosted URL only; custom/self-hosted URLs remain untouched.
HTTP 410 disables that exact endpoint/model for the worker lifetime and falls
through to another configured provider, rather than retrying every 60 seconds.
Changing the configured model or endpoint makes the new pair eligible immediately.

OmniRoute does not grant a guaranteed token allocation. It aggregates whatever
free tiers, OAuth sessions, API keys, subscriptions, and no-auth providers the
operator connects to its local gateway. Keep it opt-in, protect its dashboard
and client API, and review every routed upstream's terms and data handling. Set
a non-default dashboard password, require a client API key, and keep port 20128
on localhost or a private Docker network; do not publish it through the public
Cloudflare tunnel.

`TICKER_NEWS_LLM=router` makes the provider chain primary. If every configured
LLM provider is unavailable, the existing TinyFish evidence digest is returned
without representing it as an LLM-generated answer. Omitting this setting keeps
the previous TinyFish-first behavior.

The stock Heat Map contains market data only and does not invoke an LLM.
