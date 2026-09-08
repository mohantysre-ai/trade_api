# Swing 2-Session Momentum V2

SWING_2S_MOMENTUM_V2 is implemented as a deterministic, paper-authoritative
Swing strategy. It intentionally cannot place a broker order or become
live-capital eligible merely by changing an environment variable.

## Safety state

- Production compose: SWING_STRATEGY_AUTHORITY=V2, SWING_V2_ENABLED=true and
  SWING_V2_MODE=PAPER. V1 is disabled for Swing selection and reporting.
- Validation label: RESEARCH_HYPOTHESIS.
- Broker execution: disabled. The engine records paper observations only.
- V2 is authoritative only for the application's modeled paper book. The UI
  continues to label it RESEARCH_HYPOTHESIS until the documented gates pass.
- Enabling V2 without 99% governed universe coverage or a rated regime produces
  a visible fail-closed reason instead of candidates.

## Architecture

The implementation lives under backend/app/services/swing_v2/.

| Area | Module |
| --- | --- |
| Typed/versioned policy | config.py, schemas.py |
| NSE session lifecycle | calendar.py |
| Point-in-time membership | universe.py |
| Source timestamps/freshness | data_quality.py |
| Liquidity/surveillance/cost gates | tradability.py |
| Pure momentum/intraday features | features.py |
| Independent champion/shadow setups | setups.py |
| Segment scoring and penalties | ranking.py |
| Shrunk empirical expectancy | calibration.py |
| Transparent market regime | regime.py |
| Risk, correlation and gap-stress sizing | risk.py, portfolio.py |
| Post-decision paper fills | execution.py, engine.py |
| D0/D1/D2 exits | lifecycle.py |
| SQLite-WAL append-only truth | ledger.py |
| Funnel/P&L reconciliation | reporting.py |
| V1-safe compatibility exposure | facade.py, shadow.py |
| Frozen promotion gates | validation.py |

GET /api/swing-session, POST /api/swing-session/lock, and
GET /api/reports/eod-swing retain their compatibility contracts but resolve
their Swing symbols, fills, lifecycle state and P&L from the V2 ledger when V2
authority is configured. No route falls back to V1. The desk scheduler scans
14:30–15:10 IST, freezes at 15:10, observes paper fills through 15:20 and
processes open positions through the D2 exit.

## Data activation contract

V2 does not reinterpret old V1 fields as institutional-quality facts. The
governed market snapshot must provide swingV2UniverseCoverage, swingV2Regime,
and a swingV2 enrichment per stock with point-in-time membership, 252 adjusted
observations, daily/5-minute features, source timestamps, depth, spread, modeled
cost, events, surveillance and price-band facts. Missing facts fail closed.

The V2 adapter evaluates the complete stockQuotes collection rather than the
50-card display list. The active paper universe is the official Nifty 100,
Midcap 150 and Smallcap 250 membership; Microcap remains measured but cannot
enter the paper book. Current official files can temporarily exceed their
nominal counts during corporate-action transitions. The immutable snapshot
records both the nominal 750 baseline and the complete official point-in-time
set; it never silently drops transition securities.

Official universe, surveillance and scheduled-result refresh failures, quote
coverage below 99%, missing depth, stale 5-minute bars or an unrated regime all
produce a visible cash-held decision. They never reactivate V1.

universe.py includes the official Nifty Indices segment CSV loader, immutable
date-stamped snapshots, exact 100/150/250/250 and 750-unique-symbol checks, and
Angel One instrument-resolution coverage. Historical research must retain each
dated snapshot; today's constituents are never projected backwards.

## Validation

    cd backend
    python -m pytest tests/test_swing_v2.py tests/test_swing_v2_specification.py -q

    cd ../iros-terminal
    npx tsc --noEmit

Research promotion still requires the specified point-in-time dataset,
walk-forward windows, untouched holdout, ablations, cost doubling and 300 OOS
fills. No synthetic result is included and no market-beating claim is made.
