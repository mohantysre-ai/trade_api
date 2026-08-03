"""Intraday session engine — Asset Metrics command center (manual execution only).

Funnel: Nifty 500 → regime → multi-factor score →
  10 LONG + 10 SHORT candidate pool (20) →
  adopt highest-probability 5 BUY + 5 SELL (10) → immutable JSON lock.

No broker order placement. Missing inputs → UNRATED / omitted, never invented.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_BASE = Path(__file__).resolve().parent

_LAST_MARKET_SNAPSHOT = _BASE / "last_market_snapshot.json"
_SESSION_FILE = Path(
    os.environ.get(
        "INTRADAY_SESSION_FILE",
        str(_BASE.parent.parent.parent / "intraday_session.json"),
    )
)
_FIXED_PLAN_FILE = Path(
    os.environ.get(
        "FIXED_PLAN_FILE",
        str(_BASE.parent.parent.parent / "fixed_trade_plan.json"),
    )
)

# Capital sleeves (₹)
LONG_CAPITAL = float(os.environ.get("INTRADAY_LONG_CAPITAL", "500000"))
SHORT_CAPITAL = float(os.environ.get("INTRADAY_SHORT_CAPITAL", "500000"))
RISK_FRACTION = float(os.environ.get("INTRADAY_RISK_FRACTION", "0.01"))  # of sleeve per name
ATR_STOP_MULT = float(os.environ.get("INTRADAY_ATR_STOP_MULT", "1.2"))
T1_R_LONG = float(os.environ.get("INTRADAY_T1_R_LONG", "1.5"))
T2_R_LONG = float(os.environ.get("INTRADAY_T2_R_LONG", "3.0"))
T1_R_SHORT = float(os.environ.get("INTRADAY_T1_R_SHORT", "1.5"))
T2_R_SHORT = float(os.environ.get("INTRADAY_T2_R_SHORT", "2.5"))
MAX_PER_SECTOR = int(os.environ.get("INTRADAY_MAX_PER_SECTOR", "3"))
MIN_TURNOVER_CR = float(os.environ.get("INTRADAY_MIN_TURNOVER_CR", "20"))
MIN_PRICE = float(os.environ.get("INTRADAY_MIN_PRICE", "50"))
MAX_PRICE = float(os.environ.get("INTRADAY_MAX_PRICE", "10000"))
MIN_ATR_PCT = float(os.environ.get("INTRADAY_MIN_ATR_PCT", "0.8"))
MAX_ATR_PCT = float(os.environ.get("INTRADAY_MAX_ATR_PCT", "12"))
SNAPSHOT_STALE_SEC = int(os.environ.get("INTRADAY_SNAPSHOT_STALE_SEC", "900"))

# Codex §6 weights (env-overridable starting params — not proven optimal)
W_REGIME = float(os.environ.get("INTRADAY_W_REGIME", "15"))
W_RS = float(os.environ.get("INTRADAY_W_RS", "15"))
W_TREND = float(os.environ.get("INTRADAY_W_TREND", "15"))
W_MOMENTUM = float(os.environ.get("INTRADAY_W_MOMENTUM", "10"))
W_VWAP = float(os.environ.get("INTRADAY_W_VWAP", "10"))
W_VOLUME = float(os.environ.get("INTRADAY_W_VOLUME", "10"))
W_BREAKOUT = float(os.environ.get("INTRADAY_W_BREAKOUT", "10"))
W_VOLATILITY = float(os.environ.get("INTRADAY_W_VOLATILITY", "5"))
W_SECTOR = float(os.environ.get("INTRADAY_W_SECTOR", "5"))
W_LIQUIDITY = float(os.environ.get("INTRADAY_W_LIQUIDITY", "5"))

# Candidate pool per side (20 total = 10 LONG + 10 SHORT), then adopt top LOCK_SIZE.
MOMENTUM_SLOTS = int(os.environ.get("INTRADAY_MOMENTUM_SLOTS", "6"))
MEANREV_SLOTS = int(os.environ.get("INTRADAY_MEANREV_SLOTS", "4"))
_BASKET_ENV = os.environ.get("INTRADAY_BASKET_SIZE")
# Candidate pool size per side (default 10 = 6 MOM + 4 MR)
BASKET_SIZE = int(_BASKET_ENV) if _BASKET_ENV else max(1, MOMENTUM_SLOTS + MEANREV_SLOTS)
# Locked desk: high-probability adoption from the 20 → 5 BUY + 5 SELL
LOCK_SIZE = int(os.environ.get("INTRADAY_LOCK_SIZE", "5"))

# Stocks-in-Play / ORB / overextension (starting params — not proven optimal)
INPLAY_RVOL = float(os.environ.get("INTRADAY_INPLAY_RVOL", "2.0"))
INPLAY_GAP_ATR_MULT = float(os.environ.get("INTRADAY_INPLAY_GAP_ATR_MULT", "0.5"))
ORB_INPLAY_MULT = float(os.environ.get("INTRADAY_ORB_INPLAY_MULT", "1.25"))
ORB_NOT_INPLAY_MULT = float(os.environ.get("INTRADAY_ORB_NOT_INPLAY_MULT", "0.7"))
ORB_DECAY_START_HHMM = os.environ.get("INTRADAY_ORB_DECAY_START", "1330")
ORB_DECAY_END_HHMM = os.environ.get("INTRADAY_ORB_DECAY_END", "1445")
EXT_ATR_THRESH = float(os.environ.get("INTRADAY_EXT_ATR_THRESH", "1.2"))
EXT_PENALTY = float(os.environ.get("INTRADAY_EXT_PENALTY", "20"))
GAP_FADE_PENALTY = float(os.environ.get("INTRADAY_GAP_FADE_PENALTY", "15"))

# Mean-reversion sleeve gate
MR_VIX_MAX = float(os.environ.get("INTRADAY_MR_VIX_MAX", "18"))
W_MR_VWAP = float(os.environ.get("INTRADAY_W_MR_VWAP", "40"))
W_MR_RSI = float(os.environ.get("INTRADAY_W_MR_RSI", "30"))
W_MR_GAP = float(os.environ.get("INTRADAY_W_MR_GAP", "30"))

# Lightweight sector hints for concentration caps (facts from ticker identity only).
_SECTOR_HINTS: dict[str, str] = {
    "HDFCBANK": "BANKING", "ICICIBANK": "BANKING", "SBIN": "BANKING", "KOTAKBANK": "BANKING",
    "AXISBANK": "BANKING", "INDUSINDBK": "BANKING", "BANKBARODA": "BANKING", "PNB": "BANKING",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT", "LTIM": "IT",
    "PERSISTENT": "IT", "COFORGE": "IT", "MPHASIS": "IT",
    "RELIANCE": "ENERGY", "ONGC": "ENERGY", "BPCL": "ENERGY", "IOC": "ENERGY", "GAIL": "ENERGY",
    "NTPC": "POWER", "POWERGRID": "POWER", "TATAPOWER": "POWER", "ADANIGREEN": "POWER",
    "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA", "DIVISLAB": "PHARMA",
    "AUROPHARMA": "PHARMA", "LUPIN": "PHARMA", "BIOCON": "PHARMA",
    "MARUTI": "AUTO", "TATAMOTORS": "AUTO", "M&M": "AUTO", "BAJAJ-AUTO": "AUTO",
    "HEROMOTOCO": "AUTO", "EICHERMOT": "AUTO", "TVSMOTOR": "AUTO",
    "TATASTEEL": "METALS", "JSWSTEEL": "METALS", "HINDALCO": "METALS", "VEDL": "METALS",
    "COALINDIA": "METALS", "NMDC": "METALS",
    "ITC": "FMCG", "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "DABUR": "FMCG", "MARICO": "FMCG", "GODREJCP": "FMCG",
    "BHARTIARTL": "TELECOM", "IDEA": "TELECOM",
    "LT": "INFRA", "ULTRACEMCO": "CEMENT", "AMBUJACEM": "CEMENT", "ACC": "CEMENT",
    "DLF": "REALTY", "GODREJPROP": "REALTY", "OBEROIRLTY": "REALTY",
    "BAJFINANCE": "FINANCE", "BAJAJFINSV": "FINANCE", "HDFCLIFE": "FINANCE",
    "SBILIFE": "FINANCE", "ICICIPRULI": "FINANCE", "PFC": "FINANCE", "RECLTD": "FINANCE",
}


def _ist_now() -> datetime:
    return datetime.now(tz=_IST)


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _safe_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        if isinstance(v, str):
            cleaned = v.replace(",", "").replace("₹", "").replace("%", "").strip()
            if cleaned in ("", "-", "—", "N/A"):
                return default
            return float(cleaned)
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def load_market_snapshot() -> dict[str, Any]:
    try:
        return json.loads(_LAST_MARKET_SNAPSHOT.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        log.warning("Failed to load market snapshot: %s", exc)
        return {}


def load_session() -> dict[str, Any]:
    try:
        data = json.loads(_SESSION_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_session(payload: dict[str, Any]) -> None:
    _atomic_write(_SESSION_FILE, payload)


def _sector_of(symbol: str, row: dict[str, Any] | None = None) -> str:
    sym = (symbol or "").upper()
    if row:
        for key in ("sector", "industry", "capSize"):
            raw = row.get(key)
            if isinstance(raw, str) and raw.strip() and raw.strip().upper() not in ("", "NA", "N/A"):
                # capSize is Large/Mid/Small — weak sector proxy; prefer explicit sector
                if key == "capSize":
                    continue
                return raw.strip().upper()
    return _SECTOR_HINTS.get(sym, "OTHER")


def _macro_lookup(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    strip = snapshot.get("macroDataStrip") or {}
    rows = strip.get("morning") or strip.get("evening") or []
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        out[label.upper()] = row
    return out


def _parse_delta_pct(delta: Any) -> float | None:
    if delta is None:
        return None
    if isinstance(delta, (int, float)):
        return float(delta)
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", str(delta).replace(",", ""))
    return float(m.group(1)) if m else None


def detect_regime(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Regime from NIFTY / BANKNIFTY / India VIX macros → RISK_ON|NEUTRAL|RISK_OFF.

    No invented levels. Missing macros → UNRATED (gates neutral 0.5).
    """
    macros = _macro_lookup(snapshot)
    nifty = macros.get("NIFTY 50") or macros.get("NIFTY50")
    bank = macros.get("NIFTY BANK") or macros.get("BANK NIFTY")
    vix = macros.get("INDIA VIX") or macros.get("INDIAVIX")

    nifty_chg = _parse_delta_pct((nifty or {}).get("delta"))
    bank_chg = _parse_delta_pct((bank or {}).get("delta"))
    vix_val = _safe_float((vix or {}).get("val"))

    label = "UNRATED"
    bias = "NEUTRAL"
    reasons: list[str] = []

    if nifty_chg is None and bank_chg is None and vix_val is None:
        reasons.append("macro strip missing NIFTY/BANKNIFTY/VIX")
        return {
            "label": label,
            "regime": label,
            "bias": bias,
            "niftyChangePct": nifty_chg,
            "bankNiftyChangePct": bank_chg,
            "indiaVix": vix_val,
            "nifty": (nifty or {}).get("val"),
            "bankNifty": (bank or {}).get("val"),
            "reasons": reasons,
            "longGate": 0.5,
            "shortGate": 0.5,
        }

    # Elevated VIX → RISK_OFF (de-risk longs); otherwise tape-driven.
    if vix_val is not None and vix_val >= 20:
        label = "RISK_OFF"
        bias = "SHORT_BIAS"
        reasons.append(f"India VIX {vix_val:.1f} elevated")
        long_gate, short_gate = 0.35, 0.55
    elif nifty_chg is not None and bank_chg is not None:
        if nifty_chg >= 0.35 and bank_chg >= 0.2:
            label = "RISK_ON"
            bias = "LONG_BIAS"
            reasons.append("NIFTY+Bank Nifty both green")
            long_gate, short_gate = 1.0, 0.55
        elif nifty_chg <= -0.35 and bank_chg <= -0.2:
            label = "RISK_OFF"
            bias = "SHORT_BIAS"
            reasons.append("NIFTY+Bank Nifty both red")
            long_gate, short_gate = 0.55, 1.0
        else:
            label = "NEUTRAL"
            bias = "NEUTRAL"
            reasons.append("mixed index tape")
            long_gate, short_gate = 0.75, 0.75
    elif nifty_chg is not None:
        if nifty_chg >= 0.4:
            label, bias, long_gate, short_gate = "RISK_ON", "LONG_BIAS", 0.95, 0.6
        elif nifty_chg <= -0.4:
            label, bias, long_gate, short_gate = "RISK_OFF", "SHORT_BIAS", 0.6, 0.95
        else:
            label, bias, long_gate, short_gate = "NEUTRAL", "NEUTRAL", 0.75, 0.75
        reasons.append("regime from NIFTY only (Bank Nifty missing)")
    else:
        label, bias, long_gate, short_gate = "NEUTRAL", "NEUTRAL", 0.7, 0.7
        reasons.append("partial macros")

    return {
        "label": label,
        "regime": label,
        "bias": bias,
        "niftyChangePct": nifty_chg,
        "bankNiftyChangePct": bank_chg,
        "indiaVix": vix_val,
        "nifty": (nifty or {}).get("val"),
        "bankNifty": (bank or {}).get("val"),
        "indiaVixDisplay": (vix or {}).get("val"),
        "reasons": reasons,
        "longGate": long_gate,
        "shortGate": short_gate,
    }


