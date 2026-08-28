"""Intraday session engine — Asset Metrics command center.

Desk automation may auto-commit after morning pre-work. Broker orders are never
placed by this module (executionPolicy remains advisory / manual-broker).

Funnel: Nifty 500 → regime → multi-factor score → entry_quality_gate →
  10 LONG + 10 SHORT candidate pool (20) →
  adopt highest-probability QUALIFIED 5 BUY + 5 SELL (10) → immutable JSON lock.

No broker order placement. Missing inputs → UNRATED / STALE_DATA / NO_EDGE, never invented.
"""
from __future__ import annotations

import json
import copy
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .exit_plan import (
    apply_exit_policy_to_rows,
    attach_exit_plan,
    cap_stop_risk,
    overwrite_rows_with_current_policy,
    profit_guard_active,
    refresh_exit_policy,
)
from .desk_clock import (
    basket_lock_allowed,
    basket_lock_block_message,
    can_add_replacement,
    ist_now,
    lock_window_config,
    rotation_window_allowed,
    rotation_window_config,
)
from .desk_book_symbols import swing_locked_symbols
from .cross_book_resolution import reconcile_cross_book, swing_prefers_over_intraday
from .sector_rotation import sector_signal

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_BASE = Path(__file__).resolve().parent
_CLOSE_FREEZE_LOCK = threading.Lock()
_SESSION_RESPONSE_LOCK = threading.Lock()
_SESSION_RESPONSE_CACHE: dict[str, Any] | None = None
_SESSION_RESPONSE_CACHE_AT = 0.0
_SESSION_RESPONSE_REFRESHING = False
_SESSION_RESPONSE_GEN = 0
_SESSION_ROTATION_LOCK = threading.Lock()
_SESSION_ROTATION_ATTEMPT_AT = 0.0
_SESSION_ROTATION_RETRY_SEC = float(os.environ.get("INTRADAY_ROTATION_RETRY_SEC", "30"))
_SESSION_RESPONSE_OPEN_TTL = float(os.environ.get("INTRADAY_RESPONSE_OPEN_TTL", "4"))
_SESSION_RESPONSE_CLOSED_TTL = float(os.environ.get("INTRADAY_RESPONSE_CLOSED_TTL", "20"))
# Live replacement hunt: rescore Nifty 500 QUALIFIED names; do not reuse 10:18 lock pools.
_HUNT_TTL_SEC = float(os.environ.get("INTRADAY_HUNT_TTL", "30"))
_SNAP_REFRESH_MIN_GAP_SEC = float(os.environ.get("INTRADAY_HUNT_REFRESH_GAP_SEC", "120"))
_HUNT_POOL_CACHE: dict[str, Any] = {"key": "", "at": 0.0, "long": [], "short": []}
_SNAP_REFRESH_LAST = 0.0

def _market_snapshot_file() -> Path:
    from .market_snapshot_store import readable_market_snapshot_path

    return readable_market_snapshot_path()
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
INTRADAY_CAPITAL = float(os.environ.get("INTRADAY_CAPITAL", str(LONG_CAPITAL + SHORT_CAPITAL)))
RISK_FRACTION = float(os.environ.get("INTRADAY_RISK_FRACTION", "0.01"))  # of sleeve per name
ATR_STOP_MULT = float(os.environ.get("INTRADAY_ATR_STOP_MULT", "1.2"))
T1_R_LONG = float(os.environ.get("INTRADAY_T1_R_LONG", "1.5"))
T2_R_LONG = float(os.environ.get("INTRADAY_T2_R_LONG", "3.0"))
T1_R_SHORT = float(os.environ.get("INTRADAY_T1_R_SHORT", "1.5"))
T2_R_SHORT = float(os.environ.get("INTRADAY_T2_R_SHORT", "2.5"))
MAX_PER_SECTOR = int(os.environ.get("INTRADAY_MAX_PER_SECTOR", "2"))
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
LOCK_SIZE = int(os.environ.get("MAX_INTRADAY_POSITIONS", os.environ.get("INTRADAY_LOCK_SIZE", "5")))
MAX_LONG_POSITIONS = int(os.environ.get("MAX_LONG_POSITIONS", "3"))
MAX_SHORT_POSITIONS = int(os.environ.get("MAX_SHORT_POSITIONS", "3"))
MAX_PORTFOLIO_RISK = float(os.environ.get("INTRADAY_MAX_PORTFOLIO_RISK", "0.05"))
MAX_SINGLE_TRADE_RISK = float(os.environ.get("INTRADAY_MAX_SINGLE_TRADE_RISK", "0.01"))

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

