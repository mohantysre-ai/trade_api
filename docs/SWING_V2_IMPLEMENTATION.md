# Swing 2-Session Momentum V2

SWING_2S_MOMENTUM_V2 is implemented as a deterministic, non-authoritative
shadow strategy. It intentionally cannot become live merely by changing an
environment variable.

## Safety state

- Default: SWING_V2_ENABLED=false and SWING_V2_MODE=SHADOW.
- Validation label: RESEARCH_HYPOTHESIS.
- Broker execution: disabled. The engine records paper observations only.
- V1 remains authoritative while V2 shadows, as required by the rollout plan.
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
GET /api/reports/eod-swing retain their V1 contracts. When V2 is enabled they
also expose a shadowV2 block. The frontend labels that block as non-authoritative
and displays coverage, regime, candidate funnel, ledger reconciliation and the
achieved validation state.

## Data activation contract

V2 does not reinterpret old V1 fields as institutional-quality facts. The
governed market snapshot must provide swingV2UniverseCoverage, swingV2Regime,
and a swingV2 enrichment per stock with point-in-time membership, 252 adjusted
observations, daily/5-minute features, source timestamps, depth, spread, modeled
cost, events, surveillance and price-band facts. Missing facts fail closed.

The current snapshot is Nifty-500 oriented, so turning on the feature before
the Nifty Total Market 750 ingestion is populated will correctly show
UNIVERSE_COVERAGE_BELOW_99PCT.

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