def _universe_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer stockQuotes (fuller universe); enrich from stocks[] when present."""
    quotes = snapshot.get("stockQuotes") or {}
    stocks = {str(s.get("ticker") or "").upper(): s for s in (snapshot.get("stocks") or []) if s.get("ticker")}
    rows: list[dict[str, Any]] = []
    if isinstance(quotes, dict) and quotes:
        for sym, q in quotes.items():
            if not isinstance(q, dict):
                continue
            key = str(sym or q.get("ticker") or "").upper()
            if not key or key.startswith("NIFTY") or "BANK NIFTY" in key:
                continue
            merged = {**q, **(stocks.get(key) or {}), "ticker": key}
            rows.append(merged)
    else:
        rows = list(stocks.values())
    return rows


def _passes_filters(row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ltp = _safe_float(row.get("ltpRaw") or row.get("ltp") or row.get("lastPrice"))
    intra = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    atr = _safe_float(intra.get("atr_pct"))
    turnover = _safe_float(intra.get("turnover_cr"))
    if ltp is None:
        reasons.append("missing LTP")
    elif ltp < MIN_PRICE or ltp > MAX_PRICE:
        reasons.append(f"price outside {MIN_PRICE}-{MAX_PRICE}")
    if atr is None:
        reasons.append("missing ATR%")
    elif atr < MIN_ATR_PCT or atr > MAX_ATR_PCT:
        reasons.append(f"ATR% outside {MIN_ATR_PCT}-{MAX_ATR_PCT}")
    if turnover is None:
        reasons.append("missing turnover")
    elif turnover < MIN_TURNOVER_CR:
        reasons.append(f"turnover under {MIN_TURNOVER_CR} Cr")
    return len(reasons) == 0, reasons


def _regime_risk_scale(regime: dict[str, Any], direction: str) -> float:
    """Defensive risk budget scalar from regime + India VIX (snapshot macros only).

    Pattern adapted from open-source regime/VIX gates (e.g. defensive mode when
    elevated vol): shrink risk when fighting the tape or when VIX is elevated.
    Does not invent win rates — only scales RISK_FRACTION.
    """
    label = str(regime.get("label") or regime.get("regime") or "UNRATED")
    vix = _safe_float(regime.get("indiaVix"))
    is_long = direction == "LONG"
    scale = 1.0
    if label == "RISK_OFF":
        scale *= 0.70 if is_long else 1.0
    elif label == "RISK_ON":
        scale *= 1.0 if is_long else 0.85
    elif label == "UNRATED":
        scale *= 0.85
    if vix is not None:
        if vix >= 25:
            scale *= 0.60
        elif vix >= 20:
            scale *= 0.80
    return max(0.40, min(1.10, scale))


# NSE cumulative volume fraction U-curve (heuristic average — Wood/McInish/Ord style).
# Minutes from 09:15 IST → expected fraction of full-day volume.
_NSE_CUM_VOL_CURVE: list[tuple[int, float]] = [
    (0, 0.02),     # 09:15
    (30, 0.18),    # 09:45
    (75, 0.30),    # 10:30
    (135, 0.42),   # 11:30
    (195, 0.52),   # 12:30
    (255, 0.62),   # 13:30
    (315, 0.80),   # 14:30
    (345, 0.92),   # 15:00
    (375, 1.00),   # 15:30
]


def _hhmm_to_minutes(hhmm: str) -> int:
    raw = "".join(c for c in str(hhmm) if c.isdigit()).zfill(4)[:4]
    try:
        return int(raw[:2]) * 60 + int(raw[2:4])
    except ValueError:
        return 13 * 60 + 30


def _nse_cum_vol_frac(now: datetime | None = None) -> float:
    """Heuristic cumulative volume fraction for NSE session. Label as heuristic in UI."""
    t = now or _ist_now()
    mins = t.hour * 60 + t.minute
    session_open = 9 * 60 + 15
    elapsed = mins - session_open
    if elapsed <= 0:
        return 0.02
    if elapsed >= 375:
        return 1.0
    prev_m, prev_f = _NSE_CUM_VOL_CURVE[0]
    for m, f in _NSE_CUM_VOL_CURVE[1:]:
        if elapsed <= m:
            span = max(m - prev_m, 1)
            return prev_f + (f - prev_f) * (elapsed - prev_m) / span
        prev_m, prev_f = m, f
    return 1.0


def _rvol_time(intra: dict[str, Any], now: datetime | None = None) -> tuple[float | None, float]:
    """Time-normalized relative volume. Returns (rvolTime, cumFracUsed)."""
    today = _safe_float(intra.get("today_volume"))
    avg20 = _safe_float(intra.get("avg_daily_volume_20"))
    cum = _nse_cum_vol_frac(now)
    if today is None or avg20 is None or avg20 <= 0 or cum <= 0:
        return None, cum
    return today / (avg20 * cum), cum


def _gap_and_intraday(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """gapPct, intradayRet, dayChg — None when inputs missing (never invent)."""
    ltp = _safe_float(row.get("ltpRaw") or row.get("ltp"))
    open_ = _safe_float(row.get("open"))
    close = _safe_float(row.get("close"))  # prev close in snapshot convention
    gap = None
    intra_ret = None
    day_chg = None
    if open_ is not None and close is not None and close > 0 and open_ > 0:
        gap = ((open_ - close) / close) * 100.0
    if ltp is not None and open_ is not None and open_ > 0:
        intra_ret = ((ltp - open_) / open_) * 100.0
    if ltp is not None and close is not None and close > 0:
        day_chg = ((ltp - close) / close) * 100.0
    return gap, intra_ret, day_chg


def _orb_time_decay(now: datetime | None = None) -> float:
    """1.0 before decay start → 0.0 at end. Applied as damp toward 50."""
    t = now or _ist_now()
    mins = t.hour * 60 + t.minute
    start = _hhmm_to_minutes(ORB_DECAY_START_HHMM)
    end = _hhmm_to_minutes(ORB_DECAY_END_HHMM)
    if mins <= start:
        return 1.0
    if mins >= end or end <= start:
        return 0.0
    return max(0.0, 1.0 - (mins - start) / (end - start))


def _meanrev_gate_open(regime: dict[str, Any]) -> tuple[bool, str]:
    """MR sleeve only when NEUTRAL and VIX < MR_VIX_MAX."""
    label = str(regime.get("label") or regime.get("regime") or "UNRATED")
    vix = _safe_float(regime.get("indiaVix"))
    if label != "NEUTRAL":
        return False, f"regime {label} (MR requires NEUTRAL)"
    if vix is None:
        return False, "India VIX missing (MR gated)"
    if vix >= MR_VIX_MAX:
        return False, f"VIX {vix:.1f} ≥ {MR_VIX_MAX} (MR gated)"
    return True, f"NEUTRAL + VIX {vix:.1f} < {MR_VIX_MAX}"


def _attach_percentile_ranks(bucket: list[dict[str, Any]]) -> None:
    """Alphalens-style cross-section percentile ranks (0–100) in-place."""
    n = len(bucket)
    if n == 0:
        return
    if n == 1:
        bucket[0]["scorePctRank"] = 50.0
        bucket[0]["intradayRetPctRank"] = 50.0
        return
    by_score = sorted(range(n), key=lambda i: float(bucket[i].get("score") or 0.0))
    for rank_i, idx in enumerate(by_score):
        bucket[idx]["scorePctRank"] = round(100.0 * rank_i / (n - 1), 1)

    def _intra_key(i: int) -> float:
        v = bucket[i].get("intradayRet")
        return float(v) if v is not None else float("-inf")

    by_intra = sorted(range(n), key=_intra_key)
    rated_intra = [i for i in by_intra if bucket[i].get("intradayRet") is not None]
    for idx in by_intra:
        if bucket[idx].get("intradayRet") is None:
            bucket[idx]["intradayRetPctRank"] = None
    m = len(rated_intra)
    if m == 1:
        bucket[rated_intra[0]]["intradayRetPctRank"] = 50.0
    elif m > 1:
        for rank_i, idx in enumerate(rated_intra):
            bucket[idx]["intradayRetPctRank"] = round(100.0 * rank_i / (m - 1), 1)


def _factor_scores(row: dict[str, Any], regime: dict[str, Any], direction: str) -> dict[str, Any]:
    """Return 0–100 sub-scores. Missing inputs → neutral 50 or UNRATED component.

    Upgrades (hedge-fund patterns, starting params — not proven optimal):
    - Time-normalized rvol (U-curve heuristic)
    - Overnight/intraday decomposition in RS + momentum (Lou-Polk-Skouras)
    - Stocks-in-Play ORB gate + time decay (Zarattini-Aziz)
    - Overextension reversal guard
    - Regime-switched VWAP (trend vs reversion)
    """
    intra = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    ltp = _safe_float(row.get("ltpRaw") or row.get("ltp"))
    open_ = _safe_float(row.get("open"))
    high = _safe_float(row.get("high"))
    low = _safe_float(row.get("low"))
    close = _safe_float(row.get("close"))
    vwap = _safe_float(intra.get("vwap"))
    ema9 = _safe_float(intra.get("ema9"))
    atr = _safe_float(intra.get("atr_pct"))
    vol_mult_raw = _safe_float(intra.get("volume_multiplier")) or _safe_float(intra.get("relative_volume"))
    rvol_t, cum_frac = _rvol_time(intra)
    vol_mult = rvol_t if rvol_t is not None else vol_mult_raw
    turnover = _safe_float(intra.get("turnover_cr"))
    breakout_q = _safe_float(intra.get("breakout_quality"))
    sector_s = _safe_float(intra.get("sector_strength"))
    liq = _safe_float(intra.get("liquidity_score"))
    rsi = _safe_float(intra.get("rsi"))
    orb_high = _safe_float(intra.get("orb_high"))
    orb_low = _safe_float(intra.get("orb_low"))
    orb_vel = _safe_float(intra.get("orb_velocity_pct"))
    above_vwap = intra.get("price_above_vwap")
    above_ema = intra.get("price_above_ema9")
    vwap_source = str(intra.get("vwap_source") or intra.get("vwapSource") or "snapshot")

    gap_pct, intraday_ret, day_chg = _gap_and_intraday(row)
    # Prefer intraday return for RS/momentum; fall back to day_chg
    move_pct = intraday_ret if intraday_ret is not None else day_chg

    is_long = direction == "LONG"
    gate = float(regime.get("longGate") if is_long else regime.get("shortGate") or 0.5)
    regime_score = _clamp(gate * 100)
    nifty_chg = _safe_float(regime.get("niftyChangePct"))
    regime_label = str(regime.get("label") or regime.get("regime") or "UNRATED")
    vix = _safe_float(regime.get("indiaVix"))

    # --- Relative strength (intraday excess vs NIFTY day-chg proxy) ---
    rs_vs_index = None
    if move_pct is None:
        rs = 50.0
        rs_rated = False
    else:
        rs_rated = True
        if nifty_chg is not None:
            rs_vs_index = move_pct - nifty_chg
            rs = _clamp(50 + rs_vs_index * 10) if is_long else _clamp(50 - rs_vs_index * 10)
        else:
            rs = _clamp(50 + move_pct * 8) if is_long else _clamp(50 - move_pct * 8)
        # Gap-fade penalty: gap same sign as direction thesis but intraday reverses
        if gap_pct is not None and intraday_ret is not None:
            if is_long and gap_pct > 0.3 and intraday_ret < -0.1:
                rs = _clamp(rs - GAP_FADE_PENALTY)
            elif not is_long and gap_pct < -0.3 and intraday_ret > 0.1:
                rs = _clamp(rs - GAP_FADE_PENALTY)

    # --- Trend: VWAP + EMA alignment ---
    trend_pts = 50.0
    trend_rated = False
    if above_vwap is not None or above_ema is not None:
        trend_rated = True
        pts = 50.0
        if above_vwap is True:
            pts += 20 if is_long else -20
        elif above_vwap is False:
            pts += -15 if is_long else 20
        if above_ema is True:
            pts += 15 if is_long else -15
        elif above_ema is False:
            pts += -10 if is_long else 15
        trend_pts = _clamp(pts)

    # --- Momentum + overextension guard ---
    overextended = False
    if move_pct is None and rsi is None:
        mom = 50.0
        mom_rated = False
    else:
        mom_rated = True
        base = 50.0
        if move_pct is not None:
            base += (move_pct * 6) if is_long else (-move_pct * 6)
        if rsi is not None:
            if is_long:
                base += (rsi - 50) * 0.4
            else:
                base += (50 - rsi) * 0.4
        # Overextension: |intradayRet|/atr > thresh → damp chase
        if intraday_ret is not None and atr is not None and atr > 0:
            ext = intraday_ret / atr
            long_chase = is_long and ext > EXT_ATR_THRESH
            # India evidence: dips correct faster — slightly larger long-chase penalty
            short_chase = (not is_long) and ext < -EXT_ATR_THRESH
            if long_chase or short_chase:
                overextended = True
                pen = EXT_PENALTY
                if long_chase:
                    pen *= 1.15  # asymmetric
                if regime_label == "RISK_ON" and is_long:
                    pen *= 0.5
                if regime_label == "RISK_OFF" and not is_long:
                    pen *= 0.5
                base -= pen
        mom = _clamp(base)

    # --- VWAP: regime-switched trend vs reversion ---
    vwap_mode = "UNRATED"
    vwap_z = None
    if ltp is None or vwap is None or vwap <= 0:
        vwap_s = 50.0
        vwap_rated = False
    else:
        vwap_rated = True
        dist = ((ltp - vwap) / vwap) * 100.0
        use_reversion = (
            regime_label == "NEUTRAL"
            and vix is not None
            and vix < MR_VIX_MAX
        )
        if use_reversion and atr is not None and atr > 0:
            vwap_mode = "REVERSION"
            sigma = max(atr / (6.25 ** 0.5), 0.3)
            vwap_z = dist / sigma
            # Fade: long scores rise as z → −2; short as z → +2
            if is_long:
                vwap_s = _clamp(50 - vwap_z * 15)
            else:
                vwap_s = _clamp(50 + vwap_z * 15)
            if str(vwap_source).lower() in ("quote", "quote-proxy", "typical", "proxy"):
                vwap_s = _clamp(50 + (vwap_s - 50) * 0.6)
        else:
            vwap_mode = "TREND"
            vwap_s = _clamp(50 + dist * 10) if is_long else _clamp(50 - dist * 10)

    # --- Volume (time-normalized when available) ---
    if vol_mult is None:
        vol_s = 50.0
        vol_rated = False
    else:
        vol_rated = True
        vol_s = _clamp(min(vol_mult, 5.0) / 5.0 * 100)

    # --- Stocks in Play ---
    in_play = False
    in_play_reason = "not in play"
    if rvol_t is not None and rvol_t >= INPLAY_RVOL:
        in_play = True
        in_play_reason = f"rvolTime {rvol_t:.2f}× ≥ {INPLAY_RVOL}"
    elif gap_pct is not None and atr is not None and atr > 0 and abs(gap_pct) >= INPLAY_GAP_ATR_MULT * atr:
        in_play = True
        in_play_reason = f"|gap| {abs(gap_pct):.2f}% ≥ {INPLAY_GAP_ATR_MULT}×ATR"

    # --- Breakout: ORB + in-play gate + time decay ---
    bq_pts: float | None = None
    if breakout_q is not None:
        scaled = _clamp(breakout_q * 5)
        bq_pts = scaled if is_long else _clamp(100 - scaled)

    orb_pts: float | None = None
    orb_pos_pct: float | None = None
    if (
        ltp is not None
        and orb_high is not None
        and orb_low is not None
        and orb_high > 0
        and orb_low > 0
        and orb_high >= orb_low
    ):
        span = orb_high - orb_low
        if span > 0:
            orb_pos_pct = _clamp(((ltp - orb_low) / span) * 100.0)
        vol_ok = vol_mult is not None and vol_mult >= 1.5
        if is_long:
            if ltp >= orb_high:
                vel_bonus = min(max(orb_vel or 0.0, 0.0), 3.0) * 8.0
                orb_pts = _clamp(68.0 + vel_bonus + (12.0 if vol_ok else 0.0))
                if above_vwap is False:
                    orb_pts = _clamp(orb_pts - 15.0)
            elif ltp <= orb_low:
                orb_pts = 22.0
            else:
                pos = (ltp - orb_low) / span if span > 0 else 0.5
                orb_pts = _clamp(35.0 + pos * 20.0)
        else:
            if ltp <= orb_low:
                depth = ((orb_low - ltp) / orb_low) * 100.0 if orb_low else 0.0
                depth_bonus = min(max(depth, 0.0), 3.0) * 8.0
                orb_pts = _clamp(68.0 + depth_bonus + (12.0 if vol_ok else 0.0))
                if above_vwap is True:
                    orb_pts = _clamp(orb_pts - 15.0)
            elif ltp >= orb_high:
                orb_pts = 22.0
            else:
                pos = (orb_high - ltp) / span if span > 0 else 0.5
                orb_pts = _clamp(35.0 + pos * 20.0)

    if bq_pts is not None and orb_pts is not None:
        brk = _clamp(0.45 * bq_pts + 0.55 * orb_pts)
        brk_rated = True
    elif orb_pts is not None:
        brk = orb_pts
        brk_rated = True
    elif bq_pts is not None:
        brk = bq_pts
        brk_rated = True
    else:
        brk = 50.0
        brk_rated = False

    if brk_rated:
        mult = ORB_INPLAY_MULT if in_play else ORB_NOT_INPLAY_MULT
        brk = _clamp(50 + (brk - 50) * mult)
        decay = _orb_time_decay()
        brk = _clamp(50 + (brk - 50) * decay)

    # --- ATR suitability ---
    if atr is None:
        vola = 50.0
        vola_rated = False
    else:
        vola_rated = True
        ideal = 3.0
        vola = _clamp(100 - abs(atr - ideal) * 15)

    # --- Sector ---
    if sector_s is None:
        sec = 50.0
        sec_rated = False
    else:
        sec_rated = True
        scaled = _clamp(sector_s * 5)
        sec = scaled if is_long else _clamp(100 - scaled)

    # --- Liquidity ---
    if liq is None and turnover is None:
        liqs = 50.0
        liq_rated = False
    else:
        liq_rated = True
        if liq is not None:
            liqs = _clamp(liq * 5)
        else:
            liqs = _clamp(min(float(turnover or 0), 200) / 2)

    components = {
        "regime": {
            "score": round(regime_score, 1),
            "weight": W_REGIME,
            "rated": regime_label != "UNRATED",
        },
        "relativeStrength": {
            "score": round(rs, 1),
            "weight": W_RS,
            "rated": rs_rated,
            "rsVsIndexPct": None if rs_vs_index is None else round(rs_vs_index, 3),
            "niftyChangePct": nifty_chg,
            "gapPct": None if gap_pct is None else round(gap_pct, 3),
            "intradayRet": None if intraday_ret is None else round(intraday_ret, 3),
        },
        "trend": {"score": round(trend_pts, 1), "weight": W_TREND, "rated": trend_rated},
        "momentum": {
            "score": round(mom, 1),
            "weight": W_MOMENTUM,
            "rated": mom_rated,
            "overextended": overextended,
        },
        "vwap": {
            "score": round(vwap_s, 1),
            "weight": W_VWAP,
            "rated": vwap_rated,
            "vwapMode": vwap_mode,
            "vwapZ": None if vwap_z is None else round(vwap_z, 3),
            "vwapSource": vwap_source,
            "vwap": vwap,
        },
        "volume": {
            "score": round(vol_s, 1),
            "weight": W_VOLUME,
            "rated": vol_rated,
            "rvolTime": None if rvol_t is None else round(rvol_t, 3),
            "rvolRaw": vol_mult_raw,
            "cumVolFracHeuristic": round(cum_frac, 3),
        },
        "breakout": {
            "score": round(brk, 1),
            "weight": W_BREAKOUT,
            "rated": brk_rated,
            "orbHigh": orb_high,
            "orbLow": orb_low,
            "orbVelocityPct": orb_vel,
            "orbPosPct": None if orb_pos_pct is None else round(orb_pos_pct, 1),
            "inPlay": in_play,
            "inPlayReason": in_play_reason,
            "orbDecay": round(_orb_time_decay(), 3),
        },
        "volatility": {"score": round(vola, 1), "weight": W_VOLATILITY, "rated": vola_rated},
        "sector": {"score": round(sec, 1), "weight": W_SECTOR, "rated": sec_rated},
        "liquidity": {"score": round(liqs, 1), "weight": W_LIQUIDITY, "rated": liq_rated},
    }

    rated = [c for c in components.values() if c["rated"]]
    if not rated:
        return {
            "score": None,
            "label": "UNRATED",
            "components": components,
            "dayChangePct": day_chg,
            "gapPct": gap_pct,
            "intradayRet": intraday_ret,
            "inPlay": in_play,
            "rsVsIndexPct": rs_vs_index,
        }

    total_w = sum(c["weight"] for c in rated)
    if total_w <= 0:
        return {
            "score": None,
            "label": "UNRATED",
            "components": components,
            "dayChangePct": day_chg,
            "gapPct": gap_pct,
            "intradayRet": intraday_ret,
            "inPlay": in_play,
            "rsVsIndexPct": rs_vs_index,
        }

    score = sum(c["score"] * c["weight"] for c in rated) / total_w
    return {
        "score": round(_clamp(score), 1),
        "label": "SCORED",
        "components": components,
        "dayChangePct": day_chg,
        "gapPct": None if gap_pct is None else round(gap_pct, 3),
        "intradayRet": None if intraday_ret is None else round(intraday_ret, 3),
        "inPlay": in_play,
        "inPlayReason": in_play_reason,
        "rsVsIndexPct": rs_vs_index,
        "overextended": overextended,
        "vwapMode": vwap_mode,
        "open": open_,
        "high": high,
        "low": low,
        "vwap": vwap,
        "orbHigh": orb_high,
        "orbLow": orb_low,
        "orbPosPct": orb_pos_pct,
    }


def _factor_scores_meanrev(row: dict[str, Any], regime: dict[str, Any], direction: str) -> dict[str, Any]:
    """Mean-reversion sleeve score. Gated: NEUTRAL + VIX < MR_VIX_MAX, else UNRATED."""
    gate_ok, gate_reason = _meanrev_gate_open(regime)
    intra = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    ltp = _safe_float(row.get("ltpRaw") or row.get("ltp"))
    vwap = _safe_float(intra.get("vwap"))
    atr = _safe_float(intra.get("atr_pct"))
    rsi = _safe_float(intra.get("rsi"))
    vwap_source = str(intra.get("vwap_source") or intra.get("vwapSource") or "snapshot")
    gap_pct, intraday_ret, day_chg = _gap_and_intraday(row)
    is_long = direction == "LONG"

    empty_components = {
        "vwapFade": {"score": 50.0, "weight": W_MR_VWAP, "rated": False},
        "rsiFade": {"score": 50.0, "weight": W_MR_RSI, "rated": False},
        "gapFade": {"score": 50.0, "weight": W_MR_GAP, "rated": False},
    }

    if not gate_ok:
        return {
            "score": None,
            "label": "UNRATED",
            "gateOpen": False,
            "gateReason": gate_reason,
            "components": empty_components,
            "dayChangePct": day_chg,
            "gapPct": gap_pct,
            "intradayRet": intraday_ret,
        }

    # VWAP z fade
    vwap_s = 50.0
    vwap_rated = False
    vwap_z = None
    if ltp is not None and vwap is not None and vwap > 0 and atr is not None and atr > 0:
        vwap_rated = True
        dist = ((ltp - vwap) / vwap) * 100.0
        sigma = max(atr / (6.25 ** 0.5), 0.3)
        vwap_z = dist / sigma
        # Long fade when overextended above VWAP (z high → want SHORT fade = high short score)
        # For LONG MR: want z negative (price below VWAP → bounce)
        if is_long:
            vwap_s = _clamp(50 - vwap_z * 20)
        else:
            vwap_s = _clamp(50 + vwap_z * 20)
        if str(vwap_source).lower() in ("quote", "quote-proxy", "typical", "proxy"):
            vwap_s = _clamp(50 + (vwap_s - 50) * 0.6)

    # RSI fade
    rsi_s = 50.0
    rsi_rated = False
    if rsi is not None:
        rsi_rated = True
        if is_long:
            # Oversold → long fade
            rsi_s = _clamp(50 + (50 - rsi) * 1.2)
        else:
            # Overbought → short fade
            rsi_s = _clamp(50 + (rsi - 50) * 1.2)

    # Gap fade: large gap + intraday giveback favors fade direction
    gap_s = 50.0
    gap_rated = False
    if gap_pct is not None and intraday_ret is not None:
        gap_rated = True
        if is_long:
            # Gap down + stabilizing / reclaiming → long fade candidate
            gap_s = _clamp(50 - gap_pct * 8 + max(intraday_ret, 0) * 4)
        else:
            # Gap up + giving back → short fade
            gap_s = _clamp(50 + gap_pct * 8 - min(intraday_ret, 0) * 4)

    components = {
        "vwapFade": {
            "score": round(vwap_s, 1),
            "weight": W_MR_VWAP,
            "rated": vwap_rated,
            "vwapZ": None if vwap_z is None else round(vwap_z, 3),
            "vwapSource": vwap_source,
            "vwap": vwap,
        },
        "rsiFade": {"score": round(rsi_s, 1), "weight": W_MR_RSI, "rated": rsi_rated, "rsi": rsi},
        "gapFade": {
            "score": round(gap_s, 1),
            "weight": W_MR_GAP,
            "rated": gap_rated,
            "gapPct": None if gap_pct is None else round(gap_pct, 3),
            "intradayRet": None if intraday_ret is None else round(intraday_ret, 3),
        },
        "gate": {"score": 100.0, "weight": 0, "rated": True, "reason": gate_reason},
    }

    rated = [c for c in components.values() if c["rated"] and c["weight"] > 0]
    if not rated:
        return {
            "score": None,
            "label": "UNRATED",
            "gateOpen": True,
            "gateReason": gate_reason,
            "components": components,
            "dayChangePct": day_chg,
            "gapPct": gap_pct,
            "intradayRet": intraday_ret,
        }

    total_w = sum(c["weight"] for c in rated)
    score = sum(c["score"] * c["weight"] for c in rated) / total_w
    return {
        "score": round(_clamp(score), 1),
        "label": "SCORED",
        "gateOpen": True,
        "gateReason": gate_reason,
        "components": components,
        "dayChangePct": day_chg,
        "gapPct": None if gap_pct is None else round(gap_pct, 3),
        "intradayRet": None if intraday_ret is None else round(intraday_ret, 3),
        "vwap": vwap,
        "orbHigh": _safe_float(intra.get("orb_high")),
        "orbLow": _safe_float(intra.get("orb_low")),
    }


def _build_levels(entry: float, atr_pct: float, direction: str) -> dict[str, float]:
    risk = entry * (atr_pct / 100.0) * ATR_STOP_MULT
    risk = max(risk, entry * 0.004)  # floor 0.4%
    if direction == "LONG":
        sl = entry - risk
        t1 = entry + risk * T1_R_LONG
        t2 = entry + risk * T2_R_LONG
        rr = T1_R_LONG
    else:
        sl = entry + risk
        t1 = entry - risk * T1_R_SHORT
        t2 = entry - risk * T2_R_SHORT
        rr = T1_R_SHORT
    return {
        "entryPrice": round(entry, 2),
        "stopLoss": round(sl, 2),
        "target1": round(t1, 2),
        "target2": round(t2, 2),
        "riskPerShare": round(risk, 2),
        "rewardRisk": round(rr, 2),
    }


def _size_position(
    entry: float,
    risk_per_share: float,
    sleeve: float,
    risk_scale: float = 1.0,
    *,
    basket_slots: int | None = None,
) -> dict[str, Any]:
    if entry <= 0 or risk_per_share <= 0:
        return {"approxQty": 0, "deployedCapital": 0.0, "maxLoss": 0.0, "riskScale": risk_scale}
    slots = max(1, int(basket_slots if basket_slots is not None else BASKET_SIZE))
    effective_frac = RISK_FRACTION * max(0.40, min(1.10, risk_scale))
    risk_budget = sleeve * effective_frac
    qty_by_risk = int(risk_budget // risk_per_share)
    qty_by_notional = int((sleeve / slots) // entry)
    qty = max(0, min(qty_by_risk, qty_by_notional))
    if qty <= 0 and entry <= sleeve:
        qty = 1
    deployed = round(qty * entry, 2)
    return {
        "approxQty": qty,
        "deployedCapital": deployed,
        "maxLoss": round(qty * risk_per_share, 2),
        "riskScale": round(risk_scale, 3),
        "effectiveRiskFraction": round(effective_frac, 4),
    }


def _adopt_high_probability(
    rows: list[dict[str, Any]],
    n: int,
    *,
    direction: str,
    capital: float,
    regime: dict[str, Any],
) -> list[dict[str, Any]]:
    """From candidate pool (≈10/side), keep top-n by score / in-play / RR — facts only."""
    if n <= 0 or not rows:
        return []
    ranked = sorted(
        rows,
        key=lambda r: (
            float(r.get("score") or 0.0),
            1.0 if r.get("inPlay") else 0.0,
            float(r.get("scorePctRank") or 0.0),
            float(r.get("rewardRisk") or 0.0),
        ),
        reverse=True,
    )
    adopted = ranked[:n]
    risk_scale = _regime_risk_scale(regime, direction)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(adopted):
        entry = float(row.get("entryPrice") or row.get("ltp") or 0)
        risk = float(row.get("riskPerShare") or 0)
        if entry <= 0:
            continue
        if risk <= 0:
            levels = _build_levels(entry, float(row.get("atrPct") or 1.5) or 1.5, direction)
            risk = float(levels.get("riskPerShare") or 0)
            row = {**row, **levels}
        sizing = _size_position(
            entry, risk, capital, risk_scale=risk_scale, basket_slots=LOCK_SIZE
        )
        out.append({
            **row,
            **sizing,
            "rank": i + 1,
            "adopted": True,
            "adoptReason": "HIGH_PROBABILITY_SCORE",
            "candidatePoolSize": len(rows),
        })
    return out


def _construct_side(
    scored: list[dict[str, Any]],
    direction: str,
    sleeve: float,
    regime: dict[str, Any] | None = None,
    slots: int | None = None,
    sleeve_label: str = "MOMENTUM",
    exclude_symbols: set[str] | None = None,
    sector_counts: dict[str, int] | None = None,
    start_rank: int = 0,
    max_per_sector: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Greedy pick with sector caps. Returns (picked, updated sector_counts)."""
    picked: list[dict[str, Any]] = []
    counts = dict(sector_counts or {})
    used = set(exclude_symbols or [])
    risk_scale = _regime_risk_scale(regime or {}, direction)
    limit = slots if slots is not None else BASKET_SIZE
    sector_cap = max_per_sector if max_per_sector is not None else MAX_PER_SECTOR
    for cand in scored:
        if len(picked) >= limit:
            break
        sym = cand.get("symbol")
        if not sym or sym in used:
            continue
        sector = cand.get("sector") or "OTHER"
        if counts.get(sector, 0) >= sector_cap:
            continue
        entry = cand.get("ltp")
        atr = cand.get("atrPct")
        if entry is None or atr is None:
            continue
        levels = _build_levels(float(entry), float(atr), direction)
        sizing = _size_position(
            levels["entryPrice"], levels["riskPerShare"], sleeve, risk_scale=risk_scale
        )
        if sizing["approxQty"] <= 0:
            continue
        counts[sector] = counts.get(sector, 0) + 1
        used.add(sym)
        rank = start_rank + len(picked) + 1
        picked.append({
            "rank": rank,
            "symbol": cand["symbol"],
            "name": cand.get("name"),
            "direction": direction,
            "sector": sector,
            "sleeve": sleeve_label,
            "score": cand.get("score"),
            "scorePctRank": cand.get("scorePctRank"),
            "intradayRetPctRank": cand.get("intradayRetPctRank"),
            "meanrevScore": cand.get("meanrevScore"),
            "gapPct": cand.get("gapPct"),
            "intradayRet": cand.get("intradayRet"),
            "inPlay": cand.get("inPlay"),
            "inPlayReason": cand.get("inPlayReason"),
            "rsVsIndexPct": cand.get("rsVsIndexPct"),
            "overextended": cand.get("overextended"),
            "vwapMode": cand.get("vwapMode"),
            "vwap": cand.get("vwap"),
            "orbHigh": cand.get("orbHigh"),
            "orbLow": cand.get("orbLow"),
            "orbPosPct": cand.get("orbPosPct"),
            "factorBreakdown": cand.get("components"),
            "ltp": round(float(entry), 2),
            "scanLtp": round(float(entry), 2),
            "atrPct": atr,
            "status": "RUNNING",
            "closed": False,
            **levels,
            **sizing,
        })
    return picked, counts