# Entry quality gate / exhaustion filter (conservative starting params — not proven optimal)
EXHAUSTION_PCT = float(os.environ.get("INTRADAY_EXHAUSTION_PCT", "3.5"))
EXHAUSTION_HARD_PCT = float(os.environ.get("INTRADAY_EXHAUSTION_HARD_PCT", "4.0"))
VWAP_CHASE_PCT = float(os.environ.get("INTRADAY_VWAP_CHASE_PCT", "1.25"))
ORB_CHASE_PCT = float(os.environ.get("INTRADAY_ORB_CHASE_PCT", "1.0"))
REGIME_BLOCK_NIFTY_PCT = float(os.environ.get("INTRADAY_REGIME_BLOCK_NIFTY_PCT", "0.6"))
# Soft headwind (haircut) at ±0.6%; hard reject only at extreme tape (±1.5% default).
# Hard-blocking shorts on every modest up-day previously froze the daily rotate.
REGIME_HARD_NIFTY_PCT = float(os.environ.get("INTRADAY_REGIME_HARD_NIFTY_PCT", "1.5"))
REGIME_HEADWIND_HAIRCUT = float(os.environ.get("INTRADAY_REGIME_HAIRCUT", "0.70"))
ENTRY_MIN_EXPECTED_R = float(os.environ.get("INTRADAY_ENTRY_MIN_EXPECTED_R", "1.20"))
PRIORITY_EXPECTED_R = float(os.environ.get("INTRADAY_PRIORITY_EXPECTED_R", "1.50"))
HIGH_CONVICTION_R = float(os.environ.get("INTRADAY_HIGH_CONVICTION_R", "2.00"))
ENTRY_EXCEPTIONAL_SCORE = float(os.environ.get("INTRADAY_ENTRY_EXCEPTIONAL_SCORE", "72"))
ENTRY_WICK_NOISE_MAX = float(os.environ.get("INTRADAY_ENTRY_WICK_NOISE_MAX", "0.70"))
# OI preference (F&O only — when oi/prev_oi facts exist; never invent OI).
# Soft by default: aligned ranks first + R haircut if misaligned. Hard reject only if OI_REQUIRE_FNO=1.
OI_LONG_OK = frozenset({"LONG_BUILDUP", "SHORT_COVERING"})
OI_SHORT_OK = frozenset({"SHORT_BUILDUP", "LONG_UNWINDING"})
OI_REQUIRE_FNO = os.environ.get("INTRADAY_OI_REQUIRE_FNO", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
OI_MISALIGN_HAIRCUT = float(os.environ.get("INTRADAY_OI_MISALIGN_HAIRCUT", "0.75"))
OI_ALIGN_BONUS = float(os.environ.get("INTRADAY_OI_ALIGN_BONUS", "1.05"))
# Entry states (facts-only gate outcomes — never invent fills)
ENTRY_QUALIFIED = "QUALIFIED"
ENTRY_WAIT_RETEST = "WAIT_RETEST"
ENTRY_EXHAUSTED = "EXHAUSTED"
ENTRY_NO_EDGE = "NO_EDGE"
ENTRY_STALE_DATA = "STALE_DATA"
ENTRY_REGIME_AGAINST = "REGIME_AGAINST"
_ENTRY_HARD_REJECT = frozenset(
    {ENTRY_EXHAUSTED, ENTRY_STALE_DATA, ENTRY_REGIME_AGAINST, ENTRY_NO_EDGE}
)

# Replacement planner — propose only until cutoff; prefer cash over weak names
REPLACEMENT_CUTOFF_HHMM = os.environ.get("INTRADAY_REPLACEMENT_CUTOFF", "1445")
REPLACEMENT_MIN_SCORE = float(os.environ.get("INTRADAY_REPLACEMENT_MIN_SCORE", "55"))
REPLACEMENT_MAX_PER_SIDE = int(os.environ.get("INTRADAY_REPLACEMENT_MAX_PER_SIDE", str(LOCK_SIZE)))
# A locked book may rotate, but it must never turn a five-name desk into a
# high-turnover scanner. This is a session-wide cap on *new* entries after
# the morning lock (normal replacements plus permitted re-entries). Its default
# is derived from the advertised total-entry ceiling so 5 initial + 15 later
# entries can reach, but never exceed, the 20-entry session policy.
MAX_DAILY_REPLACEMENTS = int(
    os.environ.get(
        "INTRADAY_MAX_DAILY_REPLACEMENTS",
        str(max(0, int(os.environ.get("INTRADAY_MAX_DAILY_POSITIONS", "20")) - LOCK_SIZE)),
    )
)
# Hard session ledger ceiling. This counts every executed entry, including the
# morning lock, ordinary replacements and same-symbol re-entries. It is not a
# concurrent-position limit; LOCK_SIZE remains the live-book risk limit.
MAX_DAILY_POSITIONS = int(os.environ.get("INTRADAY_MAX_DAILY_POSITIONS", "20"))

# Re-entry policy.  A completed target or a genuinely profitable trailing exit
# may receive one smaller, independently-qualified continuation attempt.  An
# initial stop is deliberately disabled by default: it is the path most likely
# to create revenge trading and should only be enabled after replay validation.
REENTRY_ENABLED = os.environ.get("INTRADAY_REENTRY_ENABLED", "1").strip().lower() in (
    "1", "true", "yes",
)
REENTRY_MAX_PER_SYMBOL = int(os.environ.get("INTRADAY_MAX_REENTRIES_PER_SYMBOL", "1"))
REENTRY_TARGET_COOLDOWN_MIN = int(os.environ.get("INTRADAY_REENTRY_TARGET_COOLDOWN_MIN", "20"))
REENTRY_TRAIL_COOLDOWN_MIN = int(os.environ.get("INTRADAY_REENTRY_TRAIL_COOLDOWN_MIN", "30"))
REENTRY_ALLOW_INITIAL_STOP = os.environ.get(
    "INTRADAY_ALLOW_INITIAL_STOP_REENTRY", "0"
).strip().lower() in ("1", "true", "yes")
REENTRY_INITIAL_STOP_COOLDOWN_MIN = int(
    os.environ.get("INTRADAY_REENTRY_INITIAL_STOP_COOLDOWN_MIN", "60")
)
REENTRY_MIN_SCORE = float(os.environ.get("INTRADAY_REENTRY_MIN_SCORE", "65"))
REENTRY_MIN_EXPECTED_R = float(
    os.environ.get("INTRADAY_REENTRY_MIN_EXPECTED_R", str(PRIORITY_EXPECTED_R))
)
REENTRY_INITIAL_STOP_MIN_SCORE = float(
    os.environ.get("INTRADAY_REENTRY_INITIAL_STOP_MIN_SCORE", str(ENTRY_EXCEPTIONAL_SCORE))
)
REENTRY_INITIAL_STOP_MIN_EXPECTED_R = float(
    os.environ.get("INTRADAY_REENTRY_INITIAL_STOP_MIN_EXPECTED_R", str(HIGH_CONVICTION_R))
)
REENTRY_MIN_TRAIL_MFE_R = float(
    os.environ.get("INTRADAY_REENTRY_MIN_TRAIL_MFE_R", "1.0")
)
REENTRY_BREAKOUT_BUFFER_BPS = float(
    os.environ.get("INTRADAY_REENTRY_BREAKOUT_BUFFER_BPS", "10")
)
REENTRY_PROFIT_RISK_SCALE = float(
    os.environ.get("INTRADAY_REENTRY_PROFIT_RISK_SCALE", "0.50")
)
REENTRY_INITIAL_STOP_RISK_SCALE = float(
    os.environ.get("INTRADAY_REENTRY_INITIAL_STOP_RISK_SCALE", "0.25")
)
# Portfolio risk stops (rotation) — prefer cash when hit
DAILY_LOSS_LIMIT_INR = float(os.environ.get("INTRADAY_DAILY_LOSS_LIMIT", "15000"))
MAX_CONCURRENT_NAMES = int(os.environ.get("INTRADAY_MAX_CONCURRENT", str(LOCK_SIZE)))

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
    """Write JSON without truncating the live file (Windows Docker safe)."""
    from .json_atomic import atomic_write_json

    atomic_write_json(path, payload)

def load_market_snapshot() -> dict[str, Any]:
    try:
        return json.loads(_market_snapshot_file().read_text(encoding="utf-8-sig"))
    except Exception as exc:
        log.warning("Failed to load market snapshot: %s", exc)
        return {}


def load_session() -> dict[str, Any]:
    """Read session JSON. GET-safe: no migrate, no disk write."""
    try:
        from .json_atomic import load_json_with_fallback

        data = load_json_with_fallback(_SESSION_FILE)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _ensure_current_exit_policy(session: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    """Apply current SCALE_TRAIL notes/ratchet in memory. Path replay + disk write only on persist."""
    work = dict(session)
    changed = False
    quotes: dict[str, Any] = {}
    if persist:
        snap = load_market_snapshot()
        quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    for key in ("long", "short", "candidatePoolLong", "candidatePoolShort"):
        rows = work.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        updated, row_changed = apply_exit_policy_to_rows(rows)
        path_changed = False
        if persist:
            open_idx = [
                i for i, r in enumerate(updated)
                if isinstance(r, dict) and _position_is_open(r)
            ]
            if open_idx:
                subset = [updated[i] for i in open_idx]
                subset, path_changed = overwrite_rows_with_current_policy(
                    subset, quotes=quotes, after_close=False, force=False
                )
                for i, row in zip(open_idx, subset):
                    updated[i] = row
        if row_changed or path_changed:
            work[key] = updated
            changed = True
    if not changed:
        return session
    if persist:
        try:
            save_session(work)
            sync_fixed_plan_from_session(work)
        except Exception:
            log.exception("intraday exit-policy migrate persist failed")
    return work


def _invalidate_session_response_cache() -> None:
    """Drop the coalesced GET snapshot and retire in-flight live refresh writes."""
    global _SESSION_RESPONSE_CACHE, _SESSION_RESPONSE_CACHE_AT, _SESSION_RESPONSE_GEN
    with _SESSION_RESPONSE_LOCK:
        _SESSION_RESPONSE_GEN += 1
        _SESSION_RESPONSE_CACHE = None
        _SESSION_RESPONSE_CACHE_AT = 0.0


def save_session(payload: dict[str, Any]) -> None:
    _atomic_write(_SESSION_FILE, payload)
    # Explicit mutations invalidate the response snapshot. The computing caller
    # will republish a fresh value after its state transition finishes.
    _invalidate_session_response_cache()
    try:
        from .trade_outcome import invalidate_live_book_cache

        invalidate_live_book_cache()
    except Exception:
        pass


def _persist_if_close_transition(session: dict[str, Any], long_rows: list[dict[str, Any]], short_rows: list[dict[str, Any]]) -> None:
    """Persist any live close / exit-state transition immediately to disk.

    Callers must only invoke this on durable scheduler paths (`persist=True`).
    Read-only API GET paths must not write session JSON.
    """
    if not session.get("locked"):
        return
    for side_key, rows in (("long", long_rows), ("short", short_rows)):
        orig_rows = session.get(side_key) or []
        for idx, row in enumerate(rows):
            if idx >= len(orig_rows):
                if row.get("closed") or str(row.get("status") or "").upper() not in ("", "RUNNING"):
                    session["updatedAt"] = _utc_now_iso()
                    save_session(session)
                    return
            else:
                prev = orig_rows[idx]
                if (
                    bool(prev.get("closed")) != bool(row.get("closed"))
                    or str(prev.get("status") or "") != str(row.get("status") or "")
                    or prev.get("slotFreed") != row.get("slotFreed")
                    or prev.get("slotStatus") != row.get("slotStatus")
                ):
                    session["updatedAt"] = _utc_now_iso()
                    save_session(session)
                    return


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


def _parse_delta_pct(delta: Any, state: Any = None) -> float | None:
    """Parse % change from ``+0.16%``, ``27.70 (-0.11%)``, or a bare number.

    Prefer the percentage inside parentheses so absolute pts are never treated as %.
    """
    if delta is None:
        return None
    if isinstance(delta, (int, float)):
        return float(delta)
    text = str(delta).replace(",", "").strip()
    if not text:
        return None
    paren = re.search(r"\(([+-]?\d+(?:\.\d+)?)%\)", text)
    if paren:
        pct = float(paren.group(1))
    else:
        bare_pct = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
        if bare_pct:
            pct = float(bare_pct.group(1))
        elif re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
            pct = float(text)
        else:
            return None
    st = str(state or "").upper()
    # Legacy unsigned ``pts (0.11%)`` — apply macro state sign when present
    if st == "NEGATIVE" and pct > 0:
        pct = -pct
    elif st == "POSITIVE" and pct < 0:
        pct = abs(pct)
    return pct


def detect_regime(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Regime from NIFTY / BANKNIFTY / India VIX macros → RISK_ON|NEUTRAL|RISK_OFF.

    No invented levels. Missing macros → UNRATED (gates neutral 0.5).
    """
    macros = _macro_lookup(snapshot)
    nifty = macros.get("NIFTY 50") or macros.get("NIFTY50")
    bank = macros.get("NIFTY BANK") or macros.get("BANK NIFTY")
    vix = macros.get("INDIA VIX") or macros.get("INDIAVIX")

    nifty_chg = _parse_delta_pct((nifty or {}).get("delta"), (nifty or {}).get("state"))
    bank_chg = _parse_delta_pct((bank or {}).get("delta"), (bank or {}).get("state"))
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


def _classify_oi_setup(
    ltp: float,
    prev_close: float,
    current_oi: float,
    prev_oi: float,
) -> str:
    """Price + OI facts → setup label (same rules as Angel feed; never invent OI)."""
    price_up = ltp > prev_close
    if price_up and current_oi > prev_oi:
        return "LONG_BUILDUP"
    if price_up and current_oi < prev_oi:
        return "SHORT_COVERING"
    if (not price_up) and current_oi > prev_oi:
        return "SHORT_BUILDUP"
    if (not price_up) and current_oi < prev_oi:
        return "LONG_UNWINDING"
    return "NEUTRAL"


def _resolve_oi_facts(
    work: dict[str, Any],
    intra: dict[str, Any],
    *,
    quotes: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
) -> tuple[float | None, float | None, float | None, str | None]:
    """Return (oi, prev_oi, prev_close, oi_setup) from facts only.

    F&O detectable when oi or prev_oi > 0. Cash / missing → oi_setup None + no invent.
    """
    live = live if isinstance(live, dict) else {}
    quotes = quotes if isinstance(quotes, dict) else {}
    sym = str(work.get("symbol") or work.get("ticker") or "").upper().strip()
    q = quotes.get(sym) if sym and isinstance(quotes.get(sym), dict) else {}

    oi = _safe_float(
        live.get("oi")
        or work.get("oi")
        or intra.get("oi")
        or q.get("oi")
        or q.get("opnInterest")
    )
    prev_oi = _safe_float(
        live.get("prev_oi")
        or live.get("previousOI")
        or work.get("prev_oi")
        or work.get("previousOI")
        or intra.get("prev_oi")
        or q.get("prev_oi")
        or q.get("previousOI")
    )
    prev_close = _safe_float(
        live.get("close")
        or live.get("prevClose")
        or work.get("close")
        or work.get("prevClose")
        or q.get("close")
        or q.get("prevClose")
    )
    labeled = (
        live.get("oiSetup")
        or live.get("oi_setup")
        or work.get("oiSetup")
        or work.get("oi_setup")
        or intra.get("oi_setup")
        or q.get("oi_setup")
    )
    setup = str(labeled).upper().strip() if labeled else None
    if setup in ("", "NONE", "NULL"):
        setup = None

    has_oi = (oi is not None and oi > 0) or (prev_oi is not None and prev_oi > 0)
    if not has_oi:
        return oi, prev_oi, prev_close, None

    if setup in OI_LONG_OK | OI_SHORT_OK | {"NEUTRAL"}:
        return oi, prev_oi, prev_close, setup

    # Recompute from facts when label missing / unknown — still never invent OI numbers.
    ltp = _safe_float(
        live.get("ltp")
        or work.get("ltpRaw")
        or work.get("ltp")
        or work.get("lastPrice")
        or q.get("ltp")
    )
    if ltp is None or prev_close is None or prev_close <= 0:
        return oi, prev_oi, prev_close, "NEUTRAL"
    cur = float(oi or 0.0)
    prv = float(prev_oi or 0.0)
    return oi, prev_oi, prev_close, _classify_oi_setup(float(ltp), float(prev_close), cur, prv)


def _gate_payload(
    entry_state: str,
    *,
    exclude_reason: str | None,
    quality_r: float | None,
    flags: list[str],
    ltp_source: str | None = None,
    day_move: float | None = None,
    oi_setup: str | None = None,
    oi_aligned: bool | None = None,
) -> dict[str, Any]:
    """Normalize gate response (entryState API + replacement `state` alias)."""
    return {
        "entryState": entry_state,
        "excludeReason": exclude_reason,
        "qualityAdjustedExpectedR": quality_r,
        "flags": flags,
        # Compatibility aliases for propose_replacements
        "state": entry_state,
        "reasons": [exclude_reason] if exclude_reason else (flags or ["passed"]),
        "ltpSource": ltp_source,
        "dayMovePct": None if day_move is None else round(day_move, 3),
        "oiSetup": oi_setup,
        "oiAligned": oi_aligned,
    }


def _day_move_pct(
    cand: dict[str, Any],
    quotes: dict[str, Any] | None = None,
    live_row: dict[str, Any] | None = None,
) -> float | None:
    """Best-available day/intraday move % from live → cand → quotes (never invent)."""
    live = live_row if isinstance(live_row, dict) else {}
    for src in (live, cand):
        if not isinstance(src, dict):
            continue
        for key in ("intradayRet", "dayChangePct", "pctChange", "pChange", "changePct"):
            v = _safe_float(src.get(key))
            if v is not None:
                return v
        # Derive from open/close/ltp when present
        _, intra_ret, day_chg = _gap_and_intraday(src)
        if intra_ret is not None:
            return intra_ret
        if day_chg is not None:
            return day_chg
    quotes = quotes if isinstance(quotes, dict) else {}
    sym = str(cand.get("symbol") or cand.get("ticker") or "").upper().strip()
    q = quotes.get(sym) if sym else None
    if isinstance(q, dict):
        for key in ("intradayRet", "dayChangePct", "changePct", "pChange"):
            v = _safe_float(q.get(key))
            if v is not None:
                return v
        _, intra_ret, day_chg = _gap_and_intraday(q)
        if intra_ret is not None:
            return intra_ret
        if day_chg is not None:
            return day_chg
    return None


def entry_quality_gate(
    row: dict[str, Any],
    direction: str,
    regime_ctx: dict[str, Any] | None = None,
    *,
    quotes: dict[str, Any] | None = None,
    live_row: dict[str, Any] | None = None,
    regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Low-error entry gate: exhaustion, chase, regime, OI (F&O), data honesty.

    Uses only existing quote/snapshot/live fields (never invents LTP/VWAP/ORB/OI).

        gate = entry_quality_gate(row, "LONG", regime)
        # or replacement path:
        gate = entry_quality_gate(cand, "LONG", quotes=q, live_row=live, regime=regime)
        if gate["entryState"] != ENTRY_QUALIFIED:
            ...

    Returns entryState, excludeReason (or None), qualityAdjustedExpectedR, flags, oiSetup.
    Also exposes state/reasons/ltpSource/dayMovePct for replacement callers.
    """
    regime_use = regime if isinstance(regime, dict) else (
        regime_ctx if isinstance(regime_ctx, dict) else {}
    )
    is_long = str(direction or "").upper() == "LONG"
    flags: list[str] = []
    live = live_row if isinstance(live_row, dict) else {}
    quotes = quotes if isinstance(quotes, dict) else {}
    oi_setup: str | None = None

    # Overlay live marks onto a working view (facts only — no invented LTP).
    work = dict(row) if isinstance(row, dict) else {}
    if live.get("ltp") is not None:
        work["ltp"] = live.get("ltp")
    if live.get("ltpSource") is not None:
        work["ltpSource"] = live.get("ltpSource")
    if live.get("vwap") is not None:
        work["vwap"] = live.get("vwap")
    if live.get("oi") is not None:
        work["oi"] = live.get("oi")
    if live.get("prev_oi") is not None or live.get("previousOI") is not None:
        work["prev_oi"] = live.get("prev_oi") if live.get("prev_oi") is not None else live.get("previousOI")

    intra = work.get("intraday") if isinstance(work.get("intraday"), dict) else {}
    ltp = _safe_float(
        work.get("ltpRaw") or work.get("ltp") or work.get("lastPrice") or work.get("entryPrice")
        or work.get("scanLtp")
    )
    vwap = _safe_float(work.get("vwap") if work.get("vwap") is not None else intra.get("vwap"))
    atr = _safe_float(work.get("atrPct") if work.get("atrPct") is not None else intra.get("atr_pct"))
    orb_high = _safe_float(
        work.get("orbHigh") if work.get("orbHigh") is not None else intra.get("orb_high")
    )
    orb_low = _safe_float(
        work.get("orbLow") if work.get("orbLow") is not None else intra.get("orb_low")
    )
    turnover = _safe_float(
        work.get("turnoverCr") if work.get("turnoverCr") is not None else intra.get("turnover_cr")
    )
    wick = _safe_float(intra.get("wick_noise_ratio") or work.get("wickNoiseRatio"))
    score = _safe_float(work.get("score") or work.get("meanrevScore"))
    in_play = bool(work.get("inPlay")) if "inPlay" in work else False
    if not in_play and intra:
        rvol_t, _ = _rvol_time(intra)
        gap_pct_tmp, _, _ = _gap_and_intraday(work)
        if rvol_t is not None and rvol_t >= INPLAY_RVOL:
            in_play = True
        elif (
            gap_pct_tmp is not None
            and atr is not None
            and atr > 0
            and abs(gap_pct_tmp) >= INPLAY_GAP_ATR_MULT * atr
        ):
            in_play = True

    gap_pct, intraday_ret, day_chg = _gap_and_intraday(work)
    if day_chg is None:
        day_chg = _safe_float(work.get("dayChangePct"))
    if intraday_ret is None:
        intraday_ret = _safe_float(work.get("intradayRet"))
    if gap_pct is None:
        gap_pct = _safe_float(work.get("gapPct"))
    # Prefer live/quote day move when provided by replacement path.
    quote_move = None
    if quotes or live:
        quote_move = _day_move_pct(work, quotes, live)
    move_pct = quote_move if quote_move is not None else (
        intraday_ret if intraday_ret is not None else day_chg
    )
    day_move = move_pct

    ltp_source = str(work.get("ltpSource") or work.get("ltp_source") or "").strip().lower()
    if ltp is None:
        return _gate_payload(
            ENTRY_STALE_DATA,
            exclude_reason="missing LTP",
            quality_r=None,
            flags=["STALE_DATA", "MISSING_LTP"],
            ltp_source=ltp_source or "none",
            day_move=day_move,
        )
    if ltp_source in ("cached", "none"):
        return _gate_payload(
            ENTRY_STALE_DATA,
            exclude_reason=f"ltpSource={ltp_source}",
            quality_r=None,
            flags=["STALE_DATA", f"SOURCE_{ltp_source.upper()}"],
            ltp_source=ltp_source,
            day_move=day_move,
        )

    nifty_chg = _safe_float(regime_use.get("niftyChangePct"))
    regime_label = str(regime_use.get("label") or regime_use.get("regime") or "UNRATED")
    regime_haircut = 1.0
    if nifty_chg is not None:
        # Extreme tape only — hard reject opposite sleeve
        if is_long and nifty_chg <= -REGIME_HARD_NIFTY_PCT:
            return _gate_payload(
                ENTRY_REGIME_AGAINST,
                exclude_reason=(
                    f"NIFTY {nifty_chg:.2f}% ≤ -{REGIME_HARD_NIFTY_PCT}% (hard block LONG)"
                ),
                quality_r=None,
                flags=["REGIME_AGAINST", "NIFTY_SHARP_DOWN", "REGIME_HARD"],
                ltp_source=ltp_source or None,
                day_move=day_move,
            )
        if (not is_long) and nifty_chg >= REGIME_HARD_NIFTY_PCT:
            return _gate_payload(
                ENTRY_REGIME_AGAINST,
                exclude_reason=(
                    f"NIFTY {nifty_chg:.2f}% ≥ +{REGIME_HARD_NIFTY_PCT}% (hard block SHORT)"
                ),
                quality_r=None,
                flags=["REGIME_AGAINST", "NIFTY_SHARP_UP", "REGIME_HARD"],
                ltp_source=ltp_source or None,
                day_move=day_move,
            )
        # Modest adverse tape — soft haircut (same pattern as OI misalign), still tradable
        if is_long and nifty_chg <= -REGIME_BLOCK_NIFTY_PCT:
            regime_haircut = REGIME_HEADWIND_HAIRCUT
            flags.append("REGIME_HEADWIND")
            flags.append("NIFTY_DOWN_SOFT")
        elif (not is_long) and nifty_chg >= REGIME_BLOCK_NIFTY_PCT:
            regime_haircut = REGIME_HEADWIND_HAIRCUT
            flags.append("REGIME_HEADWIND")
            flags.append("NIFTY_UP_SOFT")
    elif regime_label == "UNRATED":
        flags.append("REGIME_UNRATED")

    if turnover is not None and turnover < MIN_TURNOVER_CR:
        return _gate_payload(
            ENTRY_NO_EDGE,
            exclude_reason=f"turnover {turnover:.1f} Cr < {MIN_TURNOVER_CR}",
            quality_r=None,
            flags=["LOW_TURNOVER", *flags],
            ltp_source=ltp_source or None,
            day_move=day_move,
        )
    if turnover is None:
        flags.append("TURNOVER_MISSING")

    if wick is not None and wick > ENTRY_WICK_NOISE_MAX:
        return _gate_payload(
            ENTRY_NO_EDGE,
            exclude_reason=f"wick_noise_ratio {wick:.2f} > {ENTRY_WICK_NOISE_MAX}",
            quality_r=None,
            flags=["WICK_NOISE", *flags],
            ltp_source=ltp_source or None,
            day_move=day_move,
            oi_setup=oi_setup,
        )

    # --- OI preference (F&O only): prefer aligned first — soft haircut, not hard reject ---
    _oi, _prev_oi, _prev_close, oi_setup = _resolve_oi_facts(
        work, intra, quotes=quotes, live=live
    )
    has_fno_oi = (_oi is not None and _oi > 0) or (_prev_oi is not None and _prev_oi > 0)
    oi_aligned: bool | None = None
    if not has_fno_oi:
        flags.append("OI_MISSING")
    else:
        flags.append("FNO_OI")
        if oi_setup:
            flags.append(f"OI_{oi_setup}")
        allowed = OI_LONG_OK if is_long else OI_SHORT_OK
        oi_aligned = bool(oi_setup and oi_setup in allowed)
        if oi_aligned:
            flags.append("OI_PREFERRED")
        else:
            flags.append("OI_MISALIGNED")
            # Opt-in hard gate only (default soft)
            if OI_REQUIRE_FNO:
                return _gate_payload(
                    ENTRY_NO_EDGE,
                    exclude_reason=(
                        f"OI {oi_setup or 'NEUTRAL'} not aligned for "
                        f"{'LONG' if is_long else 'SHORT'} "
                        f"(need {'/'.join(sorted(allowed))})"
                    ),
                    quality_r=None,
                    flags=flags,
                    ltp_source=ltp_source or None,
                    day_move=day_move,
                    oi_setup=oi_setup,
                    oi_aligned=False,
                )
        # Soft demotion signal when extended move + adverse OI (still not a hard block alone)
        if is_long and oi_setup == "LONG_UNWINDING":
            flags.append("OI_EXHAUSTION_CLASH")
        if (not is_long) and oi_setup == "SHORT_COVERING":
            flags.append("OI_EXHAUSTION_CLASH")

    exhausted = False
    hard_exhausted = False
    if move_pct is not None:
        signed = move_pct if is_long else -move_pct
        if signed >= EXHAUSTION_HARD_PCT:
            hard_exhausted = True
            exhausted = True
            flags.append("EXHAUSTION_HARD")
        elif signed >= EXHAUSTION_PCT:
            exhausted = True
            flags.append("EXHAUSTION_SOFT")

    exceptional = False
    if exhausted and not hard_exhausted:
        regime_ok = (
            (is_long and regime_label == "RISK_ON")
            or ((not is_long) and regime_label == "RISK_OFF")
        )
        score_ok = score is not None and score >= ENTRY_EXCEPTIONAL_SCORE
        # OI is preference only: aligned helps exceptional; misaligned does not hard-block it
        clash = "OI_EXHAUSTION_CLASH" in flags
        if in_play and score_ok and regime_ok and not clash:
            exceptional = True
            flags.append("EXCEPTIONAL_CONTINUATION")
        elif in_play and score_ok and regime_ok and clash and oi_aligned:
            # Aligned OI can still rescue soft exhaustion; clash alone prefers skip
            exceptional = True
            flags.append("EXCEPTIONAL_CONTINUATION")
            flags.append("OI_RESCUE")
        else:
            why = "no exceptional continuation"
            if clash:
                why = f"OI {oi_setup} clashes with extended move (prefer skip)"
            return _gate_payload(
                ENTRY_EXHAUSTED,
                exclude_reason=(
                    f"|move| {abs(move_pct):.2f}% ≥ {EXHAUSTION_PCT}% ({why})"
                ),
                quality_r=None,
                flags=flags,
                ltp_source=ltp_source or None,
                day_move=day_move,
                oi_setup=oi_setup,
                oi_aligned=oi_aligned,
            )
    elif hard_exhausted:
        return _gate_payload(
            ENTRY_EXHAUSTED,
            exclude_reason=f"|move| {abs(move_pct):.2f}% ≥ {EXHAUSTION_HARD_PCT}% hard cap",
            quality_r=None,
            flags=flags,
            ltp_source=ltp_source or None,
            day_move=day_move,
            oi_setup=oi_setup,
            oi_aligned=oi_aligned,
        )

    # Overextended flag from factor score (when present) — soft exhaustion signal.
    if work.get("overextended") and not exceptional:
        return _gate_payload(
            ENTRY_EXHAUSTED,
            exclude_reason="overextended factor flag",
            quality_r=None,
            flags=["OVEREXTENDED", *flags],
            ltp_source=ltp_source or None,
            day_move=day_move,
            oi_setup=oi_setup,
        )

    vwap_dist_pct: float | None = None
    if ltp is not None and vwap is not None and vwap > 0:
        vwap_dist_pct = ((ltp - vwap) / vwap) * 100.0
        chase_vwap = (is_long and vwap_dist_pct >= VWAP_CHASE_PCT) or (
            (not is_long) and vwap_dist_pct <= -VWAP_CHASE_PCT
        )
        if chase_vwap:
            flags.append("TOO_FAR_FROM_VWAP")
            strong = score is not None and score >= ENTRY_EXCEPTIONAL_SCORE * 0.9
            if strong or in_play:
                base_r = T1_R_LONG if is_long else T1_R_SHORT
                adj = round(base_r * 0.55, 3)
                return _gate_payload(
                    ENTRY_WAIT_RETEST,
                    exclude_reason=(
                        f"price {vwap_dist_pct:+.2f}% from VWAP "
                        f"(limit ±{VWAP_CHASE_PCT}%) — wait retest"
                    ),
                    quality_r=adj,
                    flags=flags,
                    ltp_source=ltp_source or None,
                    day_move=day_move,
                    oi_setup=oi_setup,
                )
            return _gate_payload(
                ENTRY_NO_EDGE,
                exclude_reason=f"chase vs VWAP {vwap_dist_pct:+.2f}%",
                quality_r=None,
                flags=flags,
                ltp_source=ltp_source or None,
                day_move=day_move,
                oi_setup=oi_setup,
            )
    else:
        flags.append("VWAP_MISSING")

    if ltp is not None and orb_high is not None and orb_low is not None and orb_high >= orb_low > 0:
        if is_long and ltp > orb_high:
            orb_ext = ((ltp - orb_high) / orb_high) * 100.0
            if orb_ext >= ORB_CHASE_PCT:
                flags.append("TOO_FAR_FROM_ORB")
                return _gate_payload(
                    ENTRY_WAIT_RETEST,
                    exclude_reason=(
                        f"LONG {orb_ext:.2f}% above ORB high "
                        f"(limit {ORB_CHASE_PCT}%) — wait ORB retest"
                    ),
                    quality_r=round((T1_R_LONG if is_long else T1_R_SHORT) * 0.5, 3),
                    flags=flags,
                    ltp_source=ltp_source or None,
                    day_move=day_move,
                    oi_setup=oi_setup,
                )
        elif (not is_long) and ltp < orb_low:
            orb_ext = ((orb_low - ltp) / orb_low) * 100.0
            if orb_ext >= ORB_CHASE_PCT:
                flags.append("TOO_FAR_FROM_ORB")
                return _gate_payload(
                    ENTRY_WAIT_RETEST,
                    exclude_reason=(
                        f"SHORT {orb_ext:.2f}% below ORB low "
                        f"(limit {ORB_CHASE_PCT}%) — wait ORB retest"
                    ),
                    quality_r=round(T1_R_SHORT * 0.5, 3),
                    flags=flags,
                    ltp_source=ltp_source or None,
                    day_move=day_move,
                    oi_setup=oi_setup,
                )
    else:
        flags.append("ORB_MISSING")

    base_r = T1_R_LONG if is_long else T1_R_SHORT
    adj = float(base_r)
    if atr is None or atr <= 0:
        flags.append("ATR_MISSING")
        return _gate_payload(
            ENTRY_NO_EDGE,
            exclude_reason="ATR% missing — cannot compute risk distance",
            quality_r=None,
            flags=flags,
            ltp_source=ltp_source or None,
            day_move=day_move,
            oi_setup=oi_setup,
        )
    if atr > MAX_ATR_PCT * 0.75:
        adj *= 0.75
        flags.append("WIDE_STOP_HAIRCUT")
    if vwap_dist_pct is not None:
        adj *= max(0.55, 1.0 - abs(vwap_dist_pct) / max(VWAP_CHASE_PCT * 3.0, 1.0) * 0.25)
    if exceptional:
        adj *= 0.85
        flags.append("EXHAUSTION_DISCOUNT")
    if regime_label == "UNRATED":
        adj *= 0.90
    if score is not None and score < REPLACEMENT_MIN_SCORE:
        adj *= 0.70
        flags.append("LOW_SCORE_HAIRCUT")
    # Soft OI preference: boost aligned / haircut misaligned (never invent OI)
    if oi_aligned is True:
        adj *= OI_ALIGN_BONUS
        flags.append("OI_ALIGN_BONUS")
    elif oi_aligned is False:
        adj *= OI_MISALIGN_HAIRCUT
        flags.append("OI_MISALIGN_HAIRCUT")
    # Soft regime headwind (modest adverse NIFTY) — size down, do not kill the sleeve
    if regime_haircut < 1.0:
        adj *= regime_haircut
        flags.append("REGIME_HAIRCUT")

    adj = round(adj, 3)
    if adj < ENTRY_MIN_EXPECTED_R:
        return _gate_payload(
            ENTRY_NO_EDGE,
            exclude_reason=f"qualityAdjustedExpectedR {adj:.3f} < {ENTRY_MIN_EXPECTED_R}",
            quality_r=adj,
            flags=flags,
            ltp_source=ltp_source or None,
            day_move=day_move,
            oi_setup=oi_setup,
            oi_aligned=oi_aligned,
        )
    # Replacement path only: enforce minimum score (morning scan uses expected-R hurdle).
    if (quotes or live) and score is not None and score < REPLACEMENT_MIN_SCORE:
        return _gate_payload(
            ENTRY_NO_EDGE,
            exclude_reason=f"score {score:.1f} < {REPLACEMENT_MIN_SCORE}",
            quality_r=adj,
            flags=["LOW_SCORE", *flags],
            ltp_source=ltp_source or None,
            day_move=day_move,
            oi_setup=oi_setup,
            oi_aligned=oi_aligned,
        )

    if in_play:
        flags.append("IN_PLAY")
    return _gate_payload(
        ENTRY_QUALIFIED,
        exclude_reason=None,
        quality_r=adj,
        flags=flags,
        ltp_source=ltp_source or None,
        day_move=day_move,
        oi_setup=oi_setup,
        oi_aligned=oi_aligned,
    )


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
    risk = cap_stop_risk(entry, risk)  # hard cap 0.5%
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


def _entry_grade(expected_r: float, flags: list[str] | None = None) -> str:
    """Deterministic immediate-follow-through classification."""
    flags = flags or []
    confirmations = sum(
        marker in flags
        for marker in ("IN_PLAY", "OI_PREFERRED", "OI_ALIGN_BONUS")
    )
    if expected_r >= PRIORITY_EXPECTED_R and confirmations >= 1:
        return "ENTRY_A"
    if expected_r >= ENTRY_MIN_EXPECTED_R:
        return "ENTRY_B"
    if expected_r > 0:
        return "ENTRY_C"
    return "REJECT"


def _trade_quality(row: dict[str, Any]) -> float:
    """Configuration-compatible 0..100 score that does not replace Expected-R."""
    expected_r = float(row.get("qualityAdjustedExpectedR") or 0.0)
    components = row.get("factorBreakdown") or row.get("components") or {}

    def component(name: str, fallback: float = 50.0) -> float:
        value = components.get(name) if isinstance(components, dict) else None
        if isinstance(value, dict):
            value = value.get("score")
        try:
            return _clamp(float(value))
        except (TypeError, ValueError):
            return fallback

    entry = 100.0 if row.get("entryState") == ENTRY_QUALIFIED else 0.0
    expected = _clamp(expected_r / max(HIGH_CONVICTION_R, 0.01) * 100.0)
    score = (
        0.25 * entry
        + 0.20 * expected
        + 0.15 * component("trend")
        + 0.10 * component("vwap")
        + 0.10 * component("volume")
        + 0.10 * component("momentum")
        + 0.05 * (100.0 if row.get("oiAligned") is True else 50.0)
        + 0.05 * component("sector")
    )
    return round(score, 2)


def _apply_sector_rotation(
    scored: dict[str, Any], sector: str, direction: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replace the legacy stock-range proxy with live NSE sector context."""
    if scored.get("score") is None:
        return scored, {"rated": False, "score": 50.0}
    signal = sector_signal(sector, direction, _safe_float(scored.get("dayChangePct")))
    if not signal.get("rated"):
        return scored, signal
    components = dict(scored.get("components") or {})
    components["sector"] = {
        "score": signal["score"],
        "weight": W_SECTOR,
        "rated": True,
        "index": signal.get("index"),
        "sectorChangePct": signal.get("sectorChangePct"),
        "stockVsSectorPct": signal.get("stockVsSectorPct"),
        "leader": signal.get("leader"),
        "stale": signal.get("stale"),
        "updatedAt": signal.get("updatedAt"),
    }
    rated = [c for c in components.values() if c.get("rated")]
    total_weight = sum(float(c.get("weight") or 0) for c in rated)
    adjusted_score = (
        sum(float(c.get("score") or 0) * float(c.get("weight") or 0) for c in rated)
        / total_weight
        if total_weight > 0
        else float(scored.get("score") or 0)
    )
    return {**scored, "score": round(_clamp(adjusted_score), 1), "components": components}, signal


def _allocate_portfolio(rows: list[dict[str, Any]], capital: float) -> list[dict[str, Any]]:
    """Conviction/risk size with hard capital and portfolio-risk invariants."""
    remaining = max(0.0, capital)
    remaining_risk = max(0.0, capital * MAX_PORTFOLIO_RISK)
    out: list[dict[str, Any]] = []
    raw_bands = [
        0.30 if float(r.get("qualityAdjustedExpectedR") or 0) >= HIGH_CONVICTION_R
        else (0.20 if float(r.get("qualityAdjustedExpectedR") or 0) >= PRIORITY_EXPECTED_R else 0.10)
        for r in rows
    ]
    band_scale = min(1.0, 1.0 / sum(raw_bands)) if raw_bands else 1.0
    for row, raw_band in zip(rows, raw_bands):
        entry = float(row.get("entryPrice") or row.get("ltp") or 0.0)
        risk = float(row.get("riskPerShare") or 0.0)
        expected_r = float(row.get("qualityAdjustedExpectedR") or 0.0)
        if entry <= 0 or risk <= 0 or remaining < entry or remaining_risk <= 0:
            continue
        band = raw_band * band_scale
        risk_budget = min(capital * MAX_SINGLE_TRADE_RISK, remaining_risk)
        qty = min(
            int((capital * band + 0.01) // entry),
            int((risk_budget + 0.01) // risk),
            int((remaining + 0.01) // entry),
        )
        if qty <= 0:
            continue
        deployed = round(qty * entry, 2)
        max_loss = round(qty * risk, 2)
        grade = _entry_grade(expected_r, row.get("entryFlags"))
        out.append({
            **row,
            "approxQty": qty,
            "deployedCapital": deployed,
            "maxLoss": max_loss,
            "entryQuality": grade,
            "convictionTier": grade[-1] if grade.startswith("ENTRY_") else None,
            "tradeQualityScore": _trade_quality(row),
            "allocationPct": round(deployed / capital * 100.0, 2) if capital else 0.0,
        })
        remaining = round(max(0.0, remaining - deployed), 2)
        remaining_risk = round(max(0.0, remaining_risk - max_loss), 2)
    return out


def _select_total_portfolio(
    long_rows: list[dict[str, Any]], short_rows: list[dict[str, Any]], capital: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Stable top-N total selection with side, sector and duplicate controls."""
    candidates = []
    for row in [*long_rows, *short_rows]:
        if row.get("entryState") != ENTRY_QUALIFIED:
            continue
        enriched = {**row, "tradeQualityScore": _trade_quality(row)}
        candidates.append(enriched)
    candidates.sort(key=lambda r: (
        -float(r.get("tradeQualityScore") or 0),
        -float(r.get("qualityAdjustedExpectedR") or 0),
        -float(r.get("score") or 0),
        str(r.get("symbol") or ""),
        str(r.get("direction") or ""),
    ))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    sectors: dict[str, int] = {}
    sides = {"LONG": 0, "SHORT": 0}
    for row in candidates:
        if len(selected) >= LOCK_SIZE:
            break
        symbol = str(row.get("symbol") or "").upper()
        side = str(row.get("direction") or "").upper()
        sector = str(row.get("sector") or "OTHER").upper()
        if not symbol or symbol in seen or side not in sides:
            continue
        # Side limits are intentionally soft: quality rank wins and one-sided
        # five-name books remain valid. Counts are retained for audit/reporting.
        if sectors.get(sector, 0) >= MAX_PER_SECTOR:
            continue
        selected.append(row)
        seen.add(symbol)
        sides[side] += 1
        sectors[sector] = sectors.get(sector, 0) + 1
    sized = _allocate_portfolio(selected, capital)
    for rank, row in enumerate(sized, 1):
        row["rank"] = rank
        row["whySelected"] = (
            f"Rank #{rank}; {row.get('entryQuality')}; expected R "
            f"{float(row.get('qualityAdjustedExpectedR') or 0):.2f}; "
            f"trade quality {float(row.get('tradeQualityScore') or 0):.1f}."
        )
    return (
        [r for r in sized if r.get("direction") == "LONG"],
        [r for r in sized if r.get("direction") == "SHORT"],
    )


def _adopt_high_probability(
    rows: list[dict[str, Any]],
    n: int,
    *,
    direction: str,
    capital: float,
    regime: dict[str, Any],
    exclude_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    """From candidate pool (≈10/side), keep top-n QUALIFIED by score / in-play / RR."""
    if n <= 0 or not rows:
        return []
    blocked = {str(s).upper().strip() for s in (exclude_symbols or set()) if str(s).strip()}
    ranked = sorted(
        rows,
        key=lambda r: (
            1.0 if r.get("entryState") == ENTRY_QUALIFIED else 0.0,
            1.0 if r.get("oiAligned") is True else (0.5 if r.get("oiAligned") is None else 0.0),
            float(r.get("qualityAdjustedExpectedR") or 0.0),
            float(r.get("score") or 0.0),
            1.0 if r.get("inPlay") else 0.0,
            float(r.get("scorePctRank") or 0.0),
            float(r.get("rewardRisk") or 0.0),
        ),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    risk_scale = _regime_risk_scale(regime, direction)
    for row in ranked:
        if len(out) >= n:
            break
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym or sym in blocked:
            continue
        # Re-run gate at adopt time (honest; demotes exhausted/chasing).
        gate = entry_quality_gate(row, direction, regime)
        state = str(gate.get("entryState") or "")
        if state != ENTRY_QUALIFIED:
            continue
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
        out.append(
            attach_exit_plan(
                {
                    **row,
                    **sizing,
                    "rank": len(out) + 1,
                    "adopted": True,
                    "adoptReason": "HIGH_PROBABILITY_SCORE",
                    "candidatePoolSize": len(rows),
                    "entryState": gate["entryState"],
                    "excludeReason": gate.get("excludeReason"),
                    "qualityAdjustedExpectedR": gate.get("qualityAdjustedExpectedR"),
                    "entryFlags": gate.get("flags") or [],
                    "oiSetup": gate.get("oiSetup") or row.get("oiSetup"),
                    "oiAligned": gate.get("oiAligned"),
                }
            )
        )
        blocked.add(sym)
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
        # Hard rejects stay out of the live pool; WAIT_RETEST may sit for later rotation.
        entry_state = str(cand.get("entryState") or "")
        if entry_state in _ENTRY_HARD_REJECT:
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
        row = {
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
            "turnoverCr": cand.get("turnoverCr"),
            "wickNoiseRatio": cand.get("wickNoiseRatio"),
            "factorBreakdown": cand.get("components"),
            "entryState": cand.get("entryState"),
            "excludeReason": cand.get("excludeReason"),
            "qualityAdjustedExpectedR": cand.get("qualityAdjustedExpectedR"),
            "entryFlags": cand.get("entryFlags") or [],
            "ltp": round(float(entry), 2),
            "scanLtp": round(float(entry), 2),
            "ltpSource": cand.get("ltpSource"),
            "atrPct": atr,
            "status": "RUNNING" if entry_state == ENTRY_QUALIFIED else "WAIT",
            "closed": False,
            **levels,
            **sizing,
        }
        picked.append(attach_exit_plan(row))
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


def generate_candidates(
    snapshot: dict[str, Any] | None = None,
    *,
    include_full_hunt: bool = False,
) -> dict[str, Any]:
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
    gate_reject = 0
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
            scored, sector_ctx = _apply_sector_rotation(scored, sector, direction)
            if scored.get("score") is None:
                unrated += 1
                continue
            base = {
                "symbol": sym,
                "name": row.get("name"),
                "sector": sector,
                "sectorIndex": sector_ctx.get("index"),
                "sectorChangePct": sector_ctx.get("sectorChangePct"),
                "stockVsSectorPct": sector_ctx.get("stockVsSectorPct"),
                "sectorLeader": sector_ctx.get("leader"),
                "sectorDataStale": sector_ctx.get("stale"),
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
                "turnoverCr": _safe_float(intra.get("turnover_cr")),
                "wickNoiseRatio": _safe_float(intra.get("wick_noise_ratio")),
                "oi": _safe_float(row.get("oi") if row.get("oi") is not None else intra.get("oi")),
                "prev_oi": _safe_float(
                    row.get("prev_oi")
                    if row.get("prev_oi") is not None
                    else row.get("previousOI") if row.get("previousOI") is not None else intra.get("prev_oi")
                ),
                "close": _safe_float(row.get("close")),
                "oiSetup": (
                    str(intra.get("oi_setup") or row.get("oi_setup") or "").upper().strip() or None
                ),
                "filterReasons": reasons,
                "ltpSource": row.get("ltpSource") or row.get("ltp_source"),
                "intraday": intra,
            }
            gate = entry_quality_gate(base, direction, regime)
            base["entryState"] = gate["entryState"]
            base["excludeReason"] = gate.get("excludeReason")
            base["qualityAdjustedExpectedR"] = gate.get("qualityAdjustedExpectedR")
            base["entryFlags"] = gate.get("flags") or []
            base["oiSetup"] = gate.get("oiSetup") or base.get("oiSetup")
            base["oiAligned"] = gate.get("oiAligned")
            # Drop nested intraday after gate — flat fields are enough for adopt re-check.
            base.pop("intraday", None)
            if gate["entryState"] in _ENTRY_HARD_REJECT:
                gate_reject += 1
            mom_bucket.append(base)

            mr = _factor_scores_meanrev(row, regime, direction)
            mr, mr_sector_ctx = _apply_sector_rotation(mr, sector, direction)
            if mr.get("score") is not None:
                mr_row = {
                    **base,
                    "score": mr["score"],
                    "meanrevScore": mr["score"],
                    "components": mr.get("components"),
                    "sleeve": "MEAN_REVERSION",
                    "gateReason": mr.get("gateReason"),
                    "sectorIndex": mr_sector_ctx.get("index"),
                    "sectorChangePct": mr_sector_ctx.get("sectorChangePct"),
                    "stockVsSectorPct": mr_sector_ctx.get("stockVsSectorPct"),
                    "sectorLeader": mr_sector_ctx.get("leader"),
                    "sectorDataStale": mr_sector_ctx.get("stale"),
                }
                mr_gate = entry_quality_gate(mr_row, direction, regime)
                mr_row["entryState"] = mr_gate["entryState"]
                mr_row["excludeReason"] = mr_gate.get("excludeReason")
                mr_row["qualityAdjustedExpectedR"] = mr_gate.get("qualityAdjustedExpectedR")
                mr_row["entryFlags"] = mr_gate.get("flags") or []
                mr_row["oiSetup"] = mr_gate.get("oiSetup") or mr_row.get("oiSetup")
                mr_row["oiAligned"] = mr_gate.get("oiAligned")
                mr_bucket.append(mr_row)
                # Stash MR score on momentum row for UI transparency
                base["meanrevScore"] = mr["score"]

    _attach_percentile_ranks(long_scored)
    _attach_percentile_ranks(short_scored)
    _attach_percentile_ranks(long_mr)
    _attach_percentile_ranks(short_mr)

    def _rank_key(x: dict[str, Any]) -> tuple:
        # Prefer OI-aligned F&O names first (soft); unknown/cash mid; misaligned last
        oa = x.get("oiAligned")
        oi_pref = 1.0 if oa is True else (0.5 if oa is None else 0.0)
        return (
            1 if x.get("entryState") == ENTRY_QUALIFIED else 0,
            oi_pref,
            float(x.get("qualityAdjustedExpectedR") or 0),
            float(x.get("score") or 0),
        )

    long_scored.sort(key=_rank_key, reverse=True)
    short_scored.sort(key=_rank_key, reverse=True)
    long_mr.sort(key=_rank_key, reverse=True)
    short_mr.sort(key=_rank_key, reverse=True)

    # Sequential construction: long first, then short excludes long basket symbols
    # (avoids wiping MR pool via premature opposite-side top-N filter)
    # Also exclude today's locked swing symbols and swing-higher-probability BUY names.
    swing_exclude = set(swing_locked_symbols(_ist_now().strftime("%Y-%m-%d")))
    for row in long_scored + long_mr:
        sym = str(row.get("symbol") or "").upper().strip()
        if sym and swing_prefers_over_intraday(sym, row, snapshot=snap):
            swing_exclude.add(sym)
    long_basket = _construct_dual_sleeve(
        long_scored[:60],
        long_mr[:60],
        "LONG",
        LONG_CAPITAL,
        regime,
        mr_gate_open,
        exclude_symbols=swing_exclude or None,
    )
    long_syms = {p["symbol"] for p in long_basket} | set(swing_exclude)
    short_basket = _construct_dual_sleeve(
        short_scored[:60],
        short_mr[:60],
        "SHORT",
        SHORT_CAPITAL,
        regime,
        mr_gate_open,
        exclude_symbols=long_syms,
    )

    # One ranked portfolio: five total is a maximum, never a per-side target.
    adopt_long, adopt_short = _select_total_portfolio(
        long_basket, short_basket, INTRADAY_CAPITAL
    )
    deployed = round(sum(float(r.get("deployedCapital") or 0) for r in [*adopt_long, *adopt_short]), 2)
    portfolio_risk = round(sum(float(r.get("maxLoss") or 0) for r in [*adopt_long, *adopt_short]), 2)

    body = {
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
            "configuredCapital": INTRADAY_CAPITAL,
            "longCapital": LONG_CAPITAL,
            "shortCapital": SHORT_CAPITAL,
            "deployedCapital": deployed,
            "remainingCapital": round(max(0.0, INTRADAY_CAPITAL - deployed), 2),
            "portfolioRisk": portfolio_risk,
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
            "gateReject": gate_reject,
            "longScored": len(long_scored),
            "shortScored": len(short_scored),
            "longMeanRevScored": len(long_mr),
            "shortMeanRevScored": len(short_mr),
            "unratedComponents": unrated,
            "candidatePool": len(long_basket) + len(short_basket),
            "adopted": len(adopt_long) + len(adopt_short),
            "funnelNote": (
                f"{BASKET_SIZE}+{BASKET_SIZE} candidates -> adopt top "
                f"{LOCK_SIZE} TOTAL QUALIFIED by entry gate"
            ),
        },
        "entryGate": {
            "exhaustionPct": EXHAUSTION_PCT,
            "exhaustionHardPct": EXHAUSTION_HARD_PCT,
            "vwapChasePct": VWAP_CHASE_PCT,
            "orbChasePct": ORB_CHASE_PCT,
            "regimeBlockNiftyPct": REGIME_BLOCK_NIFTY_PCT,
            "regimeHardNiftyPct": REGIME_HARD_NIFTY_PCT,
            "regimeHeadwindHaircut": REGIME_HEADWIND_HAIRCUT,
            "minExpectedR": ENTRY_MIN_EXPECTED_R,
            "oiRequireFno": OI_REQUIRE_FNO,
            "oiPreferFirst": True,
            "oiMisalignHaircut": OI_MISALIGN_HAIRCUT,
            "oiAlignBonus": OI_ALIGN_BONUS,
            "oiLongOk": sorted(OI_LONG_OK),
            "oiShortOk": sorted(OI_SHORT_OK),
            "dailyLossLimitInr": DAILY_LOSS_LIMIT_INR,
            "maxConcurrentNames": MAX_CONCURRENT_NAMES,
            "replacementCutoff": REPLACEMENT_CUTOFF_HHMM,
            "maxDailyReplacements": MAX_DAILY_REPLACEMENTS,
            "maxDailyPositions": MAX_DAILY_POSITIONS,
            "reentry": {
                "enabled": REENTRY_ENABLED,
                "maxPerSymbol": REENTRY_MAX_PER_SYMBOL,
                "targetCooldownMin": REENTRY_TARGET_COOLDOWN_MIN,
                "profitTrailCooldownMin": REENTRY_TRAIL_COOLDOWN_MIN,
                "initialStopEnabled": REENTRY_ALLOW_INITIAL_STOP,
                "initialStopCooldownMin": REENTRY_INITIAL_STOP_COOLDOWN_MIN,
                "minScore": REENTRY_MIN_SCORE,
                "minExpectedR": REENTRY_MIN_EXPECTED_R,
                "breakoutBufferBps": REENTRY_BREAKOUT_BUFFER_BPS,
                "profitRiskScale": REENTRY_PROFIT_RISK_SCALE,
            },
            "maxPerSector": MAX_PER_SECTOR,
            "states": [
                ENTRY_QUALIFIED,
                ENTRY_WAIT_RETEST,
                ENTRY_EXHAUSTED,
                ENTRY_NO_EDGE,
                ENTRY_STALE_DATA,
                ENTRY_REGIME_AGAINST,
            ],
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
                "entryState": c.get("entryState"),
                "excludeReason": c.get("excludeReason"),
                "qualityAdjustedExpectedR": c.get("qualityAdjustedExpectedR"),
                "oiSetup": c.get("oiSetup"),
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
                "entryState": c.get("entryState"),
                "excludeReason": c.get("excludeReason"),
                "qualityAdjustedExpectedR": c.get("qualityAdjustedExpectedR"),
                "oiSetup": c.get("oiSetup"),
            }
            for c in short_scored[:20]
        ],
        # Full 10+10 research pool (not yet locked)
        "proposedLong": long_basket,
        "proposedShort": short_basket,
        # High-probability top five total that commit will lock
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
    if include_full_hunt:

        def _qualified_hunt(
            mom: list[dict[str, Any]],
            mr: list[dict[str, Any]],
            direction: str,
        ) -> list[dict[str, Any]]:
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for bucket in (mom, mr):
                for row in bucket:
                    if not isinstance(row, dict):
                        continue
                    if row.get("entryState") != ENTRY_QUALIFIED:
                        continue
                    sym = str(row.get("symbol") or "").upper()
                    if not sym or sym in seen:
                        continue
                    seen.add(sym)
                    item = dict(row)
                    item["direction"] = direction
                    out.append(item)
            return out

        body["replacementHuntLong"] = _qualified_hunt(long_scored, long_mr, "LONG")
        body["replacementHuntShort"] = _qualified_hunt(short_scored, short_mr, "SHORT")
    return body


def _maybe_refresh_live_snapshot(*, reason: str) -> dict[str, Any]:
    """During RTH, pull a fresh Angel snapshot when quotes are older than SNAPSHOT_STALE_SEC.

    Inline import: angel_one_feed imports this module for routes.
    """
    global _SNAP_REFRESH_LAST
    from .angel_one_feed import _snapshot_needs_live_refresh
    from .angel_one_feed import run_scheduled_live_refresh
    from .trade_outcome import _is_market_open

    snap = load_market_snapshot()
    if not _is_market_open():
        return snap
    if not _snapshot_needs_live_refresh(snap, stale_sec=SNAPSHOT_STALE_SEC):
        return snap
    now = time.monotonic()
    if (now - _SNAP_REFRESH_LAST) < _SNAP_REFRESH_MIN_GAP_SEC:
        return snap
    try:
        result = run_scheduled_live_refresh(reason=reason)
    except Exception:
        log.exception("intraday live snapshot refresh failed (%s)", reason)
        return load_market_snapshot()
    if not isinstance(result, dict) or result.get("success") is not True:
        log.warning(
            "intraday live snapshot refresh unsuccessful (%s): %s",
            reason,
            result.get("error") if isinstance(result, dict) else result,
        )
        return load_market_snapshot()
    _SNAP_REFRESH_LAST = time.monotonic()
    return load_market_snapshot()


def _replacement_source_pools(
    session: dict[str, Any],
    snap: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Market hours: QUALIFIED names from a live Nifty 500 hunt. After hours: morning lock pools."""
    from .trade_outcome import _is_market_open

    lock_long = list(session.get("candidatePoolLong") or [])
    lock_short = list(session.get("candidatePoolShort") or [])
    if not _is_market_open():
        return lock_long, lock_short, "lock_pool"
    key = str(snap.get("updatedAt") or "")
    now = time.monotonic()
    cache = _HUNT_POOL_CACHE
    if cache["key"] == key and cache["at"] and (now - float(cache["at"])) < _HUNT_TTL_SEC:
        return list(cache["long"] or []), list(cache["short"] or []), "live_universe_hunt"
    try:
        hunt = generate_candidates(snap, include_full_hunt=True)
    except Exception:
        log.exception("live replacement hunt failed — using morning lock pool")
        return lock_long, lock_short, "lock_pool_error"
    long_p = list(hunt.get("replacementHuntLong") or [])
    short_p = list(hunt.get("replacementHuntShort") or [])
    _HUNT_POOL_CACHE.update({"key": key, "at": now, "long": long_p, "short": short_p})
    return long_p, short_p, "live_universe_hunt"


def _plan_row_from_session(row: dict[str, Any], direction: str, session_date: str) -> dict[str, Any]:
    status = str(row.get("status") or "RUNNING")
    return {
        "symbol": row.get("symbol"),
        "direction": direction,
        "entryDate": session_date,
        "approxQty": row.get("approxQty"),
        "deployedCapital": row.get("deployedCapital"),
        "entryPrice": row.get("entryPrice"),
        "stopLoss": row.get("stopLoss"),
        "target1": row.get("target1"),
        "target2": row.get("target2"),
        "riskPerShare": row.get("riskPerShare"),
        "exitPlan": row.get("exitPlan"),
        "scanLtp": row.get("ltp") or row.get("scanLtp"),
        "currentPrice": row.get("ltp") or row.get("currentPrice"),
        "score": row.get("score"),
        "sector": row.get("sector"),
        "sleeve": row.get("sleeve"),
        "rewardRisk": row.get("rewardRisk"),
        "status": status,
        "closed": bool(row.get("closed")),
        "triggered": row.get("triggered"),
        "triggeredAt": row.get("triggeredAt"),
        "executionStatus": row.get("executionStatus"),
        "plannedCapital": row.get("plannedCapital"),
        "lockObservedPrice": row.get("lockObservedPrice"),
        "realizedPnl": row.get("realizedPnl"),
        "unrealizedPnl": row.get("unrealizedPnl"),
        "exitState": row.get("exitState"),
        "remainingQty": row.get("remainingQty"),
        "effectiveStop": row.get("effectiveStop"),
        "sessionLocked": True,
        "adopted": True,
        "source": row.get("source"),
        "replacedFrom": row.get("replacedFrom"),
        "replacedAt": row.get("replacedAt"),
        "reentryOf": row.get("reentryOf"),
        "reentryExitKind": row.get("reentryExitKind"),
        "reentryPreviousCloseAt": row.get("reentryPreviousCloseAt"),
        "reentryReferencePrice": row.get("reentryReferencePrice"),
        "reentryPreviousEconomicR": row.get("reentryPreviousEconomicR"),
        "reentryRiskScale": row.get("reentryRiskScale"),
        "reentrySameLogicConfirmed": row.get("reentrySameLogicConfirmed"),
        "reentryLogic": row.get("reentryLogic"),
    }


def sync_fixed_plan_from_session(session: dict[str, Any]) -> None:
    """Mirror today's locked Intraday session into fixed_trade_plan.json."""
    if not isinstance(session, dict) or not session.get("locked"):
        return
    session_date = str(session.get("sessionDate") or _ist_now().strftime("%Y-%m-%d"))[:10]
    plan = {
        "long": [
            _plan_row_from_session(r, "LONG", session_date)
            for r in (session.get("long") or [])
            if isinstance(r, dict) and r.get("symbol")
        ],
        "short": [
            _plan_row_from_session(r, "SHORT", session_date)
            for r in (session.get("short") or [])
            if isinstance(r, dict) and r.get("symbol")
        ],
        "updatedAt": session.get("updatedAt") or _utc_now_iso(),
        "sessionDate": session_date,
        "locked": True,
        "executionPolicy": session.get("executionPolicy") or "MANUAL_ONLY",
        "capital": session.get("capital"),
        "regime": session.get("regime"),
        "source": "intraday_session_engine",
        "funnel": session.get("funnel"),
        "rotation": "DAILY",
        "priorSessionDate": session.get("priorSessionDate"),
        "exitMode": "SCALE_TRAIL",
    }
    try:
        from .trade_outcome import save_fixed_trade_plan

        save_fixed_trade_plan(plan)
    except Exception as exc:
        log.warning("fixed plan sync failed: %s", exc)


def commit_session(force: bool = False, *, bypass_lock_window: bool = False) -> dict[str, Any]:
    """Lock up to five qualified names total; cash is valid when edge is absent.

    Daily rotation: a locked basket from a prior IST sessionDate is stale and
    force-rebuilt irrespective of P&L (mirrors swing_session).

    Time gate: primary 09:45–10:15 IST (or late-start catch-up). Only
    ``bypass_lock_window=True`` (operator emergency) skips the clock.
    ``force`` only means rebuild an already-locked basket — it does not open early.
    """
    today = _ist_now().strftime("%Y-%m-%d")
    reconcile_cross_book(today, persist=True)
    existing = load_session()
    existing_date = str(existing.get("sessionDate") or "").strip()[:10]
    stale_day = bool(
        existing.get("locked")
        and existing_date
        and existing_date != today
    )
    if stale_day and not force:
        log.info(
            "Intraday sessionDate %s != today %s — forcing daily rotate",
            existing_date,
            today,
        )
        force = True

    if stale_day and existing_date:
        try:
            from datetime import date as _date

            from .eod_book_cache import freeze_dated_books_from_live

            freeze_dated_books_from_live(_date.fromisoformat(existing_date[:10]))
        except Exception as exc:
            log.warning("Prior-day EOD freeze failed for %s: %s", existing_date, exc)

    if existing.get("locked") and not force:
        return {
            "success": False,
            "error": "SESSION BASKET LOCKED — symbols immutable. Pass force=true only to rebuild after explicit unlock.",
            "session": existing,
            "alreadyLocked": True,
        }

    allowed, reason = basket_lock_allowed(allow_manual_override=bool(bypass_lock_window))
    if not allowed:
        return {
            "success": False,
            "error": basket_lock_block_message(reason),
            "lockWindow": reason,
            "lockWindowConfig": lock_window_config(),
            "session": existing,
        }

    candidates = generate_candidates()
    pool_long = candidates.get("proposedLong") or []
    pool_short = candidates.get("proposedShort") or []
    long_rows = candidates.get("adoptLong") or []
    short_rows = candidates.get("adoptShort") or []
    regime = candidates.get("regime") or {}

    # generate_candidates already applies the single total selector and capital guard.
    long_rows = long_rows[:LOCK_SIZE]
    short_rows = short_rows[: max(0, LOCK_SIZE - len(long_rows))]
    # A stale feed can lock a plan, but cannot prove an execution. Fresh locks
    # use the observed candidate LTP as timestamped modeled-fill evidence.
    committed_at = _utc_now_iso()
    feed_stale_at_lock = bool(candidates.get("dataStale"))
    def _stamp_execution(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        planned = float(out.get("deployedCapital") or 0)
        out["plannedCapital"] = planned
        out["lockObservedPrice"] = _safe_float(out.get("ltp") or out.get("currentPrice"))
        if feed_stale_at_lock:
            out.update({
                "triggered": False,
                "executionStatus": "PENDING_ENTRY",
                "triggeredAt": None,
                "deployedCapital": 0.0,
                "status": "PENDING ENTRY",
            })
        else:
            out.update({
                "triggered": True,
                "executionStatus": "TRIGGERED",
                "triggeredAt": committed_at,
            })
        return out
    long_rows = [_stamp_execution(r) for r in long_rows]
    short_rows = [_stamp_execution(r) for r in short_rows]
    cash_held = len(long_rows) + len(short_rows) < LOCK_SIZE
    short_cash_held = len(short_rows) < MAX_SHORT_POSITIONS
    short_cash_reason = None
    if short_cash_held:
        short_cash_reason = (
            f"Portfolio {len(long_rows) + len(short_rows)}/{LOCK_SIZE} — cash held "
            f"(regime={regime.get('label')} nifty={regime.get('niftyChangePct')})"
        )
        log.warning("Intraday commit %s", short_cash_reason)

    session_date = _ist_now().strftime("%Y-%m-%d")
    events = [
        {
            "type": "SESSION_COMMIT",
            "at": committed_at,
            "long": [r["symbol"] for r in long_rows],
            "short": [r["symbol"] for r in short_rows],
            "candidatePoolLong": [r["symbol"] for r in pool_long],
            "candidatePoolShort": [r["symbol"] for r in pool_short],
            "funnel": f"{len(pool_long)}+{len(pool_short)} → adopt {len(long_rows) + len(short_rows)} total",
            "shortCashHeld": short_cash_held,
            "shortCashReason": short_cash_reason,
            "sleeves": {
                "momentumSlots": MOMENTUM_SLOTS,
                "meanRevSlots": (candidates.get("capital") or {}).get("meanRevSlots"),
                "lockSize": LOCK_SIZE,
                "candidatePoolSize": BASKET_SIZE,
                "totalFilled": len(long_rows) + len(short_rows),
            },
            "executionPolicy": "MANUAL_ONLY",
        }
    ]
    try:
        from .trade_outcome import emit_book_lock_alerts

        emit_book_lock_alerts(
            book="INTRADAY",
            session_date=session_date,
            long_rows=[r for r in long_rows if r.get("triggered")],
            short_rows=[r for r in short_rows if r.get("triggered")],
        )
    except Exception as exc:
        log.warning("Intraday lock alerts failed: %s", exc)

    capital = dict(candidates.get("capital") or {})
    capital["basketSize"] = LOCK_SIZE
    capital["candidatePoolSize"] = BASKET_SIZE
    capital["lockSize"] = LOCK_SIZE
    capital["shortFilled"] = len(short_rows)
    capital["shortCashHeld"] = short_cash_held
    capital["cashHeld"] = cash_held
    deployed = round(sum(float(r.get("deployedCapital") or 0) for r in [*long_rows, *short_rows]), 2)
    if deployed > INTRADAY_CAPITAL + 0.01:
        return {"success": False, "error": "CAPITAL_INVARIANT_VIOLATION", "candidates": candidates}
    capital["deployedCapital"] = deployed
    capital["remainingCapital"] = round(max(0.0, INTRADAY_CAPITAL - deployed), 2)
    if short_cash_reason:
        capital["shortCashReason"] = short_cash_reason

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
        "rotation": "DAILY",
        "priorSessionDate": existing_date if stale_day else None,
        "rotated": bool(stale_day),
        "shortCashHeld": short_cash_held,
        "shortCashReason": short_cash_reason,
    }
    save_session(session)

    try:
        from .swing_session import ensure_swing_session_locked
        ensure_swing_session_locked()
    except Exception as exc:
        log.warning("Swing session auto-lock failed: %s", exc)

    session["fixedPlanSynced"] = True
    save_session(session)
    sync_fixed_plan_from_session(session)
    return session


def ensure_intraday_session_locked() -> dict[str, Any]:
    """Idempotent lock — rotates automatically when sessionDate != IST today.

    Always returns a session-shaped dict (locked/sessionDate) for scheduler consumers.
    """
    existing = load_session()
    today = _ist_now().strftime("%Y-%m-%d")
    existing_date = str(existing.get("sessionDate") or "").strip()[:10]
    # A current-day cash-held lock with zero names is valid. Replacement
    # hunting may fill it later; do not make it impossible to re-enter because
    # commit_session correctly refuses to overwrite today's immutable lock.
    if existing.get("locked") and existing_date == today:
        return existing
    result = commit_session(force=bool(existing.get("locked") and existing_date != today))
    if isinstance(result, dict) and result.get("locked") and result.get("sessionDate"):
        return result
    nested = result.get("session") if isinstance(result, dict) else None
    if isinstance(nested, dict) and nested.get("locked"):
        out = dict(nested)
        if result.get("error"):
            out["commitError"] = result.get("error")
        if result.get("alreadyLocked"):
            out["alreadyLocked"] = True
        return out
    # Commit failed — return current disk session so callers still see shape
    failed = dict(existing) if isinstance(existing, dict) else {}
    failed.setdefault("locked", False)
    if isinstance(result, dict) and result.get("error"):
        failed["commitError"] = result.get("error")
    # Stale prior-day lock must never look "healthy" — stamp rotation failure on disk
    if existing.get("locked") and existing_date and existing_date != today:
        failed["locked"] = True
        failed["sessionDate"] = existing_date
        failed["rotationPending"] = True
        failed["rotationError"] = (
            result.get("error") if isinstance(result, dict) else "commit_failed"
        )
        failed["rotationAttemptedAt"] = _utc_now_iso()
        try:
            save_session(failed)
        except Exception as exc:
            log.warning("Failed to persist rotationPending flag: %s", exc)
    return failed


def _cutoff_passed(now: datetime | None = None) -> bool:
    """True when IST clock is at/after REPLACEMENT_CUTOFF_HHMM (default 14:45)."""
    n = now or _ist_now()
    cutoff = _hhmm_to_minutes(REPLACEMENT_CUTOFF_HHMM)
    return (n.hour * 60 + n.minute) >= cutoff


def _sum_realized_pnl(rows: list[dict[str, Any]]) -> float | None:
    """Sum realized P&L from position rows / exitState (facts only; None if none)."""
    vals: list[float] = []
    for r in rows:
        v = r.get("realizedPnl")
        if v is None and isinstance(r.get("exitState"), dict):
            v = r["exitState"].get("realizedPnl")
        if v is None and isinstance(r.get("outcome"), dict):
            v = r["outcome"].get("realizedPnl")
        fv = _safe_float(v)
        if fv is not None:
            vals.append(fv)
    if not vals:
        return None
    return round(sum(vals), 2)


def _portfolio_risk_flags(
    long_rows: list[dict[str, Any]],
    short_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Daily-loss / max-concurrent stops for rotation (plan §6)."""
    all_rows = list(long_rows) + list(short_rows)
    realized = _sum_realized_pnl(all_rows)
    open_count = sum(1 for r in all_rows if _position_is_open(r))
    daily_loss_hit = (
        realized is not None and DAILY_LOSS_LIMIT_INR > 0 and realized <= -abs(DAILY_LOSS_LIMIT_INR)
    )
    max_names_hit = (
        MAX_CONCURRENT_NAMES > 0 and open_count >= MAX_CONCURRENT_NAMES
    )
    return {
        "realizedPnl": realized,
        "openCount": open_count,
        "dailyLossLimitInr": DAILY_LOSS_LIMIT_INR,
        "maxConcurrentNames": MAX_CONCURRENT_NAMES,
        "dailyLossHit": daily_loss_hit,
        "maxNamesHit": max_names_hit,
    }


def _is_closed_trade(row: dict[str, Any]) -> bool:
    """True only for an executed position that actually closed.

    `NOT_TRIGGERED` and pending rows are not trades and must never become
    re-entry candidates merely because they are not open.
    """
    if not isinstance(row, dict):
        return False
    if str(row.get("executionStatus") or "").upper() == "NOT_TRIGGERED":
        return False
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    status = str(row.get("status") or "").upper()
    return bool(
        row.get("closed")
        or outcome.get("closed")
        or status in {"CLOSED", "STOP LOSS HIT", "TRAIL STOP HIT", "SCALE COMPLETE"}
    )


def _closed_at(row: dict[str, Any]) -> datetime | None:
    """Return the first durable close timestamp as an IST-aware datetime."""
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    state = row.get("exitState") if isinstance(row.get("exitState"), dict) else {}
    for raw in (
        row.get("closedAt"),
        row.get("closed_at"),
        outcome.get("closedAt"),
        outcome.get("resolvedAt"),
        state.get("closedAt"),
    ):
        parsed = _parse_iso(str(raw)) if raw else None
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_IST)
        return parsed.astimezone(_IST)
    return None


def _economic_r(row: dict[str, Any]) -> float | None:
    """Read the booked economic R without manufacturing a value."""
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    state = row.get("exitState") if isinstance(row.get("exitState"), dict) else {}
    for source in (row, state, outcome):
        for key in ("economicR", "rMultiple"):
            value = _safe_float(source.get(key))
            if value is not None:
                return value
    return None


def _mfe_r(row: dict[str, Any]) -> float | None:
    state = row.get("exitState") if isinstance(row.get("exitState"), dict) else {}
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    for source in (row, state, outcome):
        value = _safe_float(source.get("mfeR"))
        if value is not None:
            return value
    return None


def _last_exit_leg(row: dict[str, Any]) -> dict[str, Any]:
    state = row.get("exitState") if isinstance(row.get("exitState"), dict) else {}
    legs = state.get("legsFilled") if isinstance(state.get("legsFilled"), list) else []
    for leg in reversed(legs):
        if isinstance(leg, dict):
            return leg
    return {}


def _exit_profile(row: dict[str, Any]) -> dict[str, Any]:
    """Classify a closed position for re-entry policy from booked exit facts.

    The generic session status is intentionally not enough because current
    SCALE_TRAIL rows are normalised to `CLOSED`; the booked exit leg is the
    authoritative distinction between an initial stop, trail and target exit.
    """
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    label = str(outcome.get("label") or row.get("status") or "").upper()
    leg = _last_exit_leg(row)
    leg_kind = str(leg.get("r") or "").upper()
    economic_r = _economic_r(row)
    mfe_r = _mfe_r(row)

    if leg_kind == "INITIAL_SL" or "INITIAL STOP" in label or "STOP LOSS HIT" in label:
        return {"kind": "INITIAL_STOP", "economicR": economic_r, "mfeR": mfe_r}
    if leg_kind == "TRAIL_SL" or "TRAIL STOP" in label:
        profitable = (
            economic_r is not None
            and economic_r > 0
            and mfe_r is not None
            and mfe_r >= REENTRY_MIN_TRAIL_MFE_R
        )
        return {
            "kind": "PROFIT_TRAIL" if profitable else "TRAIL_LOSS_OR_THIN",
            "economicR": economic_r,
            "mfeR": mfe_r,
        }
    if leg_kind == "EOD_SQUAREOFF" or "EOD" in label or "SESSION CLOSED" in label:
        return {"kind": "EOD_EXIT", "economicR": economic_r, "mfeR": mfe_r}
    if (
        "SCALE COMPLETE" in label
        or "TARGET 2 HIT" in label
        or "TARGET COMPLETE" in label
    ):
        return {"kind": "TARGET_COMPLETE", "economicR": economic_r, "mfeR": mfe_r}
    return {"kind": "UNKNOWN_EXIT", "economicR": economic_r, "mfeR": mfe_r}


def _exit_reference_price(row: dict[str, Any], profile: dict[str, Any]) -> float | None:
    """Price that must be reclaimed/broken before a continuation re-entry."""
    direction = str(row.get("direction") or "LONG").upper()
    entry = _safe_float(row.get("entryPrice"))
    risk = _safe_float(row.get("riskPerShare"))
    mfe_r = _safe_float(profile.get("mfeR"))
    if profile.get("kind") == "PROFIT_TRAIL" and entry and risk and mfe_r and mfe_r > 0:
        sign = -1.0 if direction == "SHORT" else 1.0
        return round(entry + sign * risk * mfe_r, 4)
    # If a future replay proves initial-stop retries are useful, a LONG must
    # first reclaim its original entry (SHORT must break back below it).  The
    # stopped price itself is not a meaningful new-setup reference.
    if profile.get("kind") == "INITIAL_STOP" and entry and entry > 0:
        return entry

    leg = _last_exit_leg(row)
    candidates: list[Any] = [
        leg.get("price"),
        row.get("target2") if profile.get("kind") == "TARGET_COMPLETE" else None,
        row.get("target1") if profile.get("kind") == "TARGET_COMPLETE" else None,
        row.get("effectiveStop"),
    ]
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    candidates.append(outcome.get("ltp"))
    for value in candidates:
        price = _safe_float(value)
        if price is not None and price > 0:
            return price
    return None


def _candidate_is_in_play(cand: dict[str, Any]) -> bool:
    """Require a current activity catalyst for a repeat trade, not stale rank."""
    if bool(cand.get("inPlay")):
        return True
    intra = cand.get("intraday") if isinstance(cand.get("intraday"), dict) else {}
    rvol, _ = _rvol_time(intra)
    if rvol is not None and rvol >= INPLAY_RVOL:
        return True
    gap_pct, _, _ = _gap_and_intraday(cand)
    atr = _safe_float(cand.get("atrPct") if cand.get("atrPct") is not None else intra.get("atr_pct"))
    return bool(
        gap_pct is not None
        and atr is not None
        and atr > 0
        and abs(gap_pct) >= INPLAY_GAP_ATR_MULT * atr
    )


def _is_reentry_row(row: dict[str, Any]) -> bool:
    source = str(row.get("source") or "").upper()
    reason = str(row.get("adoptReason") or "").upper()
    return source == "REENTRY" or reason.startswith("REENTRY_")


def _replacement_count(rows: list[dict[str, Any]]) -> int:
    """Count durable after-lock entries; event history is intentionally ignored."""
    return sum(
        1
        for row in rows
        if isinstance(row, dict)
        and (
            str(row.get("source") or "").upper() == "REPLACEMENT"
            or _is_reentry_row(row)
            or str(row.get("adoptReason") or "").upper() == "REPLACEMENT_FREE_SLOT"
        )
    )


def _is_executed_entry(row: dict[str, Any]) -> bool:
    """True when a durable book row represents an actual session entry."""
    if not isinstance(row, dict) or not row.get("symbol"):
        return False
    execution = str(row.get("executionStatus") or "").upper().strip()
    if execution in {"NOT_TRIGGERED", "PENDING_ENTRY", "CANCELLED", "REJECTED"}:
        return False
    if row.get("triggered") is False and not _is_closed_trade(row):
        return False
    return bool(
        row.get("triggered")
        or execution in {"TRIGGERED", "FILLED", "EXECUTED"}
        or _is_closed_trade(row)
        # Legacy locked rows pre-date executionStatus but are still durable
        # entries. Explicit non-execution states above always take precedence.
        or row.get("adopted")
    )


def _daily_position_count(rows: list[dict[str, Any]]) -> int:
    """Count executed session entries; each permitted re-entry counts again."""
    return sum(1 for row in rows if _is_executed_entry(row))


def _trade_logic(row: dict[str, Any]) -> str | None:
    """Return the deterministic sleeve used to generate an entry."""
    value = str(row.get("sleeve") or "").upper().strip()
    return value or None


def _reentry_decision(
    rows: list[dict[str, Any]],
    cand: dict[str, Any],
    direction: str,
    gate: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return an evidence-only decision for a potential same-symbol re-entry.

    New symbols pass through unchanged.  Re-entries are a separate strategy:
    one attempt only, after the cooldown, through a fresh price break, with
    stronger score/Expected-R requirements and lower risk sizing.
    """
    sym = str(cand.get("symbol") or "").upper().strip()
    side = str(direction or "").upper()
    base = {
        "allowed": False,
        "isReentry": False,
        "reason": "invalid_symbol_or_direction",
        "exitKind": None,
        "riskScale": 1.0,
        "previousCloseAt": None,
        "referencePrice": None,
        "sameLogicConfirmed": False,
        "priorLogic": None,
        "currentLogic": None,
    }
    if not sym or side not in {"LONG", "SHORT"}:
        return base

    symbol_rows = [
        row for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").upper().strip() == sym
    ]
    if not symbol_rows:
        return {**base, "allowed": True, "reason": "new_symbol"}
    if any(_position_is_open(row) for row in symbol_rows):
        return {**base, "reason": "symbol_already_open"}
    if any(not _is_closed_trade(row) for row in symbol_rows):
        return {**base, "reason": "prior_entry_not_a_closed_trade"}
    if any(str(row.get("direction") or "").upper() != side for row in symbol_rows):
        return {**base, "reason": "opposite_direction_seen_today"}
    if not REENTRY_ENABLED:
        return {**base, "reason": "reentry_disabled"}

    prior_reentries = sum(1 for row in symbol_rows if _is_reentry_row(row))
    if REENTRY_MAX_PER_SYMBOL <= 0 or prior_reentries >= REENTRY_MAX_PER_SYMBOL:
        return {**base, "reason": "symbol_reentry_limit"}

    prior = next((row for row in reversed(symbol_rows) if _is_closed_trade(row)), None)
    if prior is None:
        return {**base, "reason": "missing_closed_trade"}
    gate_state = str(gate.get("entryState") or gate.get("state") or "").upper()
    if gate_state != ENTRY_QUALIFIED:
        return {**base, "reason": "reentry_base_logic_not_qualified"}
    candidate_direction = str(cand.get("direction") or side).upper().strip()
    if candidate_direction != side:
        return {**base, "reason": "reentry_direction_logic_changed"}
    prior_logic = _trade_logic(prior)
    current_logic = _trade_logic(cand)
    logic_context = {
        "priorLogic": prior_logic,
        "currentLogic": current_logic,
    }
    if prior_logic is None or current_logic is None:
        return {**base, **logic_context, "reason": "reentry_logic_missing"}
    if prior_logic != current_logic:
        return {**base, **logic_context, "reason": "reentry_logic_changed"}
    profile = _exit_profile(prior)
    kind = str(profile.get("kind") or "UNKNOWN_EXIT")
    if kind == "TARGET_COMPLETE":
        cooldown = REENTRY_TARGET_COOLDOWN_MIN
        min_score = REENTRY_MIN_SCORE
        min_expected_r = REENTRY_MIN_EXPECTED_R
        risk_scale = REENTRY_PROFIT_RISK_SCALE
        reason = "REENTRY_AFTER_TARGET"
    elif kind == "PROFIT_TRAIL":
        cooldown = REENTRY_TRAIL_COOLDOWN_MIN
        min_score = REENTRY_MIN_SCORE
        min_expected_r = REENTRY_MIN_EXPECTED_R
        risk_scale = REENTRY_PROFIT_RISK_SCALE
        reason = "REENTRY_AFTER_PROFIT_TRAIL"
    elif kind == "INITIAL_STOP":
        if not REENTRY_ALLOW_INITIAL_STOP:
            return {**base, "reason": "initial_stop_reentry_disabled", "exitKind": kind}
        cooldown = REENTRY_INITIAL_STOP_COOLDOWN_MIN
        min_score = REENTRY_INITIAL_STOP_MIN_SCORE
        min_expected_r = REENTRY_INITIAL_STOP_MIN_EXPECTED_R
        risk_scale = REENTRY_INITIAL_STOP_RISK_SCALE
        reason = "REENTRY_AFTER_INITIAL_STOP"
    else:
        return {**base, "reason": f"exit_not_eligible:{kind.lower()}", "exitKind": kind}

    closed_at = _closed_at(prior)
    if closed_at is None:
        return {**base, "reason": "close_timestamp_missing", "exitKind": kind}
    current = now or _ist_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=_IST)
    age_minutes = (current.astimezone(_IST) - closed_at).total_seconds() / 60.0
    if age_minutes < cooldown:
        return {
            **base,
            "reason": "reentry_cooldown",
            "exitKind": kind,
            "previousCloseAt": closed_at.isoformat(),
            "cooldownRemainingMin": round(max(0.0, cooldown - age_minutes), 1),
        }

    score = _safe_float(cand.get("score"))
    if score is None or score < min_score:
        return {
            **base,
            "reason": "reentry_score_below_floor",
            "exitKind": kind,
            "previousCloseAt": closed_at.isoformat(),
        }
    expected_r = _safe_float(gate.get("qualityAdjustedExpectedR"))
    if expected_r is None or expected_r < min_expected_r:
        return {
            **base,
            "reason": "reentry_expected_r_below_floor",
            "exitKind": kind,
            "previousCloseAt": closed_at.isoformat(),
        }
    if not _candidate_is_in_play(cand):
        return {
            **base,
            "reason": "reentry_not_in_play",
            "exitKind": kind,
            "previousCloseAt": closed_at.isoformat(),
        }
    if gate.get("oiAligned") is False:
        return {
            **base,
            "reason": "reentry_oi_misaligned",
            "exitKind": kind,
            "previousCloseAt": closed_at.isoformat(),
        }

    reference = _exit_reference_price(prior, profile)
    ltp = _safe_float(cand.get("ltpRaw") or cand.get("ltp") or cand.get("entryPrice"))
    if reference is None or ltp is None or ltp <= 0:
        return {
            **base,
            "reason": "reentry_breakout_reference_missing",
            "exitKind": kind,
            "previousCloseAt": closed_at.isoformat(),
        }
    buffer = max(0.0, REENTRY_BREAKOUT_BUFFER_BPS) / 10_000.0
    fresh_break = ltp >= reference * (1.0 + buffer) if side == "LONG" else ltp <= reference * (1.0 - buffer)
    if not fresh_break:
        return {
            **base,
            "reason": "reentry_fresh_breakout_not_confirmed",
            "exitKind": kind,
            "previousCloseAt": closed_at.isoformat(),
            "referencePrice": round(reference, 4),
        }
    return {
        "allowed": True,
        "isReentry": True,
        "reason": reason,
        "exitKind": kind,
        "riskScale": max(0.0, min(1.0, risk_scale)),
        "previousCloseAt": closed_at.isoformat(),
        "referencePrice": round(reference, 4),
        "previousEconomicR": profile.get("economicR"),
        "minScore": min_score,
        "minExpectedR": min_expected_r,
        "sameLogicConfirmed": True,
        "priorLogic": prior_logic,
        "currentLogic": current_logic,
    }


def _open_sector_counts(
    long_rows: list[dict[str, Any]],
    short_rows: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in list(long_rows) + list(short_rows):
        if not _position_is_open(r):
            continue
        sec = str(r.get("sector") or _sector_of(str(r.get("symbol") or ""), r) or "OTHER")
        counts[sec] = counts.get(sec, 0) + 1
    return counts


def replacement_window_open(
    now: datetime | None = None,
    *,
    daily_loss_hit: bool = False,
    max_names_hit: bool = False,
) -> tuple[bool, str | None]:
    """Replacements allowed in desk rotation windows (see desk_clock.rotation_window_allowed).

    Returns (allowed, block_reason_or_None). After cutoff / midday pause / weekend /
    daily loss / max concurrent → blocked.
    """
    if _cutoff_passed(now):
        return False, "after_rotation"
    ok, code = can_add_replacement(
        now, daily_loss_hit=daily_loss_hit, max_names_hit=max_names_hit
    )
    if ok:
        return True, None
    return False, code


def can_add_replacement_slot(
    now: datetime | None = None,
    *,
    daily_loss_hit: bool = False,
    max_names_hit: bool = False,
) -> tuple[bool, str]:
    """Thin wrapper — prefer desk_clock.can_add_replacement for new callers."""
    if _cutoff_passed(now):
        return False, "after_rotation"
    return can_add_replacement(
        now, daily_loss_hit=daily_loss_hit, max_names_hit=max_names_hit
    )


def _position_is_open(pos: dict[str, Any]) -> bool:
    if str(pos.get("executionStatus") or "").upper() == "NOT_TRIGGERED":
        return False
    if pos.get("closed"):
        return False
    st = str(pos.get("status") or "").upper()
    if st in ("CLOSED", "STOP LOSS HIT", "TRAIL STOP HIT", "SCALE COMPLETE"):
        return False
    if st.startswith("TARGET") and "HIT" in st and pos.get("closed"):
        return False
    return True


def compute_free_slots(
    long_rows: list[dict[str, Any]],
    short_rows: list[dict[str, Any]],
    *,
    lock_size: int | None = None,
) -> dict[str, Any]:
    """Capital slots freed when positions close (CLOSED / target / scale / trail / SL)."""
    n = int(lock_size if lock_size is not None else LOCK_SIZE)
    open_l = sum(1 for r in long_rows if _position_is_open(r))
    open_s = sum(1 for r in short_rows if _position_is_open(r))
    total_free = max(0, n - open_l - open_s)
    free_l = min(total_free, max(0, MAX_LONG_POSITIONS - open_l))
    free_s = min(total_free, max(0, MAX_SHORT_POSITIONS - open_s))
    return {
        "long": free_l,
        "short": free_s,
        "total": total_free,
        "openLong": open_l,
        "openShort": open_s,
        "lockSize": n,
    }


def propose_replacements(
    session: dict[str, Any],
    quotes: dict[str, Any],
    live_map: dict[str, dict[str, Any]],
    regime: dict[str, Any] | None = None,
    *,
    hunt_pools: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Propose replacements for freed capital slots.

    During RTH, hunt_pools is the live Nifty 500 QUALIFIED set. After hours
    (or when hunt_pools is omitted) uses the morning lock pools.
    Prefer cash over weak / exhausted / stale candidates. Proposal-only — does not mutate.
    Uses entry_quality_gate (EXHAUSTED / STALE / NO_EDGE / WAIT_RETEST skipped).
    Same-symbol re-entry is permitted only through `_reentry_decision`; it is
    never a generic replacement of every closed symbol. Sector caps enforced.
    """
    regime = regime or session.get("regime") or {}
    long_rows = list(session.get("long") or [])
    short_rows = list(session.get("short") or [])
    all_rows = long_rows + short_rows
    risk = _portfolio_risk_flags(long_rows, short_rows)
    allowed, _block = replacement_window_open(
        daily_loss_hit=bool(risk["dailyLossHit"]),
        max_names_hit=bool(risk["maxNamesHit"]),
    )
    if not allowed:
        return []

    free = compute_free_slots(long_rows, short_rows)
    if free["total"] <= 0:
        return []

    replacement_capacity = min(
        max(0, MAX_DAILY_REPLACEMENTS - _replacement_count(all_rows)),
        max(0, MAX_DAILY_POSITIONS - _daily_position_count(all_rows)),
    )
    if replacement_capacity <= 0:
        return []

    current_syms: set[str] = set()
    for side in (long_rows, short_rows):
        for r in side:
            sym = str(r.get("symbol") or "").upper().strip()
            if not sym:
                continue
            if _position_is_open(r):
                current_syms.add(sym)

    try:
        swing_held = swing_locked_symbols(_ist_now().strftime("%Y-%m-%d"))
    except Exception:
        swing_held = set()

    # `replacementsApplied` is a secondary ledger.  Only block entries which
    # no longer exist in the durable position rows; normal historical rows are
    # evaluated by the explicit re-entry policy below.
    row_symbols = {
        str(row.get("symbol") or "").upper().strip()
        for row in all_rows
        if isinstance(row, dict) and row.get("symbol")
    }
    prior_applied = {
        str(item.get("symbol") or "").upper().strip()
        for item in (session.get("replacementsApplied") or [])
        if isinstance(item, dict) and item.get("symbol")
    }
    ledger_only = prior_applied - row_symbols
    exclude = current_syms | set(swing_held or set()) | ledger_only
    sector_counts = _open_sector_counts(long_rows, short_rows)
    proposals: list[dict[str, Any]] = []

    def _pool_rows(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict) and item.get("symbol"):
                out.append(item)
            elif isinstance(item, str) and item.strip():
                out.append({"symbol": item.strip().upper()})
        return out

    def _merge_live(cand: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(cand)
        # Prefer quote snapshot for gap/intraday when candidate is thin
        sym = str(cand.get("symbol") or "").upper()
        q = quotes.get(sym) if isinstance(quotes, dict) else None
        if isinstance(q, dict):
            for k in ("open", "close", "ltpRaw", "ltp", "vwap", "dayChangePct", "oi", "prev_oi"):
                if merged.get(k) is None and q.get(k) is not None:
                    merged[k] = q.get(k)
            intra = q.get("intraday") if isinstance(q.get("intraday"), dict) else None
            if intra and not isinstance(merged.get("intraday"), dict):
                merged["intraday"] = intra
        if live:
            if live.get("ltp") is not None:
                merged["ltp"] = live.get("ltp")
                merged["ltpRaw"] = live.get("ltp")
            if live.get("ltpSource"):
                merged["ltpSource"] = live.get("ltpSource")
            for k in ("dayChangePct", "pctChange", "intradayRet", "oi", "prev_oi"):
                if live.get(k) is not None and merged.get(k) is None:
                    merged[k] = live.get(k)
        return merged

    if hunt_pools is not None:
        pool_long_raw, pool_short_raw = hunt_pools
    else:
        pool_long_raw = session.get("candidatePoolLong")
        pool_short_raw = session.get("candidatePoolShort")
    side_specs = (
        ("LONG", free["long"], _pool_rows(pool_long_raw)),
        ("SHORT", free["short"], _pool_rows(pool_short_raw)),
    )
    for direction, slots, pool in side_specs:
        if slots <= 0 or not pool or len(proposals) >= replacement_capacity:
            continue
        allowed_oi = OI_LONG_OK if direction == "LONG" else OI_SHORT_OK
        ranked = sorted(
            pool,
            key=lambda r: (
                1.0
                if (
                    r.get("oiAligned") is True
                    or str(r.get("oiSetup") or "").upper() in allowed_oi
                )
                else (
                    0.0
                    if r.get("oiAligned") is False
                    or str(r.get("oiSetup") or "").upper()
                    in (OI_LONG_OK | OI_SHORT_OK | {"NEUTRAL"}) - allowed_oi
                    else 0.5
                ),
                float(r.get("qualityAdjustedExpectedR") or r.get("score") or 0.0),
                1.0 if r.get("inPlay") else 0.0,
                float(r.get("rewardRisk") or 0.0),
            ),
            reverse=True,
        )
        taken = 0
        for cand in ranked:
            if (
                taken >= min(slots, REPLACEMENT_MAX_PER_SIDE)
                or len(proposals) >= replacement_capacity
            ):
                break
            sym = str(cand.get("symbol") or "").upper().strip()
            if not sym or sym in exclude:
                continue
            sector = str(cand.get("sector") or _sector_of(sym, cand) or "OTHER")
            if sector_counts.get(sector, 0) >= MAX_PER_SECTOR:
                continue
            live = live_map.get(sym) if live_map else None
            merged = _merge_live(cand, live)
            if direction == "LONG" and swing_prefers_over_intraday(sym, merged):
                continue
            gate = entry_quality_gate(
                merged, direction, quotes=quotes, live_row=live, regime=regime
            )
            state = str(gate.get("entryState") or gate.get("state") or "")
            if state in _ENTRY_HARD_REJECT or state == ENTRY_WAIT_RETEST:
                continue
            if state != ENTRY_QUALIFIED:
                continue
            score = float(cand.get("score") or 0.0)
            if score < REPLACEMENT_MIN_SCORE:
                continue
            # Prefer cash: require qualityAdjustedExpectedR when present
            q_r = gate.get("qualityAdjustedExpectedR")
            if q_r is not None and float(q_r) < ENTRY_MIN_EXPECTED_R:
                continue
            reentry = _reentry_decision(all_rows, merged, direction, gate)
            if not reentry.get("allowed"):
                continue
            ltp_val = _safe_float((live or {}).get("ltp")) if live and live.get("ltp") is not None else _safe_float(
                merged.get("ltp") or cand.get("ltp") or cand.get("entryPrice")
            )
            proposals.append(
                {
                    "symbol": sym,
                    "direction": direction,
                    "score": cand.get("score"),
                    "sector": sector,
                    "sleeve": cand.get("sleeve"),
                    "entryState": state,
                    # Existing terminal UI renders this as the proposal note;
                    # surface an approved re-entry reason without requiring a
                    # second, UI-only interpretation layer.
                    "excludeReason": (
                        gate.get("excludeReason")
                        or (reentry.get("reason") if reentry.get("isReentry") else None)
                    ),
                    "flags": gate.get("flags") or [],
                    "ltpSource": gate.get("ltpSource")
                    or merged.get("ltpSource")
                    or cand.get("ltpSource"),
                    "dayMovePct": gate.get("dayMovePct")
                    if gate.get("dayMovePct") is not None
                    else _safe_float(merged.get("intradayRet") or merged.get("dayChangePct")),
                    "qualityAdjustedExpectedR": gate.get("qualityAdjustedExpectedR"),
                    "ltp": ltp_val,
                    "rewardRisk": cand.get("rewardRisk"),
                    "inPlay": cand.get("inPlay"),
                    "oiSetup": gate.get("oiSetup") or merged.get("oiSetup") or cand.get("oiSetup"),
                    "oiAligned": gate.get("oiAligned"),
                    "replaceReason": reentry.get("reason") if reentry.get("isReentry") else "FREE_SLOT",
                    "isReentry": bool(reentry.get("isReentry")),
                    "reentryExitKind": reentry.get("exitKind"),
                    "reentryPreviousCloseAt": reentry.get("previousCloseAt"),
                    "reentryReferencePrice": reentry.get("referencePrice"),
                    "reentryRiskScale": reentry.get("riskScale"),
                    "reentryPreviousEconomicR": reentry.get("previousEconomicR"),
                    "reentrySameLogicConfirmed": reentry.get("sameLogicConfirmed"),
                    "reentryLogic": reentry.get("currentLogic"),
                    "proposalOnly": True,
                }
            )
            exclude.add(sym)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            taken += 1

    return proposals


def _closed_notional_for(rows: list[dict[str, Any]], symbol: str | None) -> float:
    """Deployed notional of the closed row that freed this slot (0 if unknown)."""
    want = str(symbol or "").upper()
    if not want:
        return 0.0
    for row in reversed(rows):
        if str(row.get("symbol") or "").upper() != want:
            continue
        if _position_is_open(row):
            continue
        return float(row.get("deployedCapital") or row.get("positionValue") or row.get("plannedCapital") or 0)
    return 0.0


def apply_replacements(
    session: dict[str, Any],
    proposals: list[dict[str, Any]],
    quotes: dict[str, Any],
    live_map: dict[str, dict[str, Any]],
    regime: dict[str, Any] | None = None,
    *,
    bypass_window: bool = False,
    hunt_pools: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Mutate session: append sized open rows for QUALIFIED free-slot proposals.

    Closed history rows stay in place. Re-runs entry_quality_gate before apply.
    Returns list of applied position dicts (also stamped on session).
    """
    if not proposals or not session.get("locked"):
        return []
    regime = regime or session.get("regime") or {}
    long_rows = list(session.get("long") or [])
    short_rows = list(session.get("short") or [])
    all_rows = long_rows + short_rows
    risk = _portfolio_risk_flags(long_rows, short_rows)
    if not bypass_window:
        allowed, _block = replacement_window_open(
            daily_loss_hit=bool(risk["dailyLossHit"]),
            max_names_hit=bool(risk["maxNamesHit"]),
        )
        if not allowed:
            return []

    free = compute_free_slots(long_rows, short_rows)
    if free["total"] <= 0:
        return []

    replacement_capacity = min(
        max(0, MAX_DAILY_REPLACEMENTS - _replacement_count(all_rows)),
        max(0, MAX_DAILY_POSITIONS - _daily_position_count(all_rows)),
    )
    if replacement_capacity <= 0:
        return []

    already_open = {
        str(r.get("symbol") or "").upper()
        for r in all_rows
        if _position_is_open(r) and r.get("symbol")
    }
    row_symbols = {
        str(r.get("symbol") or "").upper().strip()
        for r in all_rows
        if isinstance(r, dict) and r.get("symbol")
    }
    prior_applied = {
        str(x.get("symbol") or "").upper()
        for x in (session.get("replacementsApplied") or [])
        if isinstance(x, dict) and x.get("symbol")
    }
    # Do not trust a stray historical ledger item over the position book.  The
    # book itself is the source of truth for whether a same-symbol repeat can
    # enter via `_reentry_decision`.
    exclude = already_open | (prior_applied - row_symbols)
    sector_counts = _open_sector_counts(long_rows, short_rows)

    if hunt_pools is not None:
        pool_long_raw, pool_short_raw = hunt_pools
    else:
        pool_long_raw = session.get("candidatePoolLong") or []
        pool_short_raw = session.get("candidatePoolShort") or []
    pool_by_side = {
        "LONG": {
            str(c.get("symbol") or "").upper(): c
            for c in pool_long_raw
            if isinstance(c, dict) and c.get("symbol")
        },
        "SHORT": {
            str(c.get("symbol") or "").upper(): c
            for c in pool_short_raw
            if isinstance(c, dict) and c.get("symbol")
        },
    }

    def _freed_queue(rows: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for r in rows:
            if _position_is_open(r):
                continue
            if not r.get("slotFreed") and str(r.get("slotStatus") or "").upper() != "REPLACEABLE":
                # still allow CLOSED history as replace source
                if not r.get("closed") and str(r.get("status") or "").upper() not in (
                    "CLOSED",
                    "STOP LOSS HIT",
                    "TRAIL STOP HIT",
                    "SCALE COMPLETE",
                ):
                    continue
            sym = str(r.get("symbol") or "").upper()
            if sym:
                out.append(sym)
        return out

    freed_long = _freed_queue(long_rows)
    freed_short = _freed_queue(short_rows)
    used_freed: set[str] = set()

    slots_left = {"LONG": int(free["long"]), "SHORT": int(free["short"])}
    total_slots_left = min(int(free["total"]), replacement_capacity)
    open_rows = [r for r in all_rows if _position_is_open(r)]
    remaining_capital = max(
        0.0,
        INTRADAY_CAPITAL
        - sum(float(r.get("deployedCapital") or r.get("positionValue") or 0) for r in open_rows),
    )
    remaining_risk = max(
        0.0,
        INTRADAY_CAPITAL * MAX_PORTFOLIO_RISK
        - sum(float(r.get("maxLoss") or 0) for r in open_rows),
    )
    applied: list[dict[str, Any]] = []
    risk_scale_cache: dict[str, float] = {}

    for prop in proposals:
        if (
            total_slots_left <= 0
            or len(applied) >= replacement_capacity
            or remaining_capital <= 0
            or remaining_risk <= 0
        ):
            break
        if not isinstance(prop, dict):
            continue
        direction = str(prop.get("direction") or "LONG").upper()
        if direction not in ("LONG", "SHORT") or slots_left.get(direction, 0) <= 0:
            continue
        sym = str(prop.get("symbol") or "").upper().strip()
        if not sym or sym in exclude:
            continue

        pool = pool_by_side.get(direction) or {}
        cand = dict(pool.get(sym) or prop)
        cand["symbol"] = sym
        live = live_map.get(sym) if live_map else None
        q = quotes.get(sym) if isinstance(quotes, dict) else None
        if isinstance(q, dict):
            for k in ("open", "close", "ltpRaw", "ltp", "vwap", "dayChangePct", "oi", "prev_oi"):
                if cand.get(k) is None and q.get(k) is not None:
                    cand[k] = q.get(k)
        if live:
            if live.get("ltp") is not None:
                cand["ltp"] = live.get("ltp")
                cand["ltpRaw"] = live.get("ltp")
            for k in ("dayChangePct", "pctChange", "intradayRet", "oi", "prev_oi"):
                if live.get(k) is not None and cand.get(k) is None:
                    cand[k] = live.get(k)

        gate = entry_quality_gate(
            cand, direction, quotes=quotes, live_row=live, regime=regime
        )
        state = str(gate.get("entryState") or gate.get("state") or "")
        if state != ENTRY_QUALIFIED:
            continue
        score = float(cand.get("score") or prop.get("score") or 0.0)
        if score < REPLACEMENT_MIN_SCORE:
            continue
        q_r = gate.get("qualityAdjustedExpectedR")
        if q_r is not None and float(q_r) < ENTRY_MIN_EXPECTED_R:
            continue
        reentry = _reentry_decision(all_rows, cand, direction, gate)
        if not reentry.get("allowed"):
            continue

        sector = str(cand.get("sector") or _sector_of(sym, cand) or "OTHER")
        if sector_counts.get(sector, 0) >= MAX_PER_SECTOR:
            continue

        entry = float(
            cand.get("entryPrice")
            or cand.get("ltp")
            or prop.get("ltp")
            or 0
        )
        risk = float(cand.get("riskPerShare") or 0)
        if entry <= 0:
            continue
        if risk <= 0:
            levels = _build_levels(entry, float(cand.get("atrPct") or 1.5) or 1.5, direction)
            risk = float(levels.get("riskPerShare") or 0)
            cand = {**cand, **levels}
            entry = float(cand.get("entryPrice") or entry)
        if risk <= 0:
            continue

        if direction not in risk_scale_cache:
            risk_scale_cache[direction] = _regime_risk_scale(regime, direction)
        sizing_risk_scale = risk_scale_cache[direction]
        if reentry.get("isReentry"):
            sizing_risk_scale = max(
                0.40,
                min(1.0, sizing_risk_scale * float(reentry.get("riskScale") or 1.0)),
            )
        expected_r = float(gate.get("qualityAdjustedExpectedR") or 0)
        band = 0.30 if expected_r >= HIGH_CONVICTION_R else (0.20 if expected_r >= PRIORITY_EXPECTED_R else 0.10)
        freed_q = freed_long if direction == "LONG" else freed_short
        replaced_from = None
        if reentry.get("isReentry"):
            for src in freed_q:
                if src == sym and src not in used_freed:
                    replaced_from = src
                    used_freed.add(src)
                    break
        if replaced_from is None:
            for src in freed_q:
                if src not in used_freed and src != sym:
                    replaced_from = src
                    used_freed.add(src)
                    break
        src_rows = long_rows if direction == "LONG" else short_rows
        freed_notional = _closed_notional_for(src_rows, replaced_from) if replaced_from else 0.0
        slot_budget = remaining_capital / max(1, total_slots_left)
        sleeve = min(remaining_capital, slot_budget, INTRADAY_CAPITAL * band)
        if freed_notional > 0:
            sleeve = min(sleeve, freed_notional)
        if sleeve <= 0:
            if replaced_from:
                used_freed.discard(replaced_from)
            continue
        sizing = _size_position(
            entry,
            risk,
            sleeve,
            risk_scale=sizing_risk_scale,
            basket_slots=1,
        )
        qty_by_risk_cap = int(min(INTRADAY_CAPITAL * MAX_SINGLE_TRADE_RISK, remaining_risk) // risk)
        if qty_by_risk_cap >= 0:
            qty = min(int(sizing.get("approxQty") or 0), qty_by_risk_cap, int(remaining_capital // entry))
            sizing = {
                **sizing,
                "approxQty": max(0, qty),
                "deployedCapital": round(max(0, qty) * entry, 2),
                "maxLoss": round(max(0, qty) * risk, 2),
            }
        if int(sizing.get("approxQty") or 0) <= 0:
            if replaced_from:
                used_freed.discard(replaced_from)
            continue
        if float(sizing.get("deployedCapital") or 0) > remaining_capital + 0.01:
            if replaced_from:
                used_freed.discard(replaced_from)
            continue

        at = _utc_now_iso()
        is_reentry = bool(reentry.get("isReentry"))
        source = "REENTRY" if is_reentry else "REPLACEMENT"
        adopt_reason = reentry.get("reason") if is_reentry else "REPLACEMENT_FREE_SLOT"
        row = attach_exit_plan(
            {
                **cand,
                **sizing,
                "symbol": sym,
                "direction": direction,
                "sector": sector,
                "rank": len(applied) + 1,
                "status": "RUNNING",
                "closed": False,
                "slotFreed": False,
                "slotStatus": "RUNNING",
                "adopted": True,
                "adoptReason": adopt_reason,
                "source": source,
                "replacedFrom": replaced_from,
                "replacedAt": at,
                "reentryOf": sym if is_reentry else None,
                "reentryExitKind": reentry.get("exitKind") if is_reentry else None,
                "reentryPreviousCloseAt": reentry.get("previousCloseAt") if is_reentry else None,
                "reentryReferencePrice": reentry.get("referencePrice") if is_reentry else None,
                "reentryPreviousEconomicR": reentry.get("previousEconomicR") if is_reentry else None,
                "reentryRiskScale": reentry.get("riskScale") if is_reentry else None,
                "reentrySameLogicConfirmed": (
                    reentry.get("sameLogicConfirmed") if is_reentry else None
                ),
                "reentryLogic": reentry.get("currentLogic") if is_reentry else None,
                "entryState": gate.get("entryState"),
                "excludeReason": gate.get("excludeReason"),
                "qualityAdjustedExpectedR": gate.get("qualityAdjustedExpectedR"),
                "entryFlags": gate.get("flags") or [],
                "oiSetup": gate.get("oiSetup") or cand.get("oiSetup"),
                "oiAligned": gate.get("oiAligned"),
                "ltp": entry,
                "currentPrice": entry,
                "plannedCapital": float(sizing.get("deployedCapital") or 0),
                "lockObservedPrice": round(float(entry), 2),
                "triggered": True,
                "executionStatus": "TRIGGERED",
                "triggeredAt": at,
            }
        )
        if direction == "LONG":
            long_rows.append(row)
        else:
            short_rows.append(row)
        all_rows.append(row)
        exclude.add(sym)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        slots_left[direction] = slots_left[direction] - 1
        total_slots_left -= 1
        remaining_capital -= float(sizing["deployedCapital"])
        remaining_risk -= float(sizing["maxLoss"])
        applied.append(row)

    if not applied:
        return []

    session["long"] = long_rows
    session["short"] = short_rows
    session["freeSlots"] = compute_free_slots(long_rows, short_rows)
    applied_summary = [
        {
            "symbol": r.get("symbol"),
            "direction": r.get("direction"),
            "replacedFrom": r.get("replacedFrom"),
            "replacedAt": r.get("replacedAt"),
            "entryPrice": r.get("entryPrice"),
            "approxQty": r.get("approxQty"),
            "score": r.get("score"),
            "source": r.get("source"),
            "reentryExitKind": r.get("reentryExitKind"),
            "reentryPreviousCloseAt": r.get("reentryPreviousCloseAt"),
            "reentryReferencePrice": r.get("reentryReferencePrice"),
            "reentrySameLogicConfirmed": r.get("reentrySameLogicConfirmed"),
            "reentryLogic": r.get("reentryLogic"),
        }
        for r in applied
    ]
    prior_list = list(session.get("replacementsApplied") or [])
    if not isinstance(prior_list, list):
        prior_list = []
    session["replacementsApplied"] = (prior_list + applied_summary)[-50:]
    session["lastAppliedReplacementKey"] = [
        f"{a.get('symbol')}:{a.get('direction')}" for a in applied_summary
    ]
    session["lastReplacementAppliedAt"] = _utc_now_iso()
    events = list(session.get("events") or [])
    events.append(
        {
            "type": "REPLACEMENT_APPLIED",
            "at": session["lastReplacementAppliedAt"],
            "freeSlotsAfter": session["freeSlots"],
            "applied": applied_summary,
        }
    )
    for r in applied:
        events.append(
            {
                "type": "POSITION_REPLACED",
                "at": r.get("replacedAt"),
                "symbol": r.get("symbol"),
                "direction": r.get("direction"),
                "replacedFrom": r.get("replacedFrom"),
            }
        )
        if str(r.get("source") or "").upper() == "REENTRY":
            events.append(
                {
                    "type": "REENTRY_APPLIED",
                    "at": r.get("replacedAt"),
                    "symbol": r.get("symbol"),
                    "direction": r.get("direction"),
                    "exitKind": r.get("reentryExitKind"),
                    "previousCloseAt": r.get("reentryPreviousCloseAt"),
                    "referencePrice": r.get("reentryReferencePrice"),
                    "riskScale": r.get("reentryRiskScale"),
                    "sameLogicConfirmed": r.get("reentrySameLogicConfirmed"),
                    "logic": r.get("reentryLogic"),
                }
            )
    session["events"] = events[-200:]
    session["updatedAt"] = _utc_now_iso()
    try:
        sync_fixed_plan_from_session(session)
    except Exception as exc:
        log.warning("replacement plan sync failed: %s", exc)

    try:
        from .trade_outcome import emit_replacement_alerts

        emit_replacement_alerts(
            session_date=str(session.get("sessionDate") or "")[:10],
            rows=applied,
        )
    except Exception as exc:
        log.warning("replacement alerts failed: %s", exc)

    return applied


def _mark_slot_status(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        if not _position_is_open(row):
            if str(row.get("status") or "").upper() == "SESSION CLOSED":
                row["slotStatus"] = "SESSION_CLOSED"
                row["slotFreed"] = False
            else:
                # CLOSED book row; REPLACEABLE = capital slot free for rotation
                row["slotStatus"] = "REPLACEABLE"
                row["closedSlotStatus"] = "CLOSED"
                row["slotFreed"] = True
            row["profitGuardActive"] = False
            row["profitProtectedInr"] = None
        else:
            st = str(row.get("status") or "RUNNING").upper()
            if "PARTIAL" in st or (
                isinstance(row.get("exitState"), dict)
                and (row["exitState"].get("legsFilled") or [])
            ):
                row["slotStatus"] = "BOOKED"
            else:
                row["slotStatus"] = "RUNNING"
            row["slotFreed"] = False
            es = row.get("exitState") if isinstance(row.get("exitState"), dict) else None
            guard = False
            if es is not None:
                guard = profit_guard_active(es) or bool(
                    row.get("profitGuardActive")
                    or (
                        isinstance(row.get("outcome"), dict)
                        and row["outcome"].get("profitGuardActive")
                    )
                )
            row["profitGuardActive"] = guard
            # Capital-aware: protect open green ₹ when guard is on (facts from unrealizedPnl)
            unreal = _safe_float(row.get("unrealizedPnl"))
            if unreal is None and es is not None:
                unreal = _safe_float(es.get("unrealizedPnl"))
            if guard and unreal is not None and unreal > 0:
                row["profitProtectedInr"] = round(unreal, 2)
            else:
                row["profitProtectedInr"] = None
        out.append(row)
    return out


def _enrich_position(pos: dict[str, Any], quotes: dict[str, Any], live_row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Update LTP/PnL/distances; never mutate symbol or CLOSED→open."""
    out = dict(pos)
    was_closed = bool(out.get("closed") or str(out.get("status") or "").upper() == "CLOSED")

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
    out["dataStale"] = (not was_closed) and (live_stale or ltp_source in ("cached", "none"))

    # Prefer persisted / live realized for closes; MTM only while open.
    realized = None
    if live_row and live_row.get("realizedPnl") is not None:
        realized = float(live_row["realizedPnl"])
    elif out.get("realizedPnl") is not None:
        realized = float(out["realizedPnl"])
    elif isinstance(out.get("exitState"), dict) and out["exitState"].get("realizedPnl") is not None:
        realized = float(out["exitState"]["realizedPnl"])
    elif isinstance(out.get("outcome"), dict) and out["outcome"].get("pnl") is not None:
        realized = float(out["outcome"]["pnl"])

    if was_closed:
        # Closed economics are the session archive. The coalesced live-book
        # cache must not overlay a prior ghost trail / mfeR onto disk P&L.
        realized = None
        if out.get("realizedPnl") is not None:
            realized = float(out["realizedPnl"])
        elif isinstance(out.get("exitState"), dict) and out["exitState"].get("realizedPnl") is not None:
            realized = float(out["exitState"]["realizedPnl"])
        elif isinstance(out.get("outcome"), dict) and out["outcome"].get("pnl") is not None:
            realized = float(out["outcome"]["pnl"])
        out["status"] = out.get("status") if str(out.get("status") or "").upper() not in ("", "RUNNING") else "CLOSED"
        out["closed"] = True
        out["realizedPnl"] = round(realized, 2) if realized is not None else None
        out["unrealizedPnl"] = 0.0 if realized is not None else None
        out["pnlPct"] = None
        if realized is not None and entry is not None and entry > 0 and qty > 0:
            out["pnlPct"] = round((realized / (entry * qty)) * 100, 2)
        if realized is not None:
            out["totalPnl"] = round(realized, 2)
        try:
            refreshed = refresh_exit_policy(out, keep_exit_state=True)
            if refreshed.get("exitPlan"):
                out["exitPlan"] = refreshed.get("exitPlan")
            if refreshed.get("bookedExitPlan"):
                out["bookedExitPlan"] = refreshed.get("bookedExitPlan")
        except Exception:
            pass
        return out

    if ltp is not None and entry is not None and entry > 0:
        rem_qty = int(out.get("remainingQty") if out.get("remainingQty") is not None else qty)
        if live_row and live_row.get("remainingQty") is not None:
            rem_qty = int(live_row.get("remainingQty") or 0)
        if direction == "LONG":
            unreal = (ltp - entry) * rem_qty
            pnl_pct = ((ltp - entry) / entry) * 100
        else:
            unreal = (entry - ltp) * rem_qty
            pnl_pct = ((entry - ltp) / entry) * 100
        out["realizedPnl"] = round(realized, 2) if realized is not None else None
        out["unrealizedPnl"] = round(unreal, 2)
        out["pnlPct"] = round(pnl_pct, 2)
        out["remainingQty"] = rem_qty
        out["positionValue"] = round(ltp * rem_qty, 2)
        if realized is not None:
            out["totalPnl"] = round(realized + unreal, 2)
    else:
        out["unrealizedPnl"] = None
        out["pnlPct"] = None
        out["positionValue"] = None

    if live_row and live_row.get("effectiveStop") is not None:
        out["effectiveStop"] = live_row.get("effectiveStop")
    if live_row and isinstance(live_row.get("exitState"), dict):
        out["exitState"] = live_row.get("exitState")
    if out.get("approxQty"):
        try:
            attached = refresh_exit_policy(out, keep_exit_state=True)
            if attached.get("exitPlan"):
                out["exitPlan"] = attached.get("exitPlan")
            if attached.get("bookedExitPlan"):
                out["bookedExitPlan"] = attached.get("bookedExitPlan")
        except Exception:
            if live_row and isinstance(live_row.get("exitPlan"), dict):
                out["exitPlan"] = live_row.get("exitPlan")
    elif live_row and isinstance(live_row.get("exitPlan"), dict):
        out["exitPlan"] = live_row.get("exitPlan")

    def _dist_pct(level: float | None) -> float | None:
        if ltp is None or level is None or ltp == 0:
            return None
        return round(abs(level - ltp) / ltp * 100, 2)

    eff_sl = _safe_float(out.get("effectiveStop") or sl)
    out["distToSlPct"] = _dist_pct(eff_sl)
    out["distToT1Pct"] = _dist_pct(t1)
    out["distToT2Pct"] = _dist_pct(t2)

    status = "RUNNING"
    if out.get("dataStale"):
        status = "DATA STALE"
    if live_row and isinstance(live_row.get("outcome"), dict):
        hit = live_row["outcome"].get("hitLevel")
        label = str(live_row["outcome"].get("label") or "")
        if hit == "sl" or "STOP" in label.upper() or "TRAIL" in label.upper():
            status = "TRAIL STOP HIT" if live_row["outcome"].get("scaleTrail") else "STOP LOSS HIT"
            out["closed"] = True
        elif hit == "partial":
            status = label or "PARTIAL"
        elif hit == "t2":
            status = "TARGET 2 HIT"
        elif hit == "t1":
            status = "TARGET 1 HIT"
        if live_row["outcome"].get("closed"):
            out["closed"] = True
            if status == "RUNNING":
                status = "CLOSED"
    # Prefer authoritative live-prices close flags (do not re-open)
    if live_row:
        live_st = str(live_row.get("status") or "").upper()
        if live_row.get("closed") or live_st == "CLOSED":
            out["closed"] = True
            status = "CLOSED" if status == "RUNNING" else status
        elif live_st == "SESSION CLOSED":
            status = "SESSION CLOSED"
        elif live_st == "STOP LOSS HIT":
            status = "STOP LOSS HIT"
            out["closed"] = True
    # Approaching flags (attention strip) — factual distance only; session hours only
    if status == "RUNNING" and out.get("distToSlPct") is not None and out["distToSlPct"] <= 0.4:
        status = "SL APPROACHING"
    elif status == "RUNNING" and out.get("distToT1Pct") is not None and out["distToT1Pct"] <= 0.4:
        status = "TARGET APPROACHING"

    # Outside NSE RTH: open names are session-closed (close mark), not RUNNING / DATA STALE
    try:
        from .trade_outcome import _is_market_open

        session_closed = not _is_market_open()
    except Exception:
        session_closed = False
    if session_closed and status in (
        "RUNNING",
        "SL APPROACHING",
        "TARGET APPROACHING",
        "DATA STALE",
    ):
        status = "SESSION CLOSED"

    if out.get("closed"):
        status = "CLOSED" if status not in ("STOP LOSS HIT", "TARGET 1 HIT", "TARGET 2 HIT") else status
    out["status"] = status
    return out


def _schedule_stale_session_rotation(existing: dict[str, Any] | None = None) -> bool:
    """Recover a missed scheduler tick without blocking an HTTP request.

    GET remains non-blocking: it only coalesces one background call through the
    same deterministic ensure/commit path used by the desk scheduler.
    """
    global _SESSION_ROTATION_ATTEMPT_AT
    session = existing if isinstance(existing, dict) else load_session()
    today = _ist_now().strftime("%Y-%m-%d")
    session_date = str(session.get("sessionDate") or "").strip()[:10]
    stale = bool(session.get("locked") and session_date and session_date != today)
    allowed, _reason = basket_lock_allowed()
    if not stale or not allowed:
        return False
    now = time.monotonic()
    if now - _SESSION_ROTATION_ATTEMPT_AT < _SESSION_ROTATION_RETRY_SEC:
        return True
    if not _SESSION_ROTATION_LOCK.acquire(blocking=False):
        return True
    _SESSION_ROTATION_ATTEMPT_AT = now

    def _rotate() -> None:
        try:
            result = ensure_intraday_session_locked()
            if str(result.get("sessionDate") or "")[:10] == today and result.get("locked"):
                refresh_session_state()
                log.info("Recovered stale intraday session %s -> %s from read-path trigger", session_date, today)
            else:
                log.warning("Read-path intraday rotation remains pending: %s", result.get("commitError"))
        except Exception:
            log.exception("Read-path intraday rotation failed")
        finally:
            _SESSION_ROTATION_LOCK.release()

    try:
        threading.Thread(target=_rotate, name=f"intraday-rollover-{today}", daemon=True).start()
    except Exception:
        _SESSION_ROTATION_LOCK.release()
        raise
    return True


def get_session(include_live: bool = True) -> dict[str, Any]:
    """Return a non-blocking session snapshot to all concurrent UI callers.

    Read-only GET path (`persist=False`) — never writes session JSON.
    Current SCALE_TRAIL notes still attach in memory so the UI is not stuck
    on a prior 0.25R plan. Path replay stays on the scheduler persist path.
    Live quote enrichment runs outside the FastAPI request worker pool.
    """
    global _SESSION_RESPONSE_CACHE, _SESSION_RESPONSE_CACHE_AT, _SESSION_RESPONSE_REFRESHING
    if not include_live:
        return _compute_session(include_live=False)
    disk_session = load_session()
    rollover_pending = _schedule_stale_session_rotation(disk_session)

    def _with_rollover_state(payload: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(payload)
        if rollover_pending and str(out.get("sessionDate") or "")[:10] != _ist_now().strftime("%Y-%m-%d"):
            out["rotationPending"] = True
            out.setdefault("rotationError", "AUTOMATIC_ROTATION_IN_PROGRESS")
        return out
    try:
        from .trade_outcome import _is_market_open
        ttl = _SESSION_RESPONSE_OPEN_TTL if _is_market_open() else _SESSION_RESPONSE_CLOSED_TTL
    except Exception:
        ttl = _SESSION_RESPONSE_OPEN_TTL
    now = time.monotonic()
    if _SESSION_RESPONSE_CACHE is not None and now - _SESSION_RESPONSE_CACHE_AT < ttl:
        return _with_rollover_state(_SESSION_RESPONSE_CACHE)

    start_refresh = False
    started_gen = 0
    with _SESSION_RESPONSE_LOCK:
        now = time.monotonic()
        if _SESSION_RESPONSE_CACHE is not None and now - _SESSION_RESPONSE_CACHE_AT < ttl:
            return _with_rollover_state(_SESSION_RESPONSE_CACHE)
        if _SESSION_RESPONSE_CACHE is None:
            fallback = _compute_session(include_live=False, persist=False)
            fallback["dataStale"] = True
            fallback["liveRefreshPending"] = True
            _SESSION_RESPONSE_CACHE = copy.deepcopy(fallback)
            _SESSION_RESPONSE_CACHE_AT = 0.0
        if not _SESSION_RESPONSE_REFRESHING:
            _SESSION_RESPONSE_REFRESHING = True
            start_refresh = True
            started_gen = _SESSION_RESPONSE_GEN
        result = copy.deepcopy(_SESSION_RESPONSE_CACHE)
        result["liveRefreshPending"] = True

    if start_refresh:
        try:
            threading.Thread(
                target=_refresh_session_response_cache,
                args=(started_gen,),
                name="intraday-live-refresh",
                daemon=True,
            ).start()
        except Exception:
            with _SESSION_RESPONSE_LOCK:
                _SESSION_RESPONSE_REFRESHING = False
            log.exception("failed to start intraday live refresh")
    return _with_rollover_state(result)


def _refresh_session_response_cache(started_gen: int) -> None:
    """Refresh the read-only response cache outside FastAPI's worker pool."""
    global _SESSION_RESPONSE_CACHE, _SESSION_RESPONSE_CACHE_AT, _SESSION_RESPONSE_REFRESHING
    try:
        result = _compute_session(include_live=True, persist=False)
        result["liveRefreshPending"] = False
        with _SESSION_RESPONSE_LOCK:
            if started_gen != _SESSION_RESPONSE_GEN:
                return
            _SESSION_RESPONSE_CACHE = copy.deepcopy(result)
            _SESSION_RESPONSE_CACHE_AT = time.monotonic()
    except Exception:
        log.exception("intraday live refresh failed; serving persisted session")
    finally:
        with _SESSION_RESPONSE_LOCK:
            _SESSION_RESPONSE_REFRESHING = False


def refresh_session_state() -> dict[str, Any]:
    """Single-writer scheduler path for durable close/replacement transitions."""
    global _SESSION_RESPONSE_CACHE, _SESSION_RESPONSE_CACHE_AT, _SESSION_RESPONSE_GEN
    reconcile_cross_book(_ist_now().strftime("%Y-%m-%d"), persist=True)
    result = _compute_session(include_live=True, persist=True)
    with _SESSION_RESPONSE_LOCK:
        _SESSION_RESPONSE_GEN += 1
        _SESSION_RESPONSE_CACHE = copy.deepcopy(result)
        _SESSION_RESPONSE_CACHE_AT = time.monotonic()
    return result


def _compute_session(include_live: bool = True, *, persist: bool = False) -> dict[str, Any]:
    session = load_session()
    session = _ensure_current_exit_policy(session, persist=persist)
    snap = load_market_snapshot()
    try:
        from .trade_outcome import _is_market_open as _rth_open

        market_open_now = bool(_rth_open())
    except Exception:
        market_open_now = False
    if persist and market_open_now:
        snap = _maybe_refresh_live_snapshot(reason="intraday_replacement_hunt")
    elif include_live and market_open_now:
        snap = _maybe_refresh_live_snapshot(reason="intraday_session_read")
    quotes = snap.get("stockQuotes") or {}
    if market_open_now:
        regime = detect_regime(snap)
        session["regime"] = regime
    else:
        regime = session.get("regime") or detect_regime(snap)
    if persist and snap.get("updatedAt"):
        session["snapshotUpdatedAt"] = snap.get("updatedAt")
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

    # After close, reconcile the panel from the same timestamped entry evidence
    # used by EOD. This also repairs legacy sessions that treated basket lock as
    # an immediate fill at a stale planned entry.
    try:
        session_day = datetime.fromisoformat(str(session.get("sessionDate"))).date()
        from .trade_outcome import _is_market_open
        from .intraday_execution_evidence import (
            persisted_entry_evidence,
            mark_not_triggered,
            session_lock_fill_evidence,
        )

        if session.get("locked") and not _is_market_open():
            def _reconcile(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
                fixed: list[dict[str, Any]] = []
                for row in rows:
                    session_fill = session_lock_fill_evidence(row)
                    evidence = session_fill or persisted_entry_evidence(
                        row,
                        session_date=session_day,
                        committed_at=session.get("committedAt"),
                    )
                    if session_fill:
                        out = dict(row)
                        out["entryEvidence"] = evidence
                        fixed.append(out)
                        continue
                    fixed.append(row if evidence.get("triggered") else mark_not_triggered(row, evidence))
                return fixed
            long_rows = _reconcile(long_rows)
            short_rows = _reconcile(short_rows)
    except Exception as exc:
        log.debug("entry evidence reconciliation skipped: %s", exc)

    # Preserve CLOSED forever in persisted session; free capital slot on first close
    if session.get("locked"):
        changed = False
        for side_key, rows in (("long", long_rows), ("short", short_rows)):
            orig = session.get(side_key) or []
            for i, row in enumerate(rows):
                if row.get("closed") and i < len(orig) and not orig[i].get("closed"):
                    close_at = _closed_at(row)
                    close_at_iso = close_at.isoformat() if close_at is not None else _utc_now_iso()
                    exit_kind = _exit_profile(row).get("kind")
                    keep = {
                        k: row.get(k)
                        for k in (
                            "ltp",
                            "ltpSource",
                            "realizedPnl",
                            "unrealizedPnl",
                            "pnlPct",
                            "totalPnl",
                            "exitState",
                            "outcome",
                            "effectiveStop",
                            "remainingQty",
                            "exitPlan",
                            "scaleProgress",
                            "economicR",
                            "rMultiple",
                            "closedAt",
                            "exitKind",
                        )
                        if row.get(k) is not None
                    }
                    orig[i] = {
                        **orig[i],
                        **keep,
                        "closed": True,
                        "status": "CLOSED",
                        "closedAt": close_at_iso,
                        "exitKind": exit_kind,
                        "slotFreed": True,
                        "slotStatus": "REPLACEABLE",
                    }
                    changed = True
                    events = list(session.get("events") or [])
                    events.append({
                        "type": "POSITION_CLOSED",
                        "at": _utc_now_iso(),
                        "symbol": row.get("symbol"),
                        "direction": row.get("direction"),
                        "slotFreed": True,
                        "closedAt": close_at_iso,
                        "exitKind": exit_kind,
                    })
                    session["events"] = events[-200:]
        if changed:
            session["long"] = [
                {
                    **o,
                    "closed": True,
                    "status": "CLOSED",
                    "slotFreed": True,
                    "slotStatus": "REPLACEABLE",
                }
                if (i < len(long_rows) and long_rows[i].get("closed"))
                else o
                for i, o in enumerate(session.get("long") or [])
            ]
            session["short"] = [
                {
                    **o,
                    "closed": True,
                    "status": "CLOSED",
                    "slotFreed": True,
                    "slotStatus": "REPLACEABLE",
                }
                if (i < len(short_rows) and short_rows[i].get("closed"))
                else o
                for i, o in enumerate(session.get("short") or [])
            ]
            free_now = compute_free_slots(session.get("long") or [], session.get("short") or [])
            session["freeSlots"] = free_now
            events = list(session.get("events") or [])
            events.append({
                "type": "CAPITAL_SLOT_FREED",
                "at": _utc_now_iso(),
                "freeSlots": free_now,
            })
            session["events"] = events[-200:]
            session["updatedAt"] = _utc_now_iso()
            if persist:
                save_session(session)

    long_rows = _mark_slot_status(long_rows)
    short_rows = _mark_slot_status(short_rows)

    def _sum_pnl(rows: list[dict[str, Any]]) -> float | None:
        vals = [
            r.get("unrealizedPnl")
            for r in rows
            if r.get("unrealizedPnl") is not None and _position_is_open(r)
        ]
        if not vals:
            return None
        return round(sum(float(v) for v in vals), 2)

    open_long = [r for r in long_rows if _position_is_open(r)]
    open_short = [r for r in short_rows if _position_is_open(r)]
    long_exposure = round(sum(float(r.get("positionValue") or r.get("deployedCapital") or 0) for r in open_long), 2)
    short_exposure = round(sum(float(r.get("positionValue") or r.get("deployedCapital") or 0) for r in open_short), 2)
    u_pnl_l = _sum_pnl(long_rows)
    u_pnl_s = _sum_pnl(short_rows)
    unrealized = None if u_pnl_l is None and u_pnl_s is None else round((u_pnl_l or 0) + (u_pnl_s or 0), 2)

    free_slots = compute_free_slots(long_rows, short_rows)
    risk_flags = _portfolio_risk_flags(long_rows, short_rows)
    realized_book = risk_flags.get("realizedPnl")
    replacements_used = _replacement_count(long_rows + short_rows)
    replacements_remaining = max(0, MAX_DAILY_REPLACEMENTS - replacements_used)
    daily_positions_used = _daily_position_count(long_rows + short_rows)
    daily_positions_remaining = max(0, MAX_DAILY_POSITIONS - daily_positions_used)
    replacement_blocked_reason: str | None = None
    replacement_candidates: list[dict[str, Any]] = []
    cash_held = False
    hunt_pools: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None
    replacement_hunt_source = "lock_pool"
    rot_ok, rot_code = rotation_window_allowed()
    rot_cfg = rotation_window_config()
    if not session.get("locked"):
        replacement_blocked_reason = "session_not_locked"
    else:
        allowed, win_reason = replacement_window_open(
            daily_loss_hit=bool(risk_flags["dailyLossHit"]),
            max_names_hit=bool(risk_flags["maxNamesHit"]),
        )
        if not allowed:
            replacement_blocked_reason = win_reason or rot_code
        elif free_slots["total"] <= 0:
            replacement_blocked_reason = "no_free_slots"
        elif daily_positions_remaining <= 0:
            replacement_blocked_reason = "daily_position_cap"
            cash_held = True
        elif replacements_remaining <= 0:
            replacement_blocked_reason = "daily_replacement_cap"
            cash_held = True
        elif market_open_now:
            try:
                long_p, short_p, replacement_hunt_source = _replacement_source_pools(
                    {**session, "long": long_rows, "short": short_rows},
                    snap,
                )
                hunt_pools = (long_p, short_p)
            except Exception as exc:
                log.warning("replacement hunt pools failed: %s", exc)
                hunt_pools = None
                replacement_hunt_source = "lock_pool_error"
            try:
                replacement_candidates = propose_replacements(
                    {
                        **session,
                        "long": long_rows,
                        "short": short_rows,
                    },
                    quotes,
                    live_map,
                    regime,
                    hunt_pools=hunt_pools,
                )
                for c in replacement_candidates:
                    c["huntSource"] = replacement_hunt_source
                    if not persist:
                        c["proposalOnly"] = True
                if not replacement_candidates:
                    replacement_blocked_reason = "prefer_cash_no_qualified"
                    cash_held = True
            except Exception as exc:
                log.warning("replacement propose failed: %s", exc)
                replacement_blocked_reason = "propose_error"

    replacements_applied: list[dict[str, Any]] = []
    if (
        session.get("locked")
        and replacement_candidates
        and free_slots.get("total", 0) > 0
        and not cash_held
        and persist
    ):
        try:
            applied_rows = apply_replacements(
                session,
                replacement_candidates,
                quotes,
                live_map,
                regime,
                hunt_pools=hunt_pools,
            )
            if applied_rows:
                save_session(session)
                long_rows = _mark_slot_status(list(session.get("long") or []))
                short_rows = _mark_slot_status(list(session.get("short") or []))
                open_long = [r for r in long_rows if _position_is_open(r)]
                open_short = [r for r in short_rows if _position_is_open(r)]
                long_exposure = round(
                    sum(float(r.get("positionValue") or r.get("deployedCapital") or 0) for r in open_long),
                    2,
                )
                short_exposure = round(
                    sum(float(r.get("positionValue") or r.get("deployedCapital") or 0) for r in open_short),
                    2,
                )
                free_slots = compute_free_slots(long_rows, short_rows)
                risk_flags = _portfolio_risk_flags(long_rows, short_rows)
                realized_book = risk_flags.get("realizedPnl")
                replacements_used = _replacement_count(long_rows + short_rows)
                replacements_remaining = max(0, MAX_DAILY_REPLACEMENTS - replacements_used)
                daily_positions_used = _daily_position_count(long_rows + short_rows)
                daily_positions_remaining = max(0, MAX_DAILY_POSITIONS - daily_positions_used)
                replacements_applied = list(session.get("replacementsApplied") or [])[-len(applied_rows) :]
                # Mark just-applied proposals for UI (no longer proposal-only)
                applied_syms = {
                    f"{str(r.get('symbol') or '').upper()}:{str(r.get('direction') or '').upper()}"
                    for r in applied_rows
                }
                for c in replacement_candidates:
                    key = f"{str(c.get('symbol') or '').upper()}:{str(c.get('direction') or '').upper()}"
                    if key in applied_syms:
                        c["proposalOnly"] = False
                        c["applied"] = True
                replacement_blocked_reason = None
        except Exception as exc:
            log.warning("replacement apply failed: %s", exc)

    # Persist proposal / cash-held ledger for EOD attribution (dedupe by symbol set)
    if persist and session.get("locked") and (
        replacement_candidates
        or replacement_blocked_reason in {
            "prefer_cash_no_qualified",
            "daily_replacement_cap",
            "daily_position_cap",
        }
    ):
        try:
            cand_key = tuple(
                sorted(
                    f"{c.get('symbol')}:{c.get('direction')}"
                    for c in replacement_candidates
                    if c.get("symbol")
                )
            )
            prev_key = tuple(session.get("lastReplacementKey") or ())
            if cand_key != prev_key or (
                cash_held and session.get("lastCashHeldAt") is None
            ):
                events = list(session.get("events") or [])
                if replacement_candidates:
                    events.append(
                        {
                            "type": "REPLACEMENT_PROPOSED",
                            "at": _utc_now_iso(),
                            "freeSlots": free_slots,
                            "candidates": [
                                {
                                    "symbol": c.get("symbol"),
                                    "direction": c.get("direction"),
                                    "entryState": c.get("entryState"),
                                    "score": c.get("score"),
                                    "oiSetup": c.get("oiSetup"),
                                    "qualityAdjustedExpectedR": c.get(
                                        "qualityAdjustedExpectedR"
                                    ),
                                    "huntSource": c.get("huntSource"),
                                    "proposalOnly": True,
                                }
                                for c in replacement_candidates
                            ],
                        }
                    )
                if cash_held:
                    events.append(
                        {
                            "type": "CASH_HELD",
                            "at": _utc_now_iso(),
                            "freeSlots": free_slots,
                            "reason": replacement_blocked_reason,
                        }
                    )
                    session["lastCashHeldAt"] = _utc_now_iso()
                session["lastReplacementKey"] = list(cand_key)
                session["lastReplacementProposals"] = replacement_candidates
                session["events"] = events[-200:]
                session["updatedAt"] = _utc_now_iso()
                save_session(session)
        except Exception as exc:
            log.debug("replacement ledger skip: %s", exc)

    attention: list[dict[str, Any]] = []
    for r in long_rows + short_rows:
        st = str(r.get("status") or "")
        if st in (
            "SL APPROACHING",
            "TARGET APPROACHING",
            "DATA STALE",
            "STOP LOSS HIT",
            "TARGET 1 HIT",
            "TARGET 2 HIT",
            "SESSION CLOSED",
            "TRAIL STOP HIT",
        ):
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
    try:
        from .trade_outcome import _is_market_open

        market_open = _is_market_open()
    except Exception:
        market_open = live_meta.get("marketOpen")
    # Desk: sessionClosed means "not in RTH" (overnight + weekends), not only post-15:30
    session_closed = (market_open is False) if market_open is not None else live_meta.get("sessionClosed")
    live_meta["marketOpen"] = market_open
    live_meta["sessionClosed"] = session_closed

    # Freeze last LTP + SESSION CLOSED onto disk once per closed session.
    # Skip when already frozen — concurrent GET polls must not fight over the file.
    if persist and session.get("locked") and market_open is False and not session.get("closeMarksFrozenAt"):
        if _CLOSE_FREEZE_LOCK.acquire(blocking=False):
            try:
                # Re-check under lock (another request may have just frozen)
                latest = load_session()
                if latest.get("closeMarksFrozenAt"):
                    session["closeMarksFrozenAt"] = latest.get("closeMarksFrozenAt")
                else:
                    frozen_changed = False
                    for side_key, rows in (("long", long_rows), ("short", short_rows)):
                        orig = list(session.get(side_key) or [])
                        for i, row in enumerate(rows):
                            if i >= len(orig):
                                break
                            patch: dict[str, Any] = {}
                            if row.get("ltp") is not None and orig[i].get("ltp") != row.get("ltp"):
                                patch["ltp"] = row.get("ltp")
                                patch["currentPrice"] = row.get("ltp")
                                patch["ltpSource"] = row.get("ltpSource") or orig[i].get("ltpSource")
                            st = str(row.get("status") or "")
                            if st and st != "RUNNING" and orig[i].get("status") != st:
                                patch["status"] = st
                            if row.get("unrealizedPnl") is not None:
                                patch["unrealizedPnl"] = row.get("unrealizedPnl")
                            if row.get("pnlPct") is not None:
                                patch["pnlPct"] = row.get("pnlPct")
                            if patch:
                                orig[i] = {**orig[i], **patch}
                                frozen_changed = True
                        session[side_key] = orig
                    # Always stamp so subsequent polls skip write even if prices unchanged
                    session["closeMarksFrozenAt"] = _utc_now_iso()
                    session["updatedAt"] = session["closeMarksFrozenAt"]
                    save_session(session)
            except Exception as exc:
                log.warning("close-mark freeze failed: %s", exc)
            finally:
                _CLOSE_FREEZE_LOCK.release()

    if persist:
        _persist_if_close_transition(session, long_rows, short_rows)

    return {
        "success": True,
        "locked": bool(session.get("locked")),
        "sessionDate": session.get("sessionDate"),
        "committedAt": session.get("committedAt"),
        "updatedAt": live_meta.get("updatedAt") or session.get("updatedAt") or _utc_now_iso(),
        "snapshotUpdatedAt": (
            snap.get("updatedAt")
            if market_open
            else (live_meta.get("snapshotUpdatedAt") or session.get("snapshotUpdatedAt") or snap.get("updatedAt"))
        ),
        "marketOpen": market_open,
        "sessionClosed": session_closed,
        "closeMarksFrozenAt": session.get("closeMarksFrozenAt"),
        "dataStale": live_meta.get("dataStale") if "dataStale" in live_meta else session.get("dataStale"),
        "ltpSourceMix": live_meta.get("ltpSourceMix"),
        "priceSourcesNote": live_meta.get("priceSourcesNote"),
        "feedStatus": feed_status,
        "executionPolicy": "MANUAL_ONLY",
        "regime": regime,
        "capital": capital,
        "freeSlots": free_slots,
        "replacementCandidates": replacement_candidates,
        "replacementsApplied": session.get("replacementsApplied") or replacements_applied,
        "lastReplacementAppliedAt": session.get("lastReplacementAppliedAt"),
        "replacementBlockedReason": replacement_blocked_reason,
        "replacementHuntSource": replacement_hunt_source,
        "replacementCutoffIst": (
            f"{_hhmm_to_minutes(REPLACEMENT_CUTOFF_HHMM) // 60:02d}:"
            f"{_hhmm_to_minutes(REPLACEMENT_CUTOFF_HHMM) % 60:02d}"
        ),
        "replacementBudget": {
            "used": replacements_used,
            "limit": MAX_DAILY_REPLACEMENTS,
            "remaining": replacements_remaining,
        },
        "dailyPositionBudget": {
            "used": daily_positions_used,
            "limit": MAX_DAILY_POSITIONS,
            "remaining": daily_positions_remaining,
            "includesReentries": True,
        },
        "reentryPolicy": {
            "enabled": REENTRY_ENABLED,
            "maxPerSymbol": REENTRY_MAX_PER_SYMBOL,
            "targetCooldownMin": REENTRY_TARGET_COOLDOWN_MIN,
            "profitTrailCooldownMin": REENTRY_TRAIL_COOLDOWN_MIN,
            "initialStopEnabled": REENTRY_ALLOW_INITIAL_STOP,
            "initialStopCooldownMin": REENTRY_INITIAL_STOP_COOLDOWN_MIN,
            "minScore": REENTRY_MIN_SCORE,
            "minExpectedR": REENTRY_MIN_EXPECTED_R,
            "breakoutBufferBps": REENTRY_BREAKOUT_BUFFER_BPS,
            "profitRiskScale": REENTRY_PROFIT_RISK_SCALE,
            "sameLogicRequired": True,
        },
        "cashHeld": cash_held,
        "portfolioRisk": risk_flags,
        "rotationWindow": rot_cfg,
        "rotationWindowCode": rot_code,
        "rotationWindowOpen": bool(rot_ok),
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
            "realizedPnl": realized_book,
            "freeSlots": free_slots,
            "dailyLossLimitInr": DAILY_LOSS_LIMIT_INR,
            "maxConcurrentNames": MAX_CONCURRENT_NAMES,
            "replacementBudget": {
                "used": replacements_used,
                "limit": MAX_DAILY_REPLACEMENTS,
                "remaining": replacements_remaining,
            },
            "dailyPositionBudget": {
                "used": daily_positions_used,
                "limit": MAX_DAILY_POSITIONS,
                "remaining": daily_positions_remaining,
                "includesReentries": True,
            },
            "dailyLossHit": bool(risk_flags.get("dailyLossHit")),
            "maxNamesHit": bool(risk_flags.get("maxNamesHit")),
            "cashHeld": cash_held or bool(long_rows or short_rows) and all(
                str(r.get("executionStatus") or "").upper() == "NOT_TRIGGERED"
                for r in long_rows + short_rows
            ),
        },
        "attention": attention,
        "long": long_rows,
        "short": short_rows,
        "events": session.get("events") or [],
        "newAlerts": live_meta.get("newAlerts") or [],
        "funnel": session.get("funnel"),
    }
