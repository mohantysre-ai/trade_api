"""
IROS Cross-Sectional Intraday Scanner
======================================
Your feed is a SNAPSHOT scan across many stocks (Trendlyne-style), not a
per-stock OHLCV time series. So a literal "opening range breakout" can't be
computed from it directly — there's no 9:15-9:30 high/low here. Instead this
scanner uses the multi-timeframe fields the feed ALREADY gives you:

  Min5HighCurrentCandle / Min5EMA50CurrentCandle   -> 5-min structure
  Min15HighCurrentCandle / Min15EMA50CurrentCandle -> 15-min structure
  DaySMA50 / DaySMA200 / DayRSI14                  -> daily trend + momentum
  DayATR14CurrentCandleMul_2                       -> daily ATR (this field
                                                       is 2x ATR, so ATR = val/2)
  DeliveryData.DailyDeliveredPer                   -> conviction/liquidity filter

LOGIC (LONG example):
  1. Price is breaking/holding above the 15-min high  -> short-term breakout
  2. Price above BOTH 5-min and 15-min EMA50           -> intraday uptrend intact
  3. Price above daily SMA50                           -> aligned with daily trend
  4. Daily RSI(14) in a momentum band (not overbought/oversold blowoff)
  5. Delivery % above a floor                          -> real buying, not pure
                                                           intraday churn

NOTE ON DATA QUALITY: the `Pchange` field in your feed does not always match
(Ltp-Open)/Open for every row (e.g. some rows show a Pchange wildly out of
line with Open vs Ltp). This scanner does NOT use `Pchange` as given — it
recomputes price-change itself from Open/Ltp so a possibly-buggy upstream
field can't quietly corrupt the filter. Worth flagging to whoever owns that
feed on your end.

STOP / TARGET / BREAKEVEN ("cost to cost"):
  stop   = Ltp - ATR        (long)   /  Ltp + ATR   (short)
  target = entry + 2*risk   (long)   /  entry - 2*risk (short)
  Once live price moves +1R in your favor, move stop to entry (breakeven).
  This reuses the same TradeState engine from intraday_orb_scanner.py —
  see the bottom of this file for how they connect.
"""

import json
from dataclasses import dataclass, field
from typing import List, Optional


RSI_LONG_BAND = (50, 75)
RSI_SHORT_BAND = (25, 45)         # tightened from (25,50) — avoids near-neutral 45-50 zone
MIN_DELIVERY_PCT = 15.0          # filters out pure-churn/illiquid names
BREAKOUT_TOLERANCE = 0.999        # allow LTP within 0.1% of the 15m high (not just strictly above)
BREAKDOWN_TOLERANCE = 0.999       # LTP must be at least 0.1% BELOW 15m EMA50 for a real breakdown
TARGET_R_MULTIPLE = 2.0
TARGET_R_MULTIPLE_SHORT = 2.5    # shorts tend to move faster — wider target for better R:R


@dataclass
class ScanResult:
    symbol: str
    name: str
    direction: str
    entry: float
    stop_loss: float
    target: float
    risk_per_share: float
    rsi: float
    delivery_pct: Optional[float]
    reasons: List[str] = field(default_factory=list)
    score: float = 0.0


def _price_change_pct(open_, ltp):
    if not open_:
        return 0.0
    return (ltp - open_) / open_ * 100


def _safe(stock, *keys):
    """Return None if any required field is missing (many small/illiquid
    names in these feeds have partial data — skip rather than guess)."""
    vals = []
    for k in keys:
        v = stock.get(k)
        if v is None:
            return None
        vals.append(v)
    return vals


