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
- Set `LLM_MODEL=gemini-2.5-flash` or `gemini-2.5-pro` for richer analysis.
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
| Stock LTP (live Angel One universe, LLM-selected top 10) | Angel One `getMarketData` + LLM filter prompt |
| Nifty 50 / Nifty Bank | Angel One index quotes |
| FII/DII, Brent, DXY, global indices | Static fallback in UI |
| India-focused market news | Moneycontrol, Investing.com, LiveMint, Economic Times RSS |

Edit watchlist tokens in [`symbols.py`](symbols.py) if a symbol fails to resolve.
Set `MARKET_FILTER_PROMPT` in `.env` to control the selection criteria for the dynamic top-10 universe.
Set `INTRADAY_CANDIDATE_LIMIT` in `.env` if you want to change how many live symbols are candle-screened before the LLM ranking pass.
The backend refreshes live Angel One data and LLM-selected top 10 only during the IST refresh windows around **08:00-08:30** and **16:00-16:30**. Outside those windows it serves the last saved snapshot.
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