def _construct_dual_sleeve(
    mom_scored: list[dict[str, Any]],
    mr_scored: list[dict[str, Any]],
    direction: str,
    capital: float,
    regime: dict[str, Any],
    mr_gate_open: bool,
    exclude_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build momentum slots + mean-reversion slots; fill shortfall from momentum."""
    mom_slots = max(0, MOMENTUM_SLOTS)
    mr_slots = max(0, MEANREV_SLOTS) if mr_gate_open else 0
    picked: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}
    base_exclude = set(exclude_symbols or [])

    mom_picks, sector_counts = _construct_side(
        mom_scored, direction, capital, regime=regime,
        slots=mom_slots, sleeve_label="MOMENTUM",
        exclude_symbols=base_exclude,
        sector_counts=sector_counts, start_rank=0,
    )
    picked.extend(mom_picks)
    used = base_exclude | {p["symbol"] for p in picked}

    if mr_slots > 0:
        # Fresh sector budget so OTHER-heavy momentum does not crowd out MR
        mr_picks, mr_counts = _construct_side(
            mr_scored, direction, capital, regime=regime,
            slots=mr_slots, sleeve_label="MEAN_REVERSION",
            exclude_symbols=used, sector_counts={},
            start_rank=len(picked),
        )
        picked.extend(mr_picks)
        used |= {p["symbol"] for p in mr_picks}
        for sec, n in mr_counts.items():
            sector_counts[sec] = max(sector_counts.get(sec, 0), n)

    # Fill remaining to BASKET_SIZE from momentum; relax sector cap so basket completes
    remaining = BASKET_SIZE - len(picked)
    if remaining > 0:
        fill, sector_counts = _construct_side(
            mom_scored, direction, capital, regime=regime,
            slots=remaining, sleeve_label="MOMENTUM",
            exclude_symbols=used, sector_counts=sector_counts,
            start_rank=len(picked),
            max_per_sector=MAX_PER_SECTOR + 2,
        )
        picked.extend(fill)
        used |= {p["symbol"] for p in fill}

    # Last resort: ignore sector caps entirely to honor basket size when possible
    remaining = BASKET_SIZE - len(picked)
    if remaining > 0:
        fill2, _ = _construct_side(
            mom_scored, direction, capital, regime=regime,
            slots=remaining, sleeve_label="MOMENTUM",
            exclude_symbols=used, sector_counts={},
            start_rank=len(picked),
            max_per_sector=BASKET_SIZE,
        )
        picked.extend(fill2)

    for i, p in enumerate(picked):
        p["rank"] = i + 1
    return picked


def generate_candidates(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = snapshot if snapshot is not None else load_market_snapshot()
    updated_at = snap.get("updatedAt")
    snap_dt = _parse_iso(updated_at)
    age_sec = None
    if snap_dt is not None:
        age_sec = max(0, int((datetime.now(tz=timezone.utc) - snap_dt.astimezone(timezone.utc)).total_seconds()))
    stale = age_sec is None or age_sec > SNAPSHOT_STALE_SEC

    regime = detect_regime(snap)
    mr_gate_open, mr_gate_reason = _meanrev_gate_open(regime)
    rows = _universe_rows(snap)
    long_scored: list[dict[str, Any]] = []
    short_scored: list[dict[str, Any]] = []
    long_mr: list[dict[str, Any]] = []
    short_mr: list[dict[str, Any]] = []
    filter_reject = 0
    unrated = 0

    for row in rows:
        ok, reasons = _passes_filters(row)
        if not ok:
            filter_reject += 1
            continue
        sym = str(row.get("ticker") or "").upper()
        ltp = _safe_float(row.get("ltpRaw") or row.get("ltp"))
        intra = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
        atr = _safe_float(intra.get("atr_pct"))
        sector = _sector_of(sym, row)
        for direction, mom_bucket, mr_bucket in (
            ("LONG", long_scored, long_mr),
            ("SHORT", short_scored, short_mr),
        ):
            scored = _factor_scores(row, regime, direction)
            if scored.get("score") is None:
                unrated += 1
                continue
            base = {
                "symbol": sym,
                "name": row.get("name"),
                "sector": sector,
                "ltp": ltp,
                "atrPct": atr,
                "score": scored["score"],
                "components": scored.get("components"),
                "dayChangePct": scored.get("dayChangePct"),
                "gapPct": scored.get("gapPct"),
                "intradayRet": scored.get("intradayRet"),
                "inPlay": scored.get("inPlay"),
                "inPlayReason": scored.get("inPlayReason"),
                "rsVsIndexPct": scored.get("rsVsIndexPct"),
                "overextended": scored.get("overextended"),
                "vwapMode": scored.get("vwapMode"),
                "vwap": scored.get("vwap"),
                "orbHigh": scored.get("orbHigh"),
                "orbLow": scored.get("orbLow"),
                "orbPosPct": scored.get("orbPosPct"),
                "filterReasons": reasons,
            }
            mom_bucket.append(base)

            mr = _factor_scores_meanrev(row, regime, direction)
            if mr.get("score") is not None:
                mr_row = {
                    **base,
                    "score": mr["score"],
                    "meanrevScore": mr["score"],
                    "components": mr.get("components"),
                    "sleeve": "MEAN_REVERSION",
                    "gateReason": mr.get("gateReason"),
                }
                mr_bucket.append(mr_row)
                # Stash MR score on momentum row for UI transparency
                base["meanrevScore"] = mr["score"]

    _attach_percentile_ranks(long_scored)
    _attach_percentile_ranks(short_scored)
    _attach_percentile_ranks(long_mr)
    _attach_percentile_ranks(short_mr)

    long_scored.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    short_scored.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    long_mr.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    short_mr.sort(key=lambda x: float(x.get("score") or 0), reverse=True)

    # Sequential construction: long first, then short excludes long basket symbols
    # (avoids wiping MR pool via premature opposite-side top-N filter)
    long_basket = _construct_dual_sleeve(
        long_scored[:60], long_mr[:60], "LONG", LONG_CAPITAL, regime, mr_gate_open
    )
    long_syms = {p["symbol"] for p in long_basket}
    short_basket = _construct_dual_sleeve(
        short_scored[:60],
        short_mr[:60],
        "SHORT",
        SHORT_CAPITAL,
        regime,
        mr_gate_open,
        exclude_symbols=long_syms,
    )

    # High-probability adoption: 20 candidates → 5 BUY + 5 SELL
    adopt_long = _adopt_high_probability(
        long_basket, LOCK_SIZE, direction="LONG", capital=LONG_CAPITAL, regime=regime
    )
    adopt_short = _adopt_high_probability(
        short_basket, LOCK_SIZE, direction="SHORT", capital=SHORT_CAPITAL, regime=regime
    )

    return {
        "success": True,
        "updatedAt": _utc_now_iso(),
        "snapshotUpdatedAt": updated_at,
        "snapshotAgeSec": age_sec,
        "dataStale": stale,
        "regime": regime,
        "meanRevGate": {
            "open": mr_gate_open,
            "reason": mr_gate_reason,
            "vixMax": MR_VIX_MAX,
        },
        "capital": {
            "longCapital": LONG_CAPITAL,
            "shortCapital": SHORT_CAPITAL,
            "riskFraction": RISK_FRACTION,
            "basketSize": LOCK_SIZE,
            "candidatePoolSize": BASKET_SIZE,
            "lockSize": LOCK_SIZE,
            "momentumSlots": MOMENTUM_SLOTS,
            "meanRevSlots": MEANREV_SLOTS if mr_gate_open else 0,
            "riskScaleLong": round(_regime_risk_scale(regime, "LONG"), 3),
            "riskScaleShort": round(_regime_risk_scale(regime, "SHORT"), 3),
        },
        "funnel": {
            "universe": len(rows),
            "filterReject": filter_reject,
            "longScored": len(long_scored),
            "shortScored": len(short_scored),
            "longMeanRevScored": len(long_mr),
            "shortMeanRevScored": len(short_mr),
            "unratedComponents": unrated,
            "candidatePool": len(long_basket) + len(short_basket),
            "adopted": len(adopt_long) + len(adopt_short),
            "funnelNote": f"{BASKET_SIZE}+{BASKET_SIZE} candidates -> adopt top {LOCK_SIZE}+{LOCK_SIZE} by score",
        },
        "longCandidates": [
            {
                "symbol": c["symbol"],
                "score": c["score"],
                "scorePctRank": c.get("scorePctRank"),
                "sector": c["sector"],
                "ltp": c["ltp"],
                "atrPct": c["atrPct"],
                "inPlay": c.get("inPlay"),
                "gapPct": c.get("gapPct"),
                "intradayRet": c.get("intradayRet"),
            }
            for c in long_scored[:20]
        ],
        "shortCandidates": [
            {
                "symbol": c["symbol"],
                "score": c["score"],
                "scorePctRank": c.get("scorePctRank"),
                "sector": c["sector"],
                "ltp": c["ltp"],
                "atrPct": c["atrPct"],
                "inPlay": c.get("inPlay"),
                "gapPct": c.get("gapPct"),
                "intradayRet": c.get("intradayRet"),
            }
            for c in short_scored[:20]
        ],
        # Full 10+10 research pool (not yet locked)
        "proposedLong": long_basket,
        "proposedShort": short_basket,
        # High-probability 5+5 that commit will lock
        "adoptLong": adopt_long,
        "adoptShort": adopt_short,
        "weights": {
            "regime": W_REGIME,
            "relativeStrength": W_RS,
            "trend": W_TREND,
            "momentum": W_MOMENTUM,
            "vwap": W_VWAP,
            "volume": W_VOLUME,
            "breakout": W_BREAKOUT,
            "volatility": W_VOLATILITY,
            "sector": W_SECTOR,
            "liquidity": W_LIQUIDITY,
            "note": "starting params — not proven optimal",
        },
        "meanRevWeights": {
            "vwapFade": W_MR_VWAP,
            "rsiFade": W_MR_RSI,
            "gapFade": W_MR_GAP,
            "note": "starting params — not proven optimal",
        },
        "executionPolicy": "MANUAL_ONLY",
        "locked": False,
    }


def commit_session(force: bool = False) -> dict[str, Any]:
    """Lock high-probability 5 BUY + 5 SELL from the 10+10 candidate pool."""
    existing = load_session()
    if existing.get("locked") and not force:
        return {
            "success": False,
            "error": "SESSION BASKET LOCKED — symbols immutable. Pass force=true only to rebuild after explicit unlock.",
            "session": existing,
        }

    candidates = generate_candidates()
    pool_long = candidates.get("proposedLong") or []
    pool_short = candidates.get("proposedShort") or []
    long_rows = candidates.get("adoptLong") or []
    short_rows = candidates.get("adoptShort") or []
    if len(pool_long) < LOCK_SIZE or len(pool_short) < LOCK_SIZE:
        return {
            "success": False,
            "error": (
                f"Insufficient candidate pool for {LOCK_SIZE}+{LOCK_SIZE} adopt "
                f"(got {len(pool_long)}L / {len(pool_short)}S of {BASKET_SIZE}+{BASKET_SIZE}). "
                f"Refresh market snapshot."
            ),
            "candidates": candidates,
        }
    if len(long_rows) < LOCK_SIZE or len(short_rows) < LOCK_SIZE:
        regime = candidates.get("regime") or {}
        long_rows = _adopt_high_probability(
            pool_long, LOCK_SIZE, direction="LONG", capital=LONG_CAPITAL, regime=regime
        )
        short_rows = _adopt_high_probability(
            pool_short, LOCK_SIZE, direction="SHORT", capital=SHORT_CAPITAL, regime=regime
        )
    if len(long_rows) < LOCK_SIZE or len(short_rows) < LOCK_SIZE:
        return {
            "success": False,
            "error": (
                f"Could not adopt {LOCK_SIZE}+{LOCK_SIZE} high-probability picks "
                f"(got {len(long_rows)}L / {len(short_rows)}S)."
            ),
            "candidates": candidates,
        }

    session_date = _ist_now().strftime("%Y-%m-%d")
    committed_at = _utc_now_iso()
    events = [
        {
            "type": "SESSION_COMMIT",
            "at": committed_at,
            "long": [r["symbol"] for r in long_rows],
            "short": [r["symbol"] for r in short_rows],
            "candidatePoolLong": [r["symbol"] for r in pool_long],
            "candidatePoolShort": [r["symbol"] for r in pool_short],
            "funnel": f"{len(pool_long)}+{len(pool_short)} → adopt {len(long_rows)}+{len(short_rows)}",
            "sleeves": {
                "momentumSlots": MOMENTUM_SLOTS,
                "meanRevSlots": (candidates.get("capital") or {}).get("meanRevSlots"),
                "lockSize": LOCK_SIZE,
                "candidatePoolSize": BASKET_SIZE,
            },
            "executionPolicy": "MANUAL_ONLY",
        }
    ]

    capital = dict(candidates.get("capital") or {})
    capital["basketSize"] = LOCK_SIZE
    capital["candidatePoolSize"] = BASKET_SIZE
    capital["lockSize"] = LOCK_SIZE

    session = {
        "success": True,
        "locked": True,
        "sessionDate": session_date,
        "committedAt": committed_at,
        "updatedAt": committed_at,
        "snapshotUpdatedAt": candidates.get("snapshotUpdatedAt"),
        "dataStale": candidates.get("dataStale"),
        "regime": candidates.get("regime"),
        "meanRevGate": candidates.get("meanRevGate"),
        "capital": capital,
        "executionPolicy": "MANUAL_ONLY",
        "long": long_rows,
        "short": short_rows,
        "candidatePoolLong": pool_long,
        "candidatePoolShort": pool_short,
        "events": events,
        "funnel": candidates.get("funnel"),
        "weights": candidates.get("weights"),
        "meanRevWeights": candidates.get("meanRevWeights"),
    }
    save_session(session)

    try:
        from .swing_session import ensure_swing_session_locked
        ensure_swing_session_locked()
    except Exception as exc:
        log.warning("Swing session auto-lock failed: %s", exc)

    plan = {
        "long": [
            {
                "symbol": r["symbol"],
                "direction": "LONG",
                "entryDate": session_date,
                "approxQty": r.get("approxQty"),
                "deployedCapital": r.get("deployedCapital"),
                "entryPrice": r.get("entryPrice"),
                "stopLoss": r.get("stopLoss"),
                "target1": r.get("target1"),
                "target2": r.get("target2"),
                "scanLtp": r.get("ltp"),
                "currentPrice": r.get("ltp"),
                "score": r.get("score"),
                "sector": r.get("sector"),
                "rewardRisk": r.get("rewardRisk"),
                "status": "RUNNING",
                "sessionLocked": True,
                "adopted": True,
            }
            for r in long_rows
        ],
        "short": [
            {
                "symbol": r["symbol"],
                "direction": "SHORT",
                "entryDate": session_date,
                "approxQty": r.get("approxQty"),
                "deployedCapital": r.get("deployedCapital"),
                "entryPrice": r.get("entryPrice"),
                "stopLoss": r.get("stopLoss"),
                "target1": r.get("target1"),
                "target2": r.get("target2"),
                "scanLtp": r.get("ltp"),
                "currentPrice": r.get("ltp"),
                "score": r.get("score"),
                "sector": r.get("sector"),
                "rewardRisk": r.get("rewardRisk"),
                "status": "RUNNING",
                "sessionLocked": True,
                "adopted": True,
            }
            for r in short_rows
        ],
        "updatedAt": committed_at,
        "sessionDate": session_date,
        "locked": True,
        "executionPolicy": "MANUAL_ONLY",
        "capital": capital,
        "regime": candidates.get("regime"),
        "source": "intraday_session_engine",
        "funnel": f"{BASKET_SIZE}+{BASKET_SIZE} candidates → {LOCK_SIZE}+{LOCK_SIZE} locked",
    }
    _atomic_write(_FIXED_PLAN_FILE, plan)
    session["fixedPlanSynced"] = True
    return session

def _enrich_position(pos: dict[str, Any], quotes: dict[str, Any], live_row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Update LTP/PnL/distances; never mutate symbol or CLOSED→open."""
    out = dict(pos)
    if out.get("closed") or str(out.get("status") or "").upper() == "CLOSED":
        out["status"] = "CLOSED"
        out["closed"] = True
        return out

    symbol = str(out.get("symbol") or "").upper()
    ltp = None
    ltp_source = "none"
    if live_row and live_row.get("ltp") is not None:
        ltp = _safe_float(live_row.get("ltp"))
        ltp_source = str(live_row.get("ltpSource") or "live")
    if ltp is None and symbol in quotes:
        q = quotes[symbol]
        ltp = _safe_float(q.get("ltpRaw") or q.get("ltp"))
        if ltp is not None:
            ltp_source = "snapshot"
    if ltp is None:
        ltp = _safe_float(out.get("ltp") or out.get("currentPrice") or out.get("entryPrice"))
        ltp_source = "cached" if ltp is not None else "none"

    entry = _safe_float(out.get("entryPrice"))
    sl = _safe_float(out.get("stopLoss"))
    t1 = _safe_float(out.get("target1"))
    t2 = _safe_float(out.get("target2"))
    qty = int(out.get("approxQty") or 0)
    direction = str(out.get("direction") or "LONG").upper()

    out["ltp"] = round(ltp, 2) if ltp is not None else None
    out["ltpSource"] = ltp_source
    live_stale = bool(live_row.get("dataStale")) if live_row else False
    out["dataStale"] = live_stale or ltp_source in ("cached", "none")

    if ltp is not None and entry is not None and entry > 0:
        if direction == "LONG":
            pnl = (ltp - entry) * qty
            pnl_pct = ((ltp - entry) / entry) * 100
        else:
            pnl = (entry - ltp) * qty
            pnl_pct = ((entry - ltp) / entry) * 100
        out["unrealizedPnl"] = round(pnl, 2)
        out["pnlPct"] = round(pnl_pct, 2)
        out["positionValue"] = round(ltp * qty, 2)
    else:
        out["unrealizedPnl"] = None
        out["pnlPct"] = None
        out["positionValue"] = None

    def _dist_pct(level: float | None) -> float | None:
        if ltp is None or level is None or ltp == 0:
            return None
        return round(abs(level - ltp) / ltp * 100, 2)

    out["distToSlPct"] = _dist_pct(sl)
    out["distToT1Pct"] = _dist_pct(t1)
    out["distToT2Pct"] = _dist_pct(t2)

    status = "RUNNING"
    if out.get("dataStale"):
        status = "DATA STALE"
    if live_row and isinstance(live_row.get("outcome"), dict):
        hit = live_row["outcome"].get("hitLevel")
        label = str(live_row["outcome"].get("label") or "")
        if hit == "sl" or "STOP" in label.upper():
            status = "STOP LOSS HIT"
            out["closed"] = True
        elif hit == "t2":
            status = "TARGET 2 HIT"
        elif hit == "t1":
            status = "TARGET 1 HIT"
    # Approaching flags (attention strip) — factual distance only
    if status == "RUNNING" and out.get("distToSlPct") is not None and out["distToSlPct"] <= 0.4:
        status = "SL APPROACHING"
    elif status == "RUNNING" and out.get("distToT1Pct") is not None and out["distToT1Pct"] <= 0.4:
        status = "TARGET APPROACHING"

    if out.get("closed"):
        status = "CLOSED"
    out["status"] = status
    return out


def get_session(include_live: bool = True) -> dict[str, Any]:
    session = load_session()
    snap = load_market_snapshot()
    quotes = snap.get("stockQuotes") or {}
    regime = session.get("regime") or detect_regime(snap)
    capital = session.get("capital") or {
        "longCapital": LONG_CAPITAL,
        "shortCapital": SHORT_CAPITAL,
        "riskFraction": RISK_FRACTION,
        "basketSize": BASKET_SIZE,
    }

    live_map: dict[str, dict[str, Any]] = {}
    live_meta: dict[str, Any] = {}
    if include_live and session.get("locked"):
        try:
            from .trade_outcome import get_live_prices_for_plan
            live = get_live_prices_for_plan()
            live_meta = {
                "updatedAt": live.get("updatedAt"),
                "snapshotUpdatedAt": live.get("snapshotUpdatedAt"),
                "marketOpen": live.get("marketOpen"),
                "sessionClosed": live.get("sessionClosed"),
                "dataStale": live.get("dataStale"),
                "ltpSourceMix": live.get("ltpSourceMix"),
                "priceSourcesNote": live.get("priceSourcesNote"),
                "newAlerts": live.get("newAlerts") or [],
            }
            for side in ("long", "short"):
                for row in live.get(side) or []:
                    sym = str(row.get("symbol") or "").upper()
                    if sym:
                        live_map[sym] = row
        except Exception as exc:
            log.warning("live enrich failed: %s", exc)
            live_meta = {"error": str(exc)}

    long_rows = [_enrich_position(p, quotes, live_map.get(str(p.get("symbol") or "").upper())) for p in (session.get("long") or [])]
    short_rows = [_enrich_position(p, quotes, live_map.get(str(p.get("symbol") or "").upper())) for p in (session.get("short") or [])]

    # Preserve CLOSED forever in persisted session
    if session.get("locked"):
        changed = False
        for side_key, rows in (("long", long_rows), ("short", short_rows)):
            orig = session.get(side_key) or []
            for i, row in enumerate(rows):
                if row.get("closed") and i < len(orig) and not orig[i].get("closed"):
                    orig[i] = {**orig[i], "closed": True, "status": "CLOSED"}
                    changed = True
                    events = list(session.get("events") or [])
                    events.append({
                        "type": "POSITION_CLOSED",
                        "at": _utc_now_iso(),
                        "symbol": row.get("symbol"),
                        "direction": row.get("direction"),
                    })
                    session["events"] = events[-200:]
        if changed:
            session["long"] = [
                {**o, "closed": True, "status": "CLOSED"} if (i < len(long_rows) and long_rows[i].get("closed")) else o
                for i, o in enumerate(session.get("long") or [])
            ]
            session["short"] = [
                {**o, "closed": True, "status": "CLOSED"} if (i < len(short_rows) and short_rows[i].get("closed")) else o
                for i, o in enumerate(session.get("short") or [])
            ]
            session["updatedAt"] = _utc_now_iso()
            save_session(session)

    def _sum_pnl(rows: list[dict[str, Any]]) -> float | None:
        vals = [r.get("unrealizedPnl") for r in rows if r.get("unrealizedPnl") is not None]
        if not vals:
            return None
        return round(sum(float(v) for v in vals), 2)

    long_exposure = round(sum(float(r.get("positionValue") or r.get("deployedCapital") or 0) for r in long_rows), 2)
    short_exposure = round(sum(float(r.get("positionValue") or r.get("deployedCapital") or 0) for r in short_rows), 2)
    u_pnl_l = _sum_pnl(long_rows)
    u_pnl_s = _sum_pnl(short_rows)
    unrealized = None if u_pnl_l is None and u_pnl_s is None else round((u_pnl_l or 0) + (u_pnl_s or 0), 2)

    attention: list[dict[str, Any]] = []
    for r in long_rows + short_rows:
        st = str(r.get("status") or "")
        if st in ("SL APPROACHING", "TARGET APPROACHING", "DATA STALE", "STOP LOSS HIT", "TARGET 1 HIT", "TARGET 2 HIT"):
            attention.append({
                "symbol": r.get("symbol"),
                "direction": r.get("direction"),
                "status": st,
                "ltp": r.get("ltp"),
                "distToSlPct": r.get("distToSlPct"),
                "distToT1Pct": r.get("distToT1Pct"),
            })

    macros = _macro_lookup(snap)
    feed_status = "STALE" if (live_meta.get("dataStale") or session.get("dataStale")) else ("OK" if session.get("locked") else "IDLE")

    # Always emit session clock honesty — even when unlocked / live enrich skipped
    if "marketOpen" not in live_meta or live_meta.get("marketOpen") is None:
        try:
            from .trade_outcome import _is_market_open
            live_meta["marketOpen"] = _is_market_open()
        except Exception:
            live_meta["marketOpen"] = None
    if "sessionClosed" not in live_meta or live_meta.get("sessionClosed") is None:
        try:
            from .trade_outcome import _is_after_market_close
            live_meta["sessionClosed"] = _is_after_market_close()
        except Exception:
            live_meta["sessionClosed"] = None

    return {
        "success": True,
        "locked": bool(session.get("locked")),
        "sessionDate": session.get("sessionDate"),
        "committedAt": session.get("committedAt"),
        "updatedAt": live_meta.get("updatedAt") or session.get("updatedAt") or _utc_now_iso(),
        "snapshotUpdatedAt": live_meta.get("snapshotUpdatedAt") or session.get("snapshotUpdatedAt") or snap.get("updatedAt"),
        "marketOpen": live_meta.get("marketOpen"),
        "sessionClosed": live_meta.get("sessionClosed"),
        "dataStale": live_meta.get("dataStale") if "dataStale" in live_meta else session.get("dataStale"),
        "ltpSourceMix": live_meta.get("ltpSourceMix"),
        "priceSourcesNote": live_meta.get("priceSourcesNote"),
        "feedStatus": feed_status,
        "executionPolicy": "MANUAL_ONLY",
        "regime": regime,
        "capital": capital,
        "macros": {
            "nifty": (macros.get("NIFTY 50") or {}).get("val"),
            "niftyDelta": (macros.get("NIFTY 50") or {}).get("delta"),
            "bankNifty": (macros.get("NIFTY BANK") or {}).get("val"),
            "bankNiftyDelta": (macros.get("NIFTY BANK") or {}).get("delta"),
            "indiaVix": (macros.get("INDIA VIX") or {}).get("val"),
            "indiaVixDelta": (macros.get("INDIA VIX") or {}).get("delta"),
        },
        "portfolio": {
            "longCapital": capital.get("longCapital", LONG_CAPITAL),
            "shortCapital": capital.get("shortCapital", SHORT_CAPITAL),
            "longExposure": long_exposure,
            "shortExposure": short_exposure,
            "grossExposure": round(long_exposure + short_exposure, 2),
            "netExposure": round(long_exposure - short_exposure, 2),
            "unrealizedPnl": unrealized,
            "realizedPnl": None,  # not tracked without broker fills
        },
        "attention": attention,
        "long": long_rows,
        "short": short_rows,
        "events": session.get("events") or [],
        "newAlerts": live_meta.get("newAlerts") or [],
        "funnel": session.get("funnel"),
    }
