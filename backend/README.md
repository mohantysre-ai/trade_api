# IROS Angel One Market Feed

Python service that pulls live NSE quotes from [Angel One SmartAPI](https://smartapi.angelone.in/) and serves them to the IROS Next.js terminal.

## Setup

1. Create a SmartAPI app at https://smartapi.angelone.in/ and note your **API Key**.
2. Enable TOTP on your Angel One account and copy the **TOTP secret** (base32).
3. Install dependencies:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

4. Copy credentials:

```powershell
copy .env.example .env
```

Edit `.env` with your Angel One credentials.

## Run the API server

```powershell
python angel_one_feed.py --serve
```

Server starts at **http://localhost:8000**

- Health: `GET /health`
- Market data: `GET /api/market-data`

## One-shot JSON export

Useful for testing or writing a static snapshot:

```powershell
python angel_one_feed.py --once --output ../iros-terminal/public/market-data.json
```

## Frontend

The Next.js app polls `http://localhost:8000/api/market-data` every 30 seconds.

Optional override in `iros-terminal/.env.local`:

```
NEXT_PUBLIC_MARKET_API_URL=http://localhost:8000
```

Optional LLM news summary:

- Set `LLM_PROVIDER=openai` for OpenAI-compatible endpoints or `LLM_PROVIDER=gemini` for Gemini.
- Set `REDACTED` or `REDACTED` to your Gemini API key.
- Optionally set `LLM_API_URL` for OpenAI; leave blank for Gemini when using the `google-genai` client.
- Set `LLM_MODEL=gemini-3.7-flash` for production analysis or `gemini-3.1-flash-lite` for lower-cost, high-volume summaries.
- For Gemini, install the Python client with `pip install google-genai`.

New AI analysis endpoints:

- `GET /api/market-intelligence` returns the existing market intelligence summary from live feed data.
- `GET /api/terminal-intelligence` returns a structured Gemini `TerminalIntelligencePayload` object.

Start both services:

```powershell
# Terminal 1
cd backend
python angel_one_feed.py --serve

# Terminal 2
cd iros-terminal
npm run dev
```

## What gets updated live

| Data | Source |
|------|--------|
| Stock LTP (live Angel One universe, LLM-selected top 20) | Angel One `getMarketData` + LLM filter prompt |
| Nifty 50 / Nifty Bank | Angel One index quotes |
| FII/DII, Brent, DXY, global indices | Static fallback in UI |
| India-focused market news | Moneycontrol, Investing.com, LiveMint, Economic Times RSS |

Edit watchlist tokens in [`symbols.py`](symbols.py) if a symbol fails to resolve.
Set `MARKET_FILTER_PROMPT` in `.env` to control the selection criteria for the dynamic top-20 universe.
Set `VOLUME_PRESELECT_LIMIT` (default `50`) to control how many highest-volume Nifty 500 stocks receive full intraday screening.
Set `MIN_PROMOTER_HOLDING_PCT` (default `60`) to enforce minimum promoter holding for short-term picks.
Set `RISKY_SYMBOL_DENYLIST` (comma-separated) to block speculative names (defaults include YESBANK, OLAELEC).
Set `MIN_RSI_PIVOT` (default `55`), `MIN_VOLUME_MULTIPLIER` (default `1.5`), and `MIN_TURNOVER_CR` (default `50`) for liquidity/momentum gates.
Set `REQUIRE_BULK_DEAL` (default `false`) to require an NSE bulk/block deal before a stock passes quality filters.
Set `MIN_BULK_DEAL_VALUE_CR` (default `5`) and `BULK_DEAL_LOOKBACK_HOURS` (default `24`) for bulk/block deal detection thresholds.
Set `BULK_DEAL_CACHE_TTL_SECONDS` (default `3600`) to control how often NSE bulk/block deals are refreshed.
Set `INTRADAY_CANDIDATE_LIMIT` in `.env` if you want to cap how many of those volume leaders are candle-screened before the LLM ranking pass (defaults to `VOLUME_PRESELECT_LIMIT`).

### Complete-universe market data

The official NSE Nifty 500 index snapshot (the same endpoint used by the heat
map) is the primary bulk-quote provider. Missing rows immediately fall back to
one Dhan bulk request, then Angel One for anything still absent. Dhan also
provides historical candles and instrument-id recovery:

```env
DHAN_CLIENT_ID=your_dhan_client_id
DHAN_ACCESS_TOKEN=your_dhan_access_token
MARKET_DATA_MIN_COVERAGE_PCT=99
MARKET_DATA_MIN_CANDLE_COVERAGE_PCT=95
NIFTY_CACHE_EXPECTED_MIN=475
NIFTY_CACHE_MIN_COVERAGE_PCT=99
NIFTY_CACHE_MAX_AGE_SECONDS=86400
```

The service refuses to publish a new deterministic selection when quote or
candle coverage is below the configured threshold. Quote-derived placeholder
indicators are disabled by default. Inspect cache, provider counts and missing
symbols at `GET /api/market-data/coverage`. A partial cache is never allowed to
overwrite the last valid cache.
Nifty 500 symbols are stored in [`app/data/nifty500_symbols.json`](app/data/nifty500_symbols.json) and resolved to Angel One tokens in `nifty500_instruments.json` via `POST /api/refresh-instrument-cache`.
The backend refreshes live Angel One data and LLM-selected top 20 only during the IST refresh windows around **08:00-08:30** and **16:00-16:30**. Outside those windows it serves the last saved snapshot.
Manual refreshes are still allowed and will reuse the last saved snapshot when live or LLM refreshes are unavailable.

## Response shape

```json
{
  "success": true,
  "source": "angel_one",
  "updatedAt": "2026-05-31T12:00:00+00:00",
  "stockQuotes": {
    "RELIANCE": { "ltp": "₹2,450.20", "delta": "+1.20%", "state": "POSITIVE" }
  },
  "macroDataStrip": {
    "morning": [{ "label": "Nifty 50", "val": "23,740.50", "delta": "-1.39%", "state": "NEGATIVE" }],
    "evening": []
  }
}
```
