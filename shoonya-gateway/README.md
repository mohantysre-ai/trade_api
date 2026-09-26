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

`SHOONYA_AUTH_MODE=manual` is the default. Complete the vendor OAuth login and POST
the result to `/admin/oauth/code` using `SHOONYA_ADMIN_TOKEN`.

## API

`GET /v1/health`, `GET /v1/quotes?symbols=A,B`, `POST /v1/pin`,
`POST /v1/unpin`, `GET /v1/candles`, and `WS /v1/stream`.
