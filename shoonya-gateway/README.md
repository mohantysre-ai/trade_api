# shoonya-gateway

Standalone service that talks to Finvasia/Shoonya (OAuth login, one WebSocket, TPSeries
candles) from a static-IPv4 host, and exposes a small internal API IROS reads as a
**hot-standby** market-data lane. It is not a bulk quote provider.

Market data only: `gateway/allowlist.py` hard-blocks every non-quote/candle/symbol-master
Shoonya endpoint.

## Run

    cp .env.example .env
    docker compose up --build

## Before going live

Run the Phase 0 validation against the real account first. Keep
`SHOONYA_STANDBY_ENABLED=0` until the WS token cap, REST limits, timestamp semantics,
and TPSeries field meanings are verified.

## Auth

Set `SHOONYA_AUTH_MODE=oauth_auto` for a scheduled daily headless OAuth login using
`SHOONYA_UID`, `SHOONYA_PASSWORD`, and `SHOONYA_TOTP_SECRET`. The same-day session is
restored after restarts. Manual fallback remains available through `/admin/oauth/url`
and `/admin/oauth/code` using `X-Admin-Token`. `/admin/oauth/refresh` runs the same
headless renewal immediately for validation or recovery.

## API

`GET /v1/health`, `GET /v1/quotes?symbols=A,B`, `POST /v1/pin`,
`POST /v1/unpin`, `GET /v1/candles`, and `WS /v1/stream`.