def evaluate_stock(stock: dict, direction: str = "LONG") -> Optional[ScanResult]:
    req = _safe(stock, "Ltp", "Open", "DayRSI14CurrentCandle", "DaySMA50CurrentCandle",
                "Min15HighCurrentCandle", "Min15EMA50CurrentCandle",
                "Min5EMA50CurrentCandle", "DayATR14CurrentCandleMul_2")
    if req is None:
        return None
    ltp, open_, rsi, sma50, m15_high, m15_ema50, m5_ema50, atr2 = req
    atr = atr2 / 2
    if atr <= 0:
        return None

    delivery_pct = (stock.get("DeliveryData") or {}).get("DailyDeliveredPer")
    price_chg = _price_change_pct(open_, ltp)
    reasons = []
    score = 0.0

    if direction == "LONG":
        rsi_ok = RSI_LONG_BAND[0] <= rsi <= RSI_LONG_BAND[1]
        breakout_ok = ltp >= m15_high * BREAKOUT_TOLERANCE
        trend_ok = ltp > m5_ema50 and ltp > m15_ema50
        daily_trend_ok = ltp > sma50
        delivery_ok = delivery_pct is None or delivery_pct >= MIN_DELIVERY_PCT

        if not (rsi_ok and breakout_ok and trend_ok and daily_trend_ok and delivery_ok):
            return None

        reasons = [
            f"RSI {rsi:.1f} in momentum band {RSI_LONG_BAND}",
            f"LTP {ltp:.2f} at/above 15m high {m15_high:.2f}",
            f"Above 5m EMA50 ({m5_ema50:.2f}) and 15m EMA50 ({m15_ema50:.2f})",
            f"Above daily SMA50 ({sma50:.2f})",
        ]
        if delivery_pct is not None:
            reasons.append(f"Delivery {delivery_pct:.1f}% >= {MIN_DELIVERY_PCT}%")

        entry = ltp
        stop = entry - atr
        risk = entry - stop
        target = entry + TARGET_R_MULTIPLE * risk
        # simple composite score: momentum + trend distance, for ranking only
        score = (rsi - 50) + (ltp - sma50) / sma50 * 100 + (price_chg)

    elif direction == "SHORT":
        rsi_ok = RSI_SHORT_BAND[0] <= rsi <= RSI_SHORT_BAND[1]
        # Proper breakdown: LTP must be below 15m EMA50 by at least the
        # tolerance margin (not just "below 15m high / 0.999" which is
        # true for almost any stock). Also require LTP below the 15m
        # high to confirm we're not in an intraday bounce.
        breakdown_ok = ltp < m15_ema50 * BREAKDOWN_TOLERANCE and ltp < m15_high
        trend_ok = ltp < m5_ema50 and ltp < m15_ema50
        daily_trend_ok = ltp < sma50
        # Price must be down on the day (negative price change) — avoids
        # shorting stocks that are up but below EMA50 due to a pullback
        price_down_ok = price_chg < 0
        delivery_ok = delivery_pct is None or delivery_pct >= MIN_DELIVERY_PCT

        if not (rsi_ok and breakdown_ok and trend_ok and daily_trend_ok and price_down_ok and delivery_ok):
            return None

        reasons = [
            f"RSI {rsi:.1f} in momentum band {RSI_SHORT_BAND}",
            f"LTP {ltp:.2f} below 15m EMA50 ({m15_ema50:.2f}) by >0.1%",
            f"Below 5m EMA50 ({m5_ema50:.2f}) and 15m EMA50",
            f"Below daily SMA50 ({sma50:.2f})",
            f"Down {price_chg:.2f}% on the day (confirmed selling)",
        ]
        if delivery_pct is not None:
            reasons.append(f"Delivery {delivery_pct:.1f}% >= {MIN_DELIVERY_PCT}%")

        entry = ltp
        stop = entry + atr
        risk = stop - entry
        target = entry - TARGET_R_MULTIPLE_SHORT * risk
        # Score: reward momentum (low RSI), distance below SMA50, and
        # intraday decline magnitude — mirrors the LONG score structure
        score = (50 - rsi) + (sma50 - ltp) / sma50 * 100 + abs(price_chg)

    else:
        return None

    return ScanResult(
        symbol=stock.get("Sym", "?"),
        name=stock.get("DispSym", "?"),
        direction=direction,
        entry=round(entry, 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        risk_per_share=round(risk, 2),
        rsi=round(rsi, 1),
        delivery_pct=delivery_pct,
        reasons=reasons,
        score=round(score, 2),
    )


def scan_feed(payload: dict, direction: str = "LONG", top_n: int = 15) -> List[ScanResult]:
    results = []
    for stock in payload.get("data", []):
        r = evaluate_stock(stock, direction=direction)
        if r:
            results.append(r)
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


if __name__ == "__main__":
    with open("sample_feed.json") as f:
        payload = json.load(f)

    print(f"Total records in feed: {payload.get('tot_rec')}  (this sample has {len(payload['data'])} loaded)\n")

    for direction in ("LONG", "SHORT"):
        print(f"=== {direction} candidates ===")
        hits = scan_feed(payload, direction=direction, top_n=10)
        if not hits:
            print("  No candidates passed the filter in this sample.\n")
            continue
        for r in hits:
            print(f"  {r.symbol:12s} ({r.name})")
            print(f"     Entry {r.entry}  Stop {r.stop_loss}  Target {r.target}  Risk/share {r.risk_per_share}  Score {r.score}")
            for reason in r.reasons:
                print(f"       - {reason}")
        print()
