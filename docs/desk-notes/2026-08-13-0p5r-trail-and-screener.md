# Desk note — 13 Aug 2026

Live on Docker. DETERMINISTIC_BUY_V1 lock gates unchanged.

## What shipped

### 1. Trail / stop (intraday + swing SCALE_TRAIL)

| Before (this morning) | Now |
|---|---|
| BE / trail at **0.25R**, then 1R hybrid | BE / trail at **0.5R** |
| Initial SL from ATR (~1.2–3%+) | **New locks only:** SL cap **0.5%** of entry |
| Trail ratchet in R only | After 0.5R, trail also **≤ 0.5% behind MFE** |
| Open books retro-tightened if recapped | **Open books keep locked SL** (NESTLEIND / PFC / SWIGGY not yanked to 0.5%) |

Ratchet: `0.5R → BE`, `1.0–1.5R → BE`, `2R → 0.5R`, then structure analogue. Scale legs still 20/20/20 + 40% runner at 1 / 1.5 / 2R.

### 2. Swing hunt universe

- Hunt already uses volume-200 candles (not display-50 only).
- HOLD_FOR_DATA / missing risk is **not** a veto. REJECT still vetoes.
- Pre-filter snapshot: Chartink unofficial `screener/process` → Yahoo/yfinance fallback.
- `GET /api/swing-screener` · `POST /api/swing-screener/refresh`
- Pre-filter **reorders** hunt only. Lock still needs VWAP, EMA9, RSI≥55, R1, bullish OI, promoter≥60, wick≤0.25, EMA angle>45, turnover≥50 Cr.

Chartink has **no official free API**.

## Replay — same 13 Aug intraday fills, new exit math

Source: `intraday_session.json` triggered long+short + snapshot LTP/H/L. `after_close=False`. Original locked SL (not 0.5% recap).

Booked old plan **+₹4,580**. Mark-to-market new plan **+₹7,904**.

| Symbol | Side | Src | Old (0.25R) | MFE | New 0.5R / 0.5% trail | Δ |
|---|---|---|---:|---:|---:|---:|
| NTPC | L | LOCK | BE scratch ₹0 | 0.28R | still OPEN SL 336.05 · +₹440 | +440 |
| JIOFIN | L | LOCK | TRAIL 260.62 +₹1,561 | 0.60R | TRAIL 262.08 +₹2,690 | +1,129 |
| AARTIIND | L | LOCK | TRAIL 537.08 +₹1,152 | 0.63R | TRAIL 538.99 +₹1,866 | +714 |
| SONACOMS | L | REPL | RUNNING ₹0 | 0.18R | OPEN SL 777.80 · −₹440 | −440 |
| SHRIRAMFIN | L | REPL | BE scratch ₹0 | 0.49R | still OPEN SL 1100.14 · +₹132 | +132 |
| SWIGGY | L | REPL | RUNNING ₹0 | 0.10R | OPEN SL 267.27 · −₹832 | −832 |
| NESTLEIND | L | REPL | RUNNING ₹0 | 0.16R | OPEN SL 1471.95 · −₹416 | −416 |
| PFC | S | LOCK | RUNNING ₹0 | 0.18R | OPEN SL 379.30 · −₹906 | −906 |
| GAIL | S | LOCK | 1R+TRAIL 173.69 +₹1,866 | 1.19R | 1R + TRAIL 173.61 +₹2,031 | +165 |
| VEDL | S | REPL | BE scratch ₹0 | 0.48R | still OPEN SL 282.52 · +₹1,365 | +1,365 |
| TATASTEEL | S | REPL | BE scratch ₹0 | 0.41R | still OPEN SL 190.05 · +₹695 | +695 |
| BIOCON | S | REPL | BE scratch ₹0 | 0.42R | still OPEN SL 432.02 · +₹841 | +841 |
| ICICIBANK | S | REPL | BE scratch ₹0 | 0.27R | still OPEN SL 1443.29 · +₹437 | +437 |

Names that never printed 0.5R stay on **initial SL**. That is why VEDL / TATASTEEL / BIOCON / ICICIBANK / NTPC / SHRIRAMFIN are still open instead of 0.25R BE scratches.

Running underwater (SONACOMS / SWIGGY / NESTLEIND / PFC) never reached 0.5R either — same as before; initial SL not hit.

## Not changed

- Selection contract DETERMINISTIC_BUY_V1
- LLM still top-10 only
- Manual broker execution
- JSON snapshots only
