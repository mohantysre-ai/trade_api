# Index Options data contract

The Index Options tab is automatic paper execution only. Angel One is the live
derivative-data provider. A candidate remains `NO_TRADE` when any required
evidence is absent, stale, or fails its hard gate. The engine has independent
long-premium and defined-risk premium-selling sleeves; neither sleeve may
override the other's gates.

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

If both Angel and ScanX remain unusable, Lemonn is the third chain source. It
posts `{"symbol":"NIFTY","expiry":"01SEP2026"}` (with the corresponding
index symbol) to `https://lemonn.co.in/api/get-option-chain`. Expiry is still
resolved dynamically: Angel's active master is preferred; when it is
unavailable, the nearest non-expired date is parsed from the applicable Lemonn
option-page expiry dropdown. Those page results are cached for six hours.

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

### Long premium

1. Fresh Angel spot, futures and option quotes.
2. Five-minute ORB break with EMA9/EMA20 alignment.
3. Index-futures price/OI alignment.
4. Option premium and OI rising together for the chosen side.
5. Official weighted constituent breadth at ±0.55 with at least 90% coverage.
6. Liquid ATM/near-ITM contract with delta 0.45–0.65 and spread ≤1.5%.
7. Projected option reward/risk ≥1.5.
8. VIX regime and deterministic score ≥80.
9. Correlation and daily-entry limits.

### Defined-risk premium selling

The seller sleeve never emits a naked short option. It constructs one of:

- bullish put credit spread after a confirmed bullish breakout;
- bearish call credit spread after a confirmed bearish breakout;
- iron condor when the completed 5-minute structure remains inside the ORB.

Every seller candidate requires:

1. Live chain, spot and completed 5-minute structure with at least 20 bars.
2. Executable entry credit using short-leg bid and hedge-leg ask.
3. A same-expiry, same-lot hedge wing beyond every short strike.
4. Positive net credit, positive theta and bounded net gamma.
5. Net-profit/max-loss of at least 0.20 after estimated entry and exit costs.
6. Short-leg IV at least 0.75 points and 1.05x above India VIX.
7. Rising OI with non-rising premium at every short wall, liquid legs and per-leg spread no wider than 2%.
8. At least 1 ATR short-strike cushion for an iron condor or 0.75 ATR for a directional credit spread.
9. Neutral breadth and subdued futures movement for condors; directional breadth and futures alignment for credit spreads.
10. Entries only from 09:45–14:30 IST; expiry-day entries stop at 13:30 IST.

Paper positions take profit after capturing 50% of entry credit, cap the loss
budget at the lower of 1.5x credit or 35% of defined maximum loss, exit on a
short-strike breach, and square off by 15:20 IST. Paper P&L remains a model and
does not claim broker fills or margin availability.

Paper entries also enforce configurable maximum-loss ceilings: ₹5,000 per
structure and ₹10,000 across open seller structures by default. Override them
with `INDEX_OPTIONS_SELLER_MAX_SINGLE_RISK` and
`INDEX_OPTIONS_SELLER_MAX_PORTFOLIO_RISK`.

The LLM does not select the side, strategy, strike, expiry, size, or override
any gate.
