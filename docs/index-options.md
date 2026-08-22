# Index Options data contract

The Index Options tab is advisory and manual-execution only. Angel One is the
live derivative-data provider. A candidate remains `NO_TRADE` when any required
evidence is absent, stale, or fails its hard gate.

## Angel One inputs

The backend reuses the existing server-side credentials:

- `ANGEL_API_KEY`
- `ANGEL_CLIENT_ID`
- `ANGEL_MPIN` (or `ANGEL_PASSWORD`)
- `ANGEL_TOTP_SECRET`

It loads Angel's current scrip master, resolves the nearest active expiry and
ATM ±3 index contracts, then fetches FULL quotes and live NSE Greeks. The
provider snapshot is cached for 15 seconds to coalesce UI polling.

If Angel returns no usable chain, the backend calls the unauthenticated ScanX
`optchainactive` endpoint for NIFTY (`Sid=13`), BANKNIFTY (`Sid=25`) or
FINNIFTY (`Sid=27`) and SENSEX (`Sid=51`). The `Exp` epoch comes from the nearest active expiry in
Angel's live instrument master. It is intentionally not calculated as “last
Thursday,” because exchange expiry weekdays and weekly/monthly availability can
change.

SENSEX option quotes come from Angel's BFO instruments. Angel's Greeks endpoint
is treated as NSE-only; SENSEX cannot pass the contract gate without separately
validated Greeks/IV evidence.

## Constituent weights

Weighted breadth is never equal-weighted or inferred. The market snapshot must
contain an official, effective-dated weight map:

```json
{
  "indexConstituentWeights": {
    "NIFTY": [
      {"symbol": "HDFCBANK", "weight": 10.27},
      {"symbol": "ICICIBANK", "weight": 9.22}
    ],
    "BANKNIFTY": [],
    "FINNIFTY": [],
    "SENSEX": []
  }
}
```

The complete list must cover at least 90% of official index weight and have
current VWAP/EMA inputs for those constituents. A partial top-heavy list does
not pass the breadth gate.

## Eligibility sequence

1. Fresh Angel spot, futures and option quotes.
2. Five-minute ORB break with EMA9/EMA20 alignment.
3. Index-futures price/OI alignment.
4. Option premium and OI rising together for the chosen side.
5. Official weighted constituent breadth at ±0.55 with at least 90% coverage.
6. Liquid ATM/near-ITM contract with delta 0.45–0.65 and spread ≤1.5%.
7. Projected option reward/risk ≥1.5.
8. VIX regime and deterministic score ≥80.
9. Correlation and daily-entry limits.

The LLM does not select the side, strike, expiry, size, or override any gate.
