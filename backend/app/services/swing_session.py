"""Durable, fail-closed swing portfolio lock for EOD / Book P&L.

Only rows carrying an explicit deterministic BUY/LONG side plus complete bullish
filter evidence can enter this book.  Risk-audit APPROVE is a veto pass only; it
never supplies direction.  Intraday long/short stay in intradAy_session.json.
Once locked for the IST day: symbols immutable; prices update only.
"""
from __future__ import annotations

import json
import copy
import logging
import os
import threading
import time
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .feed_scanner import SWING_MIN_PRICE, is_swing_desk_eligible
from .exit_plan import attach_exit_plan, cap_stop_risk, evaluate_scale_trail, refresh_exit_policy
from .swing_prefilter import load_prefilter_symbols
from .trade_outcome import _is_market_open
from .desk_clock import (
    swing_entry_hunt_allowed,
    swing_entry_hunt_block_message,
    swing_entry_hunt_config,
)
from .desk_book_symbols import filter_rows_excluding, intraday_locked_symbols
from .stock_quality import (
    MAX_DAY_MOVE_PCT,
    MAX_WICK_NOISE_RATIO,
    MIN_EMA_ANGLE_DEG,
    MIN_RSI_PIVOT,
    MIN_TURNOVER_CR,
    MIN_VOLUME_MULTIPLIER,
    day_change_pct_from_row,
    evaluate_short_term_quality,
    oi_setup_allows_buy,
    pace_volume_multiplier,
)

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_SERVICES_DIR)
_BACKEND_DIR = os.path.dirname(_APP_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

_SWING_SESSION_PATH = os.environ.get(
    "SWING_SESSION_FILE",
    os.path.join(_REPO_ROOT, "swing_session.json"),
)
def _matrix_snapshot_path() -> str:
    from .market_snapshot_store import readable_market_snapshot_path

    return str(readable_market_snapshot_path())
_EOD_DATA_DIR = os.path.join(_APP_DIR, "data", "eod")

SWING_CAPITAL = float(os.environ.get("SWING_CAPITAL", "1000000"))  # ₹10L sleeve
SWING_RISK_FRACTION = float(os.environ.get("SWING_RISK_FRACTION", "0.01"))
SWING_MATRIX_LOCK_COUNT = min(5, max(1, int(os.environ.get("MAX_SWING_POSITIONS", os.environ.get("SWING_MATRIX_LOCK_COUNT", "5")))))
# Desk ATR% band when stock has no atr_pct / explicit levels (documented on row)
SWING_DEFAULT_ATR_PCT = float(os.environ.get("SWING_DEFAULT_ATR_PCT", "2.0"))
SWING_T1_R = float(os.environ.get("SWING_T1_R", "1.5"))
SWING_T2_R = float(os.environ.get("SWING_T2_R", "3.0"))
SWING_MIN_EXPECTED_R = float(os.environ.get("SWING_MIN_EXPECTED_R", "1.50"))
SWING_PRIORITY_R = float(os.environ.get("SWING_PRIORITY_R", "2.00"))
SWING_MAX_SINGLE_RISK = float(os.environ.get("SWING_MAX_SINGLE_TRADE_RISK", "0.01"))
SWING_MAX_PORTFOLIO_RISK = float(os.environ.get("SWING_MAX_PORTFOLIO_RISK", "0.05"))
SWING_SELECTION_CONTRACT = "DETERMINISTIC_BUY_V1"
_BULLISH_SIDES = frozenset({"BUY", "LONG"})
_RISK_APPROVALS = frozenset({"APPROVE", "APPROVED", "PASS", "PASSED", "CLEAR"})
# Veto-only: missing / HOLD_FOR_DATA never supply direction and must not block a
# quant BUY. LLM audits top 10 only; requiring APPROVE would make the volume-500
# hunt unusable.
_RISK_VETOES = frozenset({
    "REJECT",
    "REJECTED",
    "HOLD",
    "SELL",
    "SHORT",
    "AVOID",
})
_SWING_RESPONSE_LOCK = threading.Lock()
_SWING_RESPONSE_CACHE: dict[str, Any] | None = None
_SWING_RESPONSE_CACHE_AT = 0.0
_SWING_RESPONSE_REFRESHING = False
_SWING_RESPONSE_GEN = 0
_SWING_RESPONSE_OPEN_TTL = float(os.environ.get("SWING_RESPONSE_OPEN_TTL", "4"))
_SWING_RESPONSE_CLOSED_TTL = float(os.environ.get("SWING_RESPONSE_CLOSED_TTL", "20"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ist_today() -> str:
    return datetime.now(tz=IST).strftime("%Y-%m-%d")


def _invalidate_swing_response_cache() -> None:
    """Drop the coalesced GET snapshot and retire in-flight live refresh writes."""
    global _SWING_RESPONSE_CACHE, _SWING_RESPONSE_CACHE_AT, _SWING_RESPONSE_GEN
    with _SWING_RESPONSE_LOCK:
        _SWING_RESPONSE_GEN += 1
        _SWING_RESPONSE_CACHE = None
        _SWING_RESPONSE_CACHE_AT = 0.0


def _atomic_write(path: str, payload: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
    _invalidate_swing_response_cache()


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_swing_session() -> dict[str, Any]:
    return _read_json(_SWING_SESSION_PATH)


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _size_swing_row(
    row: dict[str, Any],
    *,
    sleeve: float,
    slots: int,
    force: bool = False,
) -> dict[str, Any]:
    """Risk + notional size for one swing name (same idea as intradAy desk)."""
    entry = _f(row.get("entryPrice")) or 0.0
    risk = _f(row.get("riskPerShare"))
    if risk is None or risk <= 0:
        stop = _f(row.get("stopLoss"))
        risk = abs(entry - stop) if stop is not None else entry * 0.02
    if entry <= 0 or risk <= 0 or sleeve <= 0:
        return {**row, "approxQty": 0, "deployedCapital": 0.0}

    existing_qty = int(row.get("approxQty") or 0)
    existing_dep = _f(row.get("deployedCapital")) or 0.0
    slots = max(1, slots)
    target_notional = sleeve / slots
    # Keep prior size only if already sized for this sleeve (±15%)
    if (
        not force
        and existing_qty > 0
        and existing_dep > 0
        and abs(existing_dep - target_notional) / max(target_notional, 1.0) <= 0.15
    ):
        return row

    risk_budget = sleeve * min(SWING_RISK_FRACTION, SWING_MAX_SINGLE_RISK)
    qty_by_risk = int(risk_budget // risk)
    qty_by_notional = int(target_notional // entry)
    qty = max(0, min(qty_by_risk, qty_by_notional))
    if qty <= 0 and entry <= target_notional:
        qty = 1
    deployed = round(qty * entry, 2)
    return {
        **row,
        "approxQty": qty,
        "deployedCapital": deployed,
        "maxLoss": round(qty * risk, 2),
        "sizingNote": "SWING_SLEEVE_10L",
        "sleeveCapital": sleeve,
        "slotNotional": round(target_notional, 2),
    }


def apply_swing_sizing(
    session: dict[str, Any] | None = None,
    *,
    persist: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Fill approxQty/deployedCapital for ₹10L swing sleeve (fixes Book ₹0 / re-size)."""
    sess = dict(session or load_swing_session())
    long_rows = [r for r in (sess.get("long") or []) if isinstance(r, dict)]
    short_rows = [r for r in (sess.get("short") or []) if isinstance(r, dict)]
    if not long_rows and not short_rows:
        return sess

    prev_cap = _f((sess.get("capital") or {}).get("swingCapital"))
    must_force = force or (prev_cap is not None and abs(prev_cap - SWING_CAPITAL) > 1.0)

    slots = max(1, len(long_rows) + len(short_rows))
    sized_long = [
        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=slots, force=must_force))
        for r in long_rows
    ]
    sized_short = [
        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=slots, force=must_force))
        for r in short_rows
    ]
    changed = sized_long != long_rows or sized_short != short_rows or must_force
    sess["long"] = sized_long
    sess["short"] = sized_short
    sess["capital"] = {
        "swingCapital": SWING_CAPITAL,
        "riskFraction": SWING_RISK_FRACTION,
        "slots": slots,
        "perSlotNotional": round(SWING_CAPITAL / slots, 2),
    }
    if changed:
        sess["updatedAt"] = _utc_now_iso()
        if persist and sess.get("locked"):
            _atomic_write(_SWING_SESSION_PATH, sess)
            log.info(
                "Swing sizing applied: %d names · capital=%.0f · force=%s",
                slots,
                SWING_CAPITAL,
                must_force,
            )
    return sess


def _parse_price(v: Any) -> float | None:
    """Parse float LTP — accepts raw number or ₹1,234.50 strings."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None
    text = str(v).strip()
    if not text:
        return None
    cleaned = re.sub(r"[₹,\s]", "", text)
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    try:
        f = float(cleaned)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _selection_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = row.get("selectionEvidence")
    intraday = row.get("intraday")
    return [
        row,
        evidence if isinstance(evidence, dict) else {},
        intraday if isinstance(intraday, dict) else {},
    ]


def _selection_value(row: dict[str, Any], *keys: str) -> Any:
    for source in _selection_sources(row):
        for key in keys:
            if key in source and source.get(key) is not None:
                return source.get(key)
    return None


def _selection_bool(row: dict[str, Any], *keys: str) -> bool | None:
    value = _selection_value(row, *keys)
    return value if isinstance(value, bool) else None


def _explicit_deterministic_side(row: dict[str, Any]) -> tuple[str, str | None]:
    """Return the explicit quant/scanner side and the field that supplied it.

    ``action`` is deliberately excluded: ledger/LLM action text is not a
    deterministic direction source.
    """
    side_keys = (
        "deterministicSide",
        "deterministic_side",
        "signalSide",
        "signal_side",
        "tradeSide",
        "trade_side",
        "side",
        "direction",
        "originalSide",
    )
    for source in _selection_sources(row):
        for key in side_keys:
            value = source.get(key)
            if value not in (None, ""):
                return str(value).upper().strip(), key
    return "", None


def _risk_audit_values(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("riskAuditVerdict", "risk_audit_verdict", "verdict"):
        value = _selection_value(row, key)
        normalized = str(value or "").upper().strip()
        if normalized and normalized not in values:
            values.append(normalized)
    desk_ic = row.get("deskIcSummary")
    if isinstance(desk_ic, dict):
        decision = str(desk_ic.get("deskDecision") or "").upper().strip()
        if decision and decision not in values:
            values.append(decision)
    return values


def _hydrate_swing_contract_row(row: dict[str, Any]) -> dict[str, Any]:
    """Recompute quality/hard/BUY from live metrics. Ignore stale snapshot flags.

    Does not invent BUY from score/APPROVE. Side is set only when hard filters
    can be fully recomputed from metrics.
    """
    out = dict(row)
    intra = dict(out["intraday"]) if isinstance(out.get("intraday"), dict) else {}
    ltp = _parse_price(out.get("ltpRaw") or out.get("ltp") or intra.get("ltp"))
    atr = _f(intra.get("atr_pct") or out.get("atr_pct"))
    turnover = _f(intra.get("turnover_cr") or out.get("turnover_cr"))
    vwap = _f(intra.get("vwap") or out.get("vwap"))
    ema9 = _f(intra.get("ema9") or out.get("ema9"))
    rsi = _f(intra.get("rsi") or out.get("rsi"))
    vol = _f(intra.get("volume_multiplier") or out.get("volume_multiplier"))
    spread = _f(intra.get("spread_pct") or out.get("spread_pct"))
    if spread is None:
        spread = 0.0
    wick = _f(intra.get("wick_noise_ratio") or out.get("wick_noise_ratio"))
    ema_angle = _f(intra.get("ema_angle_deg") or out.get("ema_angle_deg")) or 0.0
    day_move = day_change_pct_from_row(out)
    oi_setup = str(intra.get("oi_setup") or out.get("oi_setup") or "").upper().strip()
    oi_val = _f(intra.get("oi") if intra.get("oi") is not None else out.get("oi")) or 0.0
    prev_oi = _f(intra.get("prev_oi") if intra.get("prev_oi") is not None else out.get("prev_oi")) or 0.0
    if intra.get("oi") is None and out.get("oi") is not None:
        intra["oi"] = out.get("oi")
    if intra.get("prev_oi") is None and out.get("prev_oi") is not None:
        intra["prev_oi"] = out.get("prev_oi")
    if not intra.get("volume_pace_adjusted"):
        today_vol = _f(intra.get("today_volume") or out.get("today_volume"))
        avg_vol = _f(intra.get("avg_daily_volume_20") or out.get("avg_daily_volume_20"))
        if today_vol is not None and avg_vol is not None and avg_vol > 0:
            vol = pace_volume_multiplier(today_vol, avg_vol)
            intra["volume_multiplier"] = vol
            intra["volume_pace_adjusted"] = True
    above_vwap = intra.get("price_above_vwap")
    if not isinstance(above_vwap, bool) and ltp is not None and vwap is not None:
        above_vwap = ltp > vwap
        intra["price_above_vwap"] = above_vwap
    above_ema9 = intra.get("price_above_ema9")
    if not isinstance(above_ema9, bool) and ltp is not None and ema9 is not None:
        above_ema9 = ltp > ema9
        intra["price_above_ema9"] = above_ema9
    pivot = intra.get("pivot_r1_breakout")
    promoter = _f(intra.get("promoter_holding_pct") or out.get("promoter_holding_pct"))
    symbol = str(out.get("symbol") or out.get("ticker") or "").upper().strip()
    if day_move is not None:
        intra.setdefault("day_change_pct", day_move)
    can_recompute = all(
        v is not None for v in (atr, turnover, vwap, ltp, rsi, vol, wick, above_ema9, pivot)
    )
    if can_recompute:
        quality_ok, quality_reasons = evaluate_short_term_quality(symbol or "UNKNOWN", intra, promoter)
        intra["passes_quality_filters"] = quality_ok
        intra["quality_filter_reasons"] = quality_reasons
        out["passes_quality_filters"] = quality_ok
        hard = all((
            atr > 1.5,
            turnover >= MIN_TURNOVER_CR,
            ltp > vwap,
            oi_setup_allows_buy(oi_setup, oi=oi_val, prev_oi=prev_oi),
            vol >= MIN_VOLUME_MULTIPLIER,
            rsi >= MIN_RSI_PIVOT,
            spread < 0.50,
            wick <= MAX_WICK_NOISE_RATIO,
            ema_angle > MIN_EMA_ANGLE_DEG,
            above_ema9 is True,
            pivot is True,
            quality_ok is True,
            day_move is None or day_move <= MAX_DAY_MOVE_PCT,
        ))
        out["passes_hard_filters"] = hard
        intra["passes_hard_filters"] = hard
        side, _src = _explicit_deterministic_side(out)
        if hard and not side:
            out["deterministicSide"] = "BUY"
    elif out.get("passes_quality_filters") is None:
        quality = intra.get("passes_quality_filters")
        if isinstance(quality, bool):
            out["passes_quality_filters"] = quality
    if intra:
        out["intraday"] = intra
    if vwap is not None:
        out.setdefault("vwap", vwap)
    if ema9 is not None:
        out.setdefault("ema9", ema9)
    return out


_SWING_MATRIX_REFRESH_AT = 0.0
_SWING_MATRIX_REFRESH_TTL = float(os.environ.get("SWING_MATRIX_REFRESH_TTL", "600"))


def _snapshot_data_date(snap: dict[str, Any]) -> str:
    meta = snap.get("selectionMeta") if isinstance(snap.get("selectionMeta"), dict) else {}
    return str(meta.get("dataDate") or "")[:10]


def _snapshot_age_sec(snap: dict[str, Any]) -> float | None:
    iso = snap.get("updatedAt") or snap.get("asOf")
    if not iso:
        meta = snap.get("selectionMeta") if isinstance(snap.get("selectionMeta"), dict) else {}
        iso = meta.get("updatedAt") or meta.get("asOf")
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def _matrix_snapshot_ready_for_today(snap: dict[str, Any]) -> tuple[bool, str]:
    """Return whether Matrix is safe to use for today's swing selection."""
    today = _ist_today()
    stocks = snap.get("stocks") if isinstance(snap.get("stocks"), list) else []
    quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    has_side = any(
        isinstance(s, dict) and (s.get("deterministicSide") or s.get("passes_hard_filters") is not None)
        for s in stocks[:8]
    )
    try:
        universe = int(snap.get("universeSize") or 0)
    except (TypeError, ValueError):
        universe = 0
    universe = universe or len(quotes)
    data_date = _snapshot_data_date(snap)
    if not snap:
        return False, "MATRIX_SNAPSHOT_MISSING"
    if data_date != today:
        return False, f"MATRIX_DATA_DATE_STALE:{data_date or 'MISSING'}"
    if snap.get("isSnapshotFallback") is True:
        return False, "MATRIX_SNAPSHOT_FALLBACK"
    if universe < 400:
        return False, f"MATRIX_UNIVERSE_UNDERSIZED:{universe}"
    if not has_side:
        return False, "MATRIX_DETERMINISTIC_EVIDENCE_MISSING"
    return True, "READY"


def _ensure_today_matrix_snapshot() -> tuple[bool, str]:
    """Refresh Matrix unless today's file is already fresh enough during RTH."""
    global _SWING_MATRIX_REFRESH_AT
    snap = _read_json(_matrix_snapshot_path()) or {}
    ready, reason = _matrix_snapshot_ready_for_today(snap)
    age = _snapshot_age_sec(snap)
    quotes_stale = bool(_is_market_open() and (age is None or age > _SWING_MATRIX_REFRESH_TTL))
    if ready and not quotes_stale:
        return True, reason
    now = time.monotonic()
    if _SWING_MATRIX_REFRESH_AT and now - _SWING_MATRIX_REFRESH_AT < _SWING_MATRIX_REFRESH_TTL:
        if quotes_stale:
            return False, "MATRIX_QUOTES_STALE"
        if ready:
            return True, reason
        return False, reason
    try:
        result = _run_swing_matrix_refresh()
        log.info("Swing hunt matrix refresh: success=%s", result.get("success") if isinstance(result, dict) else result)
        if isinstance(result, dict) and result.get("success") is True:
            _SWING_MATRIX_REFRESH_AT = time.monotonic()
    except Exception as exc:
        log.warning("Swing hunt matrix refresh failed: %s", exc)
    refreshed = _read_json(_matrix_snapshot_path()) or {}
    ready, reason = _matrix_snapshot_ready_for_today(refreshed)
    age_after = _snapshot_age_sec(refreshed)
    still_quotes_stale = bool(
        _is_market_open() and (age_after is None or age_after > _SWING_MATRIX_REFRESH_TTL)
    )
    if still_quotes_stale:
        log.warning("Swing hunt quotes still stale after refresh")
        return False, "MATRIX_QUOTES_STALE"
    if not ready:
        log.warning("Swing hunt remains fail-closed after refresh: %s", reason)
    return ready, reason


def _run_swing_matrix_refresh() -> dict[str, Any]:
    from .angel_one_feed import run_scheduled_live_refresh

    return run_scheduled_live_refresh(reason="swing_entry_hunt")


def _evaluate_swing_buy_contract(
    row: dict[str, Any],
    *,
    intraday_symbols: set[str] | None = None,
) -> tuple[bool, dict[str, Any], list[str]]:
    """Evaluate the deterministic SWING BUY contract without mutating ``row``."""
    row = _hydrate_swing_contract_row(row)
    symbol = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
    original_side, side_source = _explicit_deterministic_side(row)
    passes_hard = _selection_bool(row, "passesHardFilters", "passes_hard_filters")
    passes_quality = _selection_bool(row, "passesQualityFilters", "passes_quality_filters")
    above_vwap = _selection_bool(row, "priceAboveVwap", "price_above_vwap")
    above_ema9 = _selection_bool(row, "priceAboveEma9", "price_above_ema9")
    vwap = _f(_selection_value(row, "vwap", "vwapAtLock"))
    ema9 = _f(_selection_value(row, "ema9", "ema9AtLock"))
    rsi = _f(_selection_value(row, "rsi", "rsiAtLock"))
    oi_setup = str(_selection_value(row, "oiSetup", "oi_setup") or "").upper().strip()
    pivot_breakout = _selection_bool(row, "pivotR1Breakout", "pivot_r1_breakout")
    rsi_breakout = _selection_bool(row, "rsiPivotBreak", "rsi_pivot_break")
    generic_breakout = _selection_bool(row, "breakoutPass", "breakout_pass", "breakoutPassed")
    breakout_pass = (
        generic_breakout
        if generic_breakout is not None
        else pivot_breakout is True and rsi_breakout is True
    )
    selection_price = _parse_price(
        row.get("ltp")
        or row.get("ltpRaw")
        or row.get("scanLtp")
        or row.get("currentPrice")
        or row.get("entryPrice")
        or row.get("entry")
        or row.get("buyAbove")
    )
    risk_values = _risk_audit_values(row)
    blocked = {str(s).upper().strip() for s in (intraday_symbols or set()) if str(s).strip()}

    reasons: list[str] = []
    if original_side not in _BULLISH_SIDES:
        reasons.append(f"EXPLICIT_BUY_SIDE_REQUIRED:{original_side or 'MISSING'}")
    if passes_hard is not True:
        reasons.append("HARD_FILTERS_NOT_PASSED")
    if passes_quality is not True:
        reasons.append("QUALITY_FILTERS_NOT_PASSED")
    if above_vwap is not True or vwap is None or selection_price is None or selection_price <= vwap:
        reasons.append("ABOVE_VWAP_REQUIREMENT_FAILED")
    if above_ema9 is not True or ema9 is None or selection_price is None or selection_price <= ema9:
        reasons.append("ABOVE_EMA9_REQUIREMENT_FAILED")
    oi_val = _f(_selection_value(row, "oi", "oi")) or 0.0
    prev_oi = _f(_selection_value(row, "prevOi", "prev_oi")) or 0.0
    if not oi_setup_allows_buy(oi_setup, oi=oi_val, prev_oi=prev_oi):
        reasons.append(f"BULLISH_OI_REQUIRED:{oi_setup or 'MISSING'}")
    if rsi is None or rsi < MIN_RSI_PIVOT:
        reasons.append(f"RSI_REQUIREMENT_FAILED:min={MIN_RSI_PIVOT:g}")
    if breakout_pass is not True:
        reasons.append("BREAKOUT_REQUIREMENT_FAILED")
    if any(value in _RISK_VETOES for value in risk_values):
        reasons.append(f"RISK_AUDIT_VETO:{','.join(risk_values)}")
    if symbol and symbol in blocked:
        reasons.append("INTRADAY_PORTFOLIO_CONFLICT")
    day_move = day_change_pct_from_row(row)
    if day_move is not None and day_move > MAX_DAY_MOVE_PCT:
        reasons.append(f"DAY_MOVE_OVER_MAX:max={MAX_DAY_MOVE_PCT:g}")

    risk_verdict = risk_values[0] if risk_values else None
    evidence = {
        "contract": SWING_SELECTION_CONTRACT,
        "originalSide": original_side or None,
        "sideSource": side_source,
        "deterministicSide": original_side if original_side in _BULLISH_SIDES else None,
        "canonicalDirection": "LONG" if original_side in _BULLISH_SIDES else None,
        "passesHardFilters": passes_hard,
        "passesQualityFilters": passes_quality,
        "selectionPrice": selection_price,
        "vwap": vwap,
        "ema9": ema9,
        "priceAboveVwap": above_vwap,
        "priceAboveEma9": above_ema9,
        "rsi": rsi,
        "rsiThreshold": MIN_RSI_PIVOT,
        "rsiPass": bool(rsi is not None and rsi >= MIN_RSI_PIVOT),
        "oiSetup": oi_setup or None,
        "pivotR1Breakout": pivot_breakout,
        "rsiPivotBreak": rsi_breakout,
        "breakoutPass": breakout_pass,
        "riskAuditVerdict": risk_verdict,
        "riskAuditDecisions": risk_values,
        "intradayConflict": bool(symbol and symbol in blocked),
        "dayChangePct": day_move,
        "maxDayMovePct": MAX_DAY_MOVE_PCT,
    }
    return not reasons, evidence, reasons


def _matrix_row_levels(row: dict[str, Any], entry: float) -> tuple[float, float, float, float, str]:
    """Build SL/T1/T2 from Matrix facts; document levelsSource on the pick."""
    stop = _parse_price(row.get("stopLoss"))
    t1 = _parse_price(row.get("target1") or row.get("target_price"))
    t2 = _parse_price(row.get("target2"))
    if stop is not None and t1 is not None and stop < entry:
        raw_risk = abs(entry - stop)
        risk = cap_stop_risk(entry, raw_risk)
        stop = round(entry - risk, 2)
        if abs(raw_risk - risk) > 1e-9:
            t1 = round(entry + SWING_T1_R * risk, 2)
            t2 = round(entry + SWING_T2_R * risk, 2)
            return stop, t1, t2, risk, "matrix_explicit_levels_capped"
        if t2 is None:
            t2 = round(entry + SWING_T2_R * risk, 2)
        return stop, t1, t2, risk, "matrix_explicit_levels"

    atr_pct = None
    intraday = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    for raw in (
        row.get("atr_pct"),
        row.get("atrPct"),
        intraday.get("atr_pct") if isinstance(intraday, dict) else None,
    ):
        atr_pct = _f(raw)
        if atr_pct is not None and atr_pct > 0:
            break
    if atr_pct is None or atr_pct <= 0:
        atr_pct = SWING_DEFAULT_ATR_PCT
        levels_src = f"desk_atr_default_{SWING_DEFAULT_ATR_PCT:g}pct"
    else:
        levels_src = "matrix_atr_pct"

    atr_abs = entry * (atr_pct / 100.0)
    risk = cap_stop_risk(entry, atr_abs)
    stop = round(entry - risk, 2)
    t1 = round(entry + SWING_T1_R * risk, 2)
    t2 = round(entry + SWING_T2_R * risk, 2)
    if abs(atr_abs - risk) > 1e-9:
        levels_src = f"{levels_src}+max_stop_0p5pct"
    return stop, t1, t2, risk, levels_src


def _normalize_swing_row(raw: dict[str, Any], session_date: str) -> dict[str, Any] | None:
    symbol = str(raw.get("symbol") or raw.get("ticker") or "").upper().strip()
    if not symbol:
        return None
    entry = _parse_price(
        raw.get("entryPrice")
        or raw.get("buyAbove")
        or raw.get("entry")
        or raw.get("ltp")
        or raw.get("ltpRaw")
        or raw.get("scanLtp")
    )
    if entry is None:
        return None
    if not is_swing_desk_eligible(symbol, entry):
        return None
    contract_passed, selection_evidence, _contract_reasons = _evaluate_swing_buy_contract(raw)
    if not contract_passed:
        return None

    stop = _parse_price(raw.get("stopLoss"))
    t1 = _parse_price(raw.get("target1") or raw.get("target_price"))
    t2 = _parse_price(raw.get("target2"))
    levels_src = str(raw.get("levelsSource") or "")
    risk = _f(raw.get("riskPerShare"))
    if stop is None or t1 is None:
        stop, t1, t2, risk, levels_src = _matrix_row_levels(raw, entry)
    elif risk is None:
        risk = abs(entry - stop)
        if t2 is None and risk > 0:
            t2 = round(entry + SWING_T2_R * risk, 2)
        levels_src = levels_src or "matrix_explicit_levels"

    if stop is None or t1 is None or risk is None or risk <= 0:
        return None

    score_components = None
    intra = raw.get("intraday") if isinstance(raw.get("intraday"), dict) else None
    if isinstance(raw.get("scoreBreakdown"), dict):
        score_components = dict(raw["scoreBreakdown"])
    elif isinstance(raw.get("scoreComponents"), dict):
        score_components = dict(raw["scoreComponents"])
    elif intra:
        # Pass-through known alpha component keys only — never invent
        keys = (
            "rel_vol",
            "relativeVolume",
            "liquidity_score",
            "breakout_quality",
            "sector_rs",
            "sectorRelativeStrength",
            "momentum",
            "momentum_velocity",
            "bulk_deal_score",
            "alpha_score",
        )
        extracted = {k: intra[k] for k in keys if intra.get(k) is not None}
        if extracted:
            score_components = extracted

    filter_stage = SWING_SELECTION_CONTRACT
    lineage_src = str(
        raw.get("_lineageSource")
        or raw.get("_candidateSource")
        or raw.get("source")
        or "asset_matrix_deterministic_buy"
    )
    lock_rank = raw.get("_lockRank")
    try:
        lock_rank = int(lock_rank) if lock_rank is not None else None
    except (TypeError, ValueError):
        lock_rank = None

    expected_r = ((t2 - entry) / risk) if t2 is not None and risk > 0 else 0.0
    if expected_r < SWING_MIN_EXPECTED_R:
        return None
    entry_quality = "ENTRY_A" if expected_r >= SWING_PRIORITY_R else "ENTRY_B"
    locked_at = str(raw.get("_lockTimestamp") or raw.get("lockedAt") or _utc_now_iso())
    acceptance_reason = (
        "Explicit deterministic BUY/LONG; hard and quality filters passed; price above VWAP and EMA9; "
        "RSI and breakout confirmed; bullish OI confirmed; risk audit passed; no intraday-book conflict."
    )
    selection_evidence = {
        **selection_evidence,
        "accepted": True,
        "acceptanceReason": acceptance_reason,
        "lockedAt": locked_at,
        "lockSource": lineage_src,
    }
    return {
        "symbol": symbol,
        "name": raw.get("name") or symbol,
        "originalSide": selection_evidence["originalSide"],
        "deterministicSide": "BUY",
        "direction": selection_evidence["canonicalDirection"],
        "book": "SWING",
        "entryDate": raw.get("entryDate") or session_date,
        "entryPrice": entry,
        "buyAbove": _parse_price(raw.get("buyAbove")) or entry,
        "stopLoss": stop,
        "target1": t1,
        "target2": t2,
        "riskPerShare": risk,
        "rewardRisk": round(expected_r, 2),
        "expectedR": round(expected_r, 2),
        "entryQuality": entry_quality,
        "approxQty": int(raw.get("approxQty") or raw.get("approx_qty") or 0),
        "deployedCapital": _f(raw.get("deployedCapital")) or 0.0,
        "score": _f(raw.get("score")),
        "sector": raw.get("sector"),
        "scanLtp": _parse_price(raw.get("scanLtp") or raw.get("ltp") or raw.get("ltpRaw")),
        "currentPrice": _parse_price(
            raw.get("currentPrice") or raw.get("ltp") or raw.get("ltpRaw") or raw.get("scanLtp") or entry
        ),
        "status": raw.get("status") or "RUNNING",
        "sessionLocked": True,
        "source": "swing_session",
        "lockSource": lineage_src,
        "lockedAt": locked_at,
        "levelsSource": levels_src or "matrix",
        "selectionReason": raw.get("selection_reason") or raw.get("selectionReason") or acceptance_reason,
        "acceptanceReason": acceptance_reason,
        "passesHardFilters": selection_evidence["passesHardFilters"],
        "passesQualityFilters": selection_evidence["passesQualityFilters"],
        "vwap": selection_evidence["vwap"],
        "ema9": selection_evidence["ema9"],
        "rsi": selection_evidence["rsi"],
        "oiSetup": selection_evidence["oiSetup"],
        "riskAuditVerdict": selection_evidence["riskAuditVerdict"],
        "verdict": selection_evidence["riskAuditVerdict"],
        "selectionEvidence": selection_evidence,
        "dayChangePct": _f(raw.get("dayChangePct") or raw.get("delta")),
        "lineage": {
            "source": lineage_src,
            "filterStage": filter_stage,
            "score": _f(raw.get("score")),
            "scoreComponents": score_components,
            "lockRank": lock_rank,
            "selectionReason": raw.get("selection_reason") or raw.get("selectionReason") or acceptance_reason,
            "acceptanceReason": acceptance_reason,
            "originalSide": selection_evidence["originalSide"],
            "riskAuditVerdict": selection_evidence["riskAuditVerdict"],
            "sector": raw.get("sector"),
            "levelsSource": levels_src or "matrix",
            "lockedAt": locked_at,
            "triggeredAt": None,
            "executedFills": None,
            "exitPathTag": None,
        },
    }


def _stock_is_matrix_buy(row: dict[str, Any]) -> bool:
    """Compatibility name for the fail-closed deterministic BUY predicate."""
    eligible, _evidence, _reasons = _evaluate_swing_buy_contract(row)
    return eligible


def _in_candle_screen(row: dict[str, Any]) -> bool:
    """True when the row has real candle metrics (VWAP or RSI), not quote-only."""
    intra = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    vwap = _f(intra.get("vwap") or row.get("vwap"))
    rsi = _f(intra.get("rsi") or row.get("rsi"))
    return (vwap is not None and vwap > 0) or (rsi is not None and rsi > 0)


def _swing_screen_rows(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Hunt universe: display stocks[] plus every snapshot quote.

    Asset Matrix still shows top 50. Missing VWAP/RSI fails the BUY contract
    with an explicit rejection — names are not dropped before evaluation.
    """
    stocks = snap.get("stocks") if isinstance(snap.get("stocks"), list) else []
    quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    by_sym: dict[str, dict[str, Any]] = {}
    for row in stocks:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        by_sym[sym] = row
    for row in quotes.values():
        if not isinstance(row, dict):
            continue
        sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not sym or sym in by_sym:
            continue
        by_sym[sym] = row
    ranked = list(by_sym.values())
    prefilter = load_prefilter_symbols()
    ranked.sort(
        key=lambda r: (
            0 if str(r.get("ticker") or r.get("symbol") or "").upper().strip() in prefilter else 1,
            -float(r.get("score") or r.get("alpha_score") or 0),
            -float(r.get("volume") or 0),
            str(r.get("ticker") or r.get("symbol") or ""),
        )
    )
    return ranked


def _dhan_recommended_symbols(snap: dict[str, Any]) -> list[str]:
    """Ticker list from snapshot dhanSwingPicks. Side/levels on those rows are ignored."""
    block = snap.get("dhanSwingPicks")
    if not isinstance(block, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for pick in block.get("picks") or []:
        if not isinstance(pick, dict):
            continue
        sym = str(pick.get("symbol") or pick.get("ticker") or "").upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _picks_from_asset_matrix(
    snapshot: dict[str, Any] | None = None,
    *,
    exclude_symbols: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return only fully qualified deterministic BUY rows.

    Ledger membership and display padding affect ordering/display only.  Neither
    can confer direction or eligibility.

    DHAN / ScanX names are extra hunt tickers only.  Each is evaluated against
    the same Matrix BUY contract using stocks[] / stockQuotes facts.  Scanner
    LONG, buyAbove, or ScanX levels never confer side or eligibility.
    """
    snap = snapshot if isinstance(snapshot, dict) else _read_json(_matrix_snapshot_path())
    ti = snap.get("terminalIntelligence") if isinstance(snap.get("terminalIntelligence"), dict) else {}
    ledger = ti.get("ledger_stocks") if isinstance(ti.get("ledger_stocks"), list) else []
    stocks = snap.get("stocks") if isinstance(snap.get("stocks"), list) else []
    quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    desk_ic_by_ticker = (
        snap.get("deskIcByTicker") if isinstance(snap.get("deskIcByTicker"), dict) else {}
    )
    blocked = {str(s).upper().strip() for s in (exclude_symbols or set()) if str(s).strip()}

    by_ticker: dict[str, dict[str, Any]] = {}
    for s in stocks:
        if not isinstance(s, dict):
            continue
        sym = str(s.get("ticker") or s.get("symbol") or s.get("Sym") or "").upper().strip()
        if sym:
            by_ticker[sym] = s

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set(blocked)
    skipped_cross = 0

    def _merge_quote(row: dict[str, Any], sym: str) -> dict[str, Any]:
        out = dict(row)
        q = quotes.get(sym) if isinstance(quotes.get(sym), dict) else None
        stock = by_ticker.get(sym)
        desk_ic = desk_ic_by_ticker.get(sym)
        if stock:
            for k in (
                "ltp",
                "ltpRaw",
                "delta",
                "intraday",
                "score",
                "verdict",
                "riskAuditVerdict",
                "deskIcSummary",
                "deterministicSide",
                "deterministic_side",
                "signalSide",
                "tradeSide",
                "side",
                "direction",
                "passes_hard_filters",
                "passes_quality_filters",
                "name",
                "sector",
            ):
                if out.get(k) in (None, "", []) and stock.get(k) is not None:
                    out[k] = stock.get(k)
            if not out.get("intraday") and isinstance(stock.get("intraday"), dict):
                out["intraday"] = stock["intraday"]
        if q:
            if out.get("ltp") in (None, "") and q.get("ltp") is not None:
                out["ltp"] = q.get("ltp")
            if out.get("ltpRaw") in (None, "") and q.get("ltpRaw") is not None:
                out["ltpRaw"] = q.get("ltpRaw")
            if out.get("delta") in (None, "") and q.get("delta") is not None:
                out["delta"] = q.get("delta")
        if isinstance(desk_ic, dict):
            out["deskIcSummary"] = dict(desk_ic)
        return out

    src = "asset_matrix_deterministic_buy"
    if ledger:
        ranked_ledger = sorted(
            [r for r in ledger if isinstance(r, dict)],
            key=lambda r: float(r.get("score") or 0),
            reverse=True,
        )
        for row in ranked_ledger:
            sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            if sym in blocked:
                skipped_cross += 1
                continue
            if sym in seen:
                continue
            merged = _merge_quote(
                {
                    **row,
                    "_fromLedger": True,
                    "_candidateSource": "asset_matrix_ledger",
                    "symbol": sym,
                    "ticker": sym,
                },
                sym,
            )
            if not _stock_is_matrix_buy(merged):
                continue
            seen.add(sym)
            candidates.append(merged)
            if len(candidates) >= SWING_MATRIX_LOCK_COUNT:
                break

    if len(candidates) < SWING_MATRIX_LOCK_COUNT:
        for sym in _dhan_recommended_symbols(snap):
            if len(candidates) >= SWING_MATRIX_LOCK_COUNT:
                break
            if sym in blocked:
                skipped_cross += 1
                continue
            if not sym or sym in seen:
                continue
            stock = by_ticker.get(sym)
            quote = quotes.get(sym) if isinstance(quotes.get(sym), dict) else None
            if not isinstance(stock, dict) and not isinstance(quote, dict):
                continue
            base = dict(stock) if isinstance(stock, dict) else dict(quote)
            merged = _merge_quote(
                {
                    **base,
                    "_candidateSource": "dhan_recommendation_gated",
                    "symbol": sym,
                    "ticker": sym,
                },
                sym,
            )
            if not _stock_is_matrix_buy(merged):
                continue
            seen.add(sym)
            candidates.append(merged)

    if len(candidates) < SWING_MATRIX_LOCK_COUNT:
        for row in _swing_screen_rows(snap):
            sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            if sym in blocked:
                skipped_cross += 1
                continue
            if sym in seen:
                continue
            merged = _merge_quote(
                {**row, "_candidateSource": "asset_matrix_deterministic_buy", "symbol": sym, "ticker": sym},
                sym,
            )
            if not _stock_is_matrix_buy(merged):
                continue
            seen.add(sym)
            candidates.append(merged)
            if len(candidates) >= SWING_MATRIX_LOCK_COUNT:
                break

    if skipped_cross:
        log.info(
            "Swing matrix skip %d intradAy-locked symbol(s) for cross-book uniqueness",
            skipped_cross,
        )
    return candidates[:SWING_MATRIX_LOCK_COUNT], src


def _booked_execution_record(session_date: str, symbol: str) -> dict[str, Any] | None:
    if not session_date or not symbol:
        return None
    book = _read_json(os.path.join(_EOD_DATA_DIR, session_date[:10], "book_swing.json"))
    for row in book.get("picks") or []:
        if not isinstance(row, dict) or str(row.get("symbol") or "").upper() != symbol:
            continue
        lineage = row.get("lineage") if isinstance(row.get("lineage"), dict) else {}
        fills = lineage.get("executedFills") if isinstance(lineage, dict) else None
        return {
            "symbol": symbol,
            "sessionDate": session_date[:10],
            "executionStatus": row.get("executionStatus"),
            "executionBasis": row.get("executionBasis"),
            "pnlKind": row.get("pnlKind"),
            "triggered": bool(row.get("triggered")),
            "skipped": bool(row.get("skipped")),
            "entryPrice": _f(row.get("entryPrice")),
            "exitPrice": _f(row.get("exitPrice") or row.get("currentPrice")),
            "qty": int(row.get("qty") or row.get("approxQty") or 0),
            "deployedCapital": _f(row.get("deployedCapital")) or 0.0,
            "realizedPnl": _f(row.get("realizedPnl") if row.get("realizedPnl") is not None else row.get("pnl")),
            "pnlPct": _f(row.get("pnlPct")),
            "exitReason": row.get("exitReason"),
            "status": row.get("status"),
            "executedFills": copy.deepcopy(fills) if isinstance(fills, list) else None,
            "source": "eod/book_swing.json",
        }
    return None


def _row_execution_record(session_date: str, row: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(row.get("symbol") or "").upper().strip()
    booked = _booked_execution_record(session_date, symbol)
    if booked is not None:
        return booked
    lineage = row.get("lineage") if isinstance(row.get("lineage"), dict) else {}
    fills = lineage.get("executedFills") if isinstance(lineage, dict) else None
    has_execution = bool(
        row.get("triggered")
        or row.get("executionStatus") in {"TRIGGERED", "EXECUTED", "FILLED"}
        or isinstance(fills, list) and fills
        or row.get("realizedPnl") is not None
    )
    if not has_execution:
        return None
    return {
        "symbol": symbol,
        "sessionDate": session_date[:10],
        "executionStatus": row.get("executionStatus"),
        "executionBasis": row.get("executionBasis"),
        "pnlKind": row.get("pnlKind"),
        "triggered": bool(row.get("triggered")),
        "skipped": bool(row.get("skipped")),
        "entryPrice": _f(row.get("entryPrice")),
        "exitPrice": _f(row.get("exitPrice") or row.get("currentPrice")),
        "qty": int(row.get("qty") or row.get("approxQty") or 0),
        "deployedCapital": _f(row.get("deployedCapital")) or 0.0,
        "realizedPnl": _f(row.get("realizedPnl")),
        "pnlPct": _f(row.get("pnlPct")),
        "exitReason": row.get("exitReason"),
        "status": row.get("status"),
        "executedFills": copy.deepcopy(fills) if isinstance(fills, list) else None,
        "source": "swing_session_row",
    }


def _append_invalid_selection_audit(
    session: dict[str, Any],
    row: dict[str, Any],
    reasons: list[str],
    *,
    excluded_at: str,
) -> None:
    symbol = str(row.get("symbol") or "?").upper().strip() or "?"
    session_date = str(session.get("sessionDate") or "")[:10]
    audit_rows = list(session.get("excludedInvalidSelections") or [])
    duplicate = any(
        isinstance(item, dict)
        and str(item.get("symbol") or "").upper() == symbol
        and str(item.get("sessionDate") or "")[:10] == session_date
        for item in audit_rows
    )
    execution = _row_execution_record(session_date, row)
    if not duplicate:
        audit_rows.append({
            "symbol": symbol,
            "sessionDate": session_date,
            "status": "EXCLUDED_INVALID_SELECTION",
            "contract": SWING_SELECTION_CONTRACT,
            "excludedAt": excluded_at,
            "rejectionReasons": list(reasons),
            "originalSelection": copy.deepcopy(row),
            "preservedExecution": copy.deepcopy(execution),
        })
    session["excludedInvalidSelections"] = audit_rows

    if execution is None:
        return
    was_executed = bool(
        execution.get("triggered")
        or execution.get("executionStatus") in {"TRIGGERED", "EXECUTED", "FILLED"}
        or execution.get("executedFills")
    )
    if not was_executed:
        return
    history = list(session.get("preservedExecutionHistory") or [])
    history_key = (session_date, symbol)
    if not any(
        isinstance(item, dict)
        and (str(item.get("sessionDate") or "")[:10], str(item.get("symbol") or "").upper()) == history_key
        for item in history
    ):
        history.append(execution)
    session["preservedExecutionHistory"] = history


def _recompute_active_swing_totals(session: dict[str, Any]) -> None:
    long_rows = [r for r in (session.get("long") or []) if isinstance(r, dict)]
    short_rows = [r for r in (session.get("short") or []) if isinstance(r, dict)]
    active = [*long_rows, *short_rows]
    deployed = round(sum(float(r.get("deployedCapital") or 0) for r in active), 2)
    portfolio_risk = round(sum(float(r.get("maxLoss") or 0) for r in active), 2)
    session["counts"] = {"long": len(long_rows), "short": len(short_rows), "total": len(active)}
    capital = dict(session.get("capital") or {})
    capital.update({
        "swingCapital": SWING_CAPITAL,
        "slots": len(active),
        "deployedCapital": deployed,
        "remainingCapital": round(max(0.0, SWING_CAPITAL - deployed), 2),
        "portfolioRisk": portfolio_risk,
    })
    session["capital"] = capital
    session["cashHeld"] = not active
    if not active:
        session["cashReason"] = session.get("cashReason") or "NO_ACTIVE_VALID_SWING_SELECTIONS"
    else:
        session.pop("cashReason", None)


def _scrub_ineligible_swing_rows(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove every row that cannot prove the full deterministic BUY contract.

    Removed rows are copied into ``excludedInvalidSelections`` and any recorded
    execution economics are retained separately from the active portfolio.
    """
    day = str(session.get("sessionDate") or _ist_today())[:10]
    blocked = intraday_locked_symbols(day)
    removed: list[str] = []
    kept_long: list[dict[str, Any]] = []
    kept_short: list[dict[str, Any]] = []
    rejected: list[tuple[dict[str, Any], list[str]]] = []

    for side_key, target in (("long", kept_long), ("short", kept_short)):
        for row in session.get(side_key) or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "?").upper().strip() or "?"
            if row.get("closed"):
                target.append(row)
                continue
            entry = _f(row.get("entryPrice") or row.get("scanLtp") or row.get("currentPrice"))
            eligible, _evidence, reasons = _evaluate_swing_buy_contract(
                row,
                intraday_symbols=blocked,
            )
            if not is_swing_desk_eligible(symbol, entry):
                reasons.append(f"DESK_GATE_FAILED:min={SWING_MIN_PRICE:g}|no_dvr")
            if side_key == "short":
                reasons.append("SWING_BOOK_IS_BUY_ONLY")
            if not eligible or reasons:
                removed.append(symbol)
                rejected.append((row, reasons))
                continue
            target.append(row)

    if not removed:
        return session, []

    scrubbed = dict(session)
    scrubbed["long"] = kept_long
    scrubbed["short"] = kept_short
    excluded_at = _utc_now_iso()
    for row, reasons in rejected:
        _append_invalid_selection_audit(scrubbed, row, reasons, excluded_at=excluded_at)
    previous_skip = list(scrubbed.get("skippedIncomplete") or [])
    for symbol, (_row, reasons) in zip(removed, rejected):
        tag = f"{symbol}:{'|'.join(reasons)}"
        if tag not in previous_skip:
            previous_skip.append(tag)
    scrubbed["skippedIncomplete"] = previous_skip
    if blocked:
        cross = set(scrubbed.get("crossBookExcluded") or [])
        cross.update(symbol for symbol in removed if symbol in blocked)
        scrubbed["crossBookExcluded"] = sorted(cross)
    _recompute_active_swing_totals(scrubbed)
    scrubbed["selectionFinalized"] = True
    scrubbed["selectionContract"] = SWING_SELECTION_CONTRACT
    scrubbed["scrubbedAt"] = excluded_at
    scrubbed["updatedAt"] = excluded_at
    log.warning(
        "Scrubbed %d fail-closed swing selection(s): %s",
        len(removed),
        ",".join(removed),
    )
    return scrubbed, removed


def _scrub_cross_book_swing_rows(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop swing rows whose symbol is already on today's locked intradAy desk.

    Does not re-size remaining rows — preserves qty / outcome fields.
    """
    day = str(session.get("sessionDate") or _ist_today())[:10]
    blocked = intraday_locked_symbols(day)
    if not blocked:
        return session, []
    original_long = [r for r in (session.get("long") or []) if isinstance(r, dict)]
    original_short = [r for r in (session.get("short") or []) if isinstance(r, dict)]
    open_long = [r for r in original_long if not r.get("closed")]
    closed_long = [r for r in original_long if r.get("closed")]
    open_short = [r for r in original_short if not r.get("closed")]
    closed_short = [r for r in original_short if r.get("closed")]
    long_kept, dropped_long = filter_rows_excluding(open_long, blocked)
    short_kept, dropped_short = filter_rows_excluding(open_short, blocked)
    long_kept = closed_long + long_kept
    short_kept = closed_short + short_kept
    removed = sorted(set(dropped_long + dropped_short))
    if not removed:
        return session, []
    sess = dict(session)
    sess["long"] = long_kept
    sess["short"] = short_kept
    excluded_at = _utc_now_iso()
    for row in [*original_long, *original_short]:
        sym = str(row.get("symbol") or "").upper().strip()
        if sym in removed:
            _append_invalid_selection_audit(
                sess,
                row,
                ["INTRADAY_PORTFOLIO_CONFLICT"],
                excluded_at=excluded_at,
            )
    prev_skip = list(sess.get("skippedIncomplete") or [])
    for sym in removed:
        tag = f"{sym}:cross_book_intraday"
        if tag not in prev_skip:
            prev_skip.append(tag)
    sess["skippedIncomplete"] = prev_skip
    _recompute_active_swing_totals(sess)
    sess["crossBookExcluded"] = removed
    sess["selectionFinalized"] = True
    sess["selectionContract"] = SWING_SELECTION_CONTRACT
    sess["updatedAt"] = excluded_at
    log.info(
        "Scrubbed %d swing name(s) already on intradAy desk: %s",
        len(removed),
        ",".join(removed),
    )
    return sess, removed


def _persist_swing_if_changed(original: dict[str, Any], scrubbed: dict[str, Any]) -> dict[str, Any]:
    if scrubbed is original:
        return scrubbed
    if scrubbed == original:
        return scrubbed
    _atomic_write(_SWING_SESSION_PATH, scrubbed)
    return scrubbed


def _enforce_swing_position_cap(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Migrate persisted books to the configured cap without re-sizing history.

    Existing rows are kept in their deterministic lock order. Dropped symbols are
    recorded so the migration is auditable, and capital is recomputed from the
    retained rows. This guard runs on reads as well as locks, preventing an old
    JSON session from bypassing a newly lowered production cap.
    """
    long_rows = [r for r in (session.get("long") or []) if isinstance(r, dict)]
    short_rows = [r for r in (session.get("short") or []) if isinstance(r, dict)]
    combined = [("long", r) for r in long_rows] + [("short", r) for r in short_rows]
    if len(combined) <= SWING_MATRIX_LOCK_COUNT:
        return session, []

    retained = combined[:SWING_MATRIX_LOCK_COUNT]
    dropped = [str(r.get("symbol") or "?").upper() for _, r in combined[SWING_MATRIX_LOCK_COUNT:]]
    kept_long = [r for side, r in retained if side == "long"]
    kept_short = [r for side, r in retained if side == "short"]
    deployed = round(sum(float(r.get("deployedCapital") or 0) for _, r in retained), 2)
    portfolio_risk = round(sum(float(r.get("maxLoss") or 0) for _, r in retained), 2)

    sess = dict(session)
    sess["long"] = kept_long
    sess["short"] = kept_short
    sess["counts"] = {
        "long": len(kept_long),
        "short": len(kept_short),
        "total": len(retained),
    }
    capital = dict(sess.get("capital") or {})
    capital.update({
        "swingCapital": SWING_CAPITAL,
        "slots": len(retained),
        "deployedCapital": deployed,
        "remainingCapital": round(max(0.0, SWING_CAPITAL - deployed), 2),
        "portfolioRisk": portfolio_risk,
    })
    sess["capital"] = capital
    sess["positionCap"] = SWING_MATRIX_LOCK_COUNT
    sess["capMigration"] = {
        "at": _utc_now_iso(),
        "droppedSymbols": dropped,
        "reason": "MAX_SWING_POSITIONS",
    }
    sess["updatedAt"] = _utc_now_iso()
    return sess, dropped


def _swing_universe_diagnostics(
    *,
    exclude_symbols: set[str] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tally deterministic BUY contract rejections from the live snapshot."""
    snap = snapshot if isinstance(snapshot, dict) else _read_json(_matrix_snapshot_path())
    stocks = snap.get("stocks") if isinstance(snap.get("stocks"), list) else []
    screen = _swing_screen_rows(snap)
    blocked = {str(s).upper().strip() for s in (exclude_symbols or set()) if str(s).strip()}
    reason_counts: dict[str, int] = {}
    evaluated = 0
    qualified = 0
    candle_metrics = 0
    for row in screen:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        evaluated += 1
        if _in_candle_screen(row):
            candle_metrics += 1
        ok, _evidence, reasons = _evaluate_swing_buy_contract(row, intraday_symbols=blocked)
        if ok:
            qualified += 1
            continue
        for reason in reasons:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    top = sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    try:
        universe_size = int(snap.get("universeSize") or 0)
    except (TypeError, ValueError):
        universe_size = 0
    try:
        volume_screened = int(snap.get("volumeScreenedCount") or 0)
    except (TypeError, ValueError):
        volume_screened = 0
    return {
        "universeSize": universe_size or None,
        "volumeScreened": volume_screened or len(screen),
        "candleMetrics": candle_metrics,
        "displayPool": len(stocks),
        "evaluated": evaluated,
        "qualified": qualified,
        "crossBookExcluded": sorted(blocked),
        "swingUniverse": "Nifty 500",
        "topRejectionReasons": [{"reason": k, "count": v} for k, v in top],
    }


def _normalize_candidate_rows(
    raw_picks: list[dict[str, Any]],
    session_date: str,
    *,
    committed_at: str,
    snap_src: str,
    rank_start: int = 1,
) -> tuple[list[dict[str, Any]], list[str]]:
    long_rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for offset, raw in enumerate(raw_picks):
        rank_idx = rank_start + offset
        sym = str(raw.get("symbol") or raw.get("ticker") or "?").upper().strip()
        entry = _parse_price(
            raw.get("entryPrice")
            or raw.get("buyAbove")
            or raw.get("entry")
            or raw.get("ltp")
            or raw.get("ltpRaw")
            or raw.get("scanLtp")
        )
        annotated = {
            **raw,
            "_lockRank": rank_idx,
            "_lockTimestamp": committed_at,
            "_lineageSource": raw.get("_candidateSource") or snap_src,
        }
        row = _normalize_swing_row(annotated, session_date)
        if row is None:
            if sym and entry is not None and not is_swing_desk_eligible(sym, entry):
                skipped.append(f"{sym}:desk_gate(min={SWING_MIN_PRICE:g}|no_dvr)")
            else:
                skipped.append(sym or "?")
            continue
        long_rows.append(row)
    return long_rows, skipped


def _size_new_swing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Size each new name against full slot capacity so later fills do not resize."""
    return [
        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=SWING_MATRIX_LOCK_COUNT))
        for r in rows[:SWING_MATRIX_LOCK_COUNT]
    ]


def _row_status_label(row: dict[str, Any]) -> str:
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    return str(row.get("status") or outcome.get("label") or "").upper()


def _unique_swing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per symbol for the session day.

    Same-day re-entry of a closed name is dropped. If clones exist, keep the
    first stop-out (INITIAL/TRAIL STOP HIT) over SCALE COMPLETE mislabels,
    else the first closed copy, else the latest open row.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        if sym not in groups:
            groups[sym] = []
            order.append(sym)
        groups[sym].append(row)
    unique: list[dict[str, Any]] = []
    for sym in order:
        copies = groups[sym]
        closed = [r for r in copies if r.get("closed")]
        opens = [r for r in copies if not r.get("closed")]
        if closed:
            stop = [r for r in closed if "STOP HIT" in _row_status_label(r)]
            unique.append((stop or closed)[0])
            continue
        unique.append(opens[-1] if opens else copies[0])
    return unique


def _swing_occupied_symbols(session: dict[str, Any]) -> set[str]:
    """Symbols already in today's swing book (open, closed, or preserved)."""
    occupied: set[str] = set()
    day = str(session.get("sessionDate") or "")[:10]
    for side in ("long", "short"):
        for row in session.get(side) or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper().strip()
            if sym:
                occupied.add(sym)
    for item in session.get("preservedExecutionHistory") or []:
        if not isinstance(item, dict):
            continue
        item_day = str(item.get("sessionDate") or "")[:10]
        if day and item_day and item_day != day:
            continue
        sym = str(item.get("symbol") or "").upper().strip()
        if sym:
            occupied.add(sym)
    return occupied


def _dedupe_swing_session_rows(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Collapse duplicate symbols in long/short. Returns (session, dropped symbols)."""
    dropped: list[str] = []
    sess = session
    for side in ("long", "short"):
        rows = [r for r in (session.get(side) or []) if isinstance(r, dict)]
        unique = _unique_swing_rows(rows)
        if len(unique) == len(rows):
            continue
        if sess is session:
            sess = dict(session)
        kept = {id(r) for r in unique}
        for row in rows:
            if id(row) in kept:
                continue
            dropped.append(str(row.get("symbol") or "?").upper())
        sess[side] = unique
    if sess is session:
        return session, []
    _recompute_active_swing_totals(sess)
    sess["updatedAt"] = _utc_now_iso()
    return sess, dropped


def _append_new_swing_entries(session: dict[str, Any]) -> dict[str, Any] | None:
    """Lock newly qualified BUY names into remaining slots. Does not resize existing."""
    session, _dupes = _dedupe_swing_session_rows(session)
    existing_rows = [
        r for r in (session.get("long") or [])
        if isinstance(r, dict) and r.get("symbol") and not r.get("closed")
    ]
    remaining = SWING_MATRIX_LOCK_COUNT - len(existing_rows)
    if remaining <= 0:
        return None
    matrix_state = _ensure_today_matrix_snapshot()
    if isinstance(matrix_state, tuple) and matrix_state[0] is False:
        log.info("Swing fill-up skipped — matrix not ready: %s", matrix_state[1])
        return None
    today = str(session.get("sessionDate") or _ist_today())[:10]
    existing_syms = _swing_occupied_symbols(session)
    exclude = set(intraday_locked_symbols(today)) | existing_syms
    raw_picks, snap_src = _picks_from_asset_matrix(exclude_symbols=exclude)
    committed_at = _utc_now_iso()
    new_rows, skipped = _normalize_candidate_rows(
        raw_picks,
        today,
        committed_at=committed_at,
        snap_src=snap_src,
        rank_start=len(existing_rows) + 1,
    )
    added = []
    seen = set(existing_syms)
    for row in _size_new_swing_rows(new_rows):
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym or sym in seen:
            continue
        added.append(row)
        seen.add(sym)
        if len(added) >= remaining:
            break
    if not added:
        return None
    sess = dict(session)
    closed_kept = [
        r for r in (session.get("long") or [])
        if isinstance(r, dict) and r.get("closed")
    ]
    sess["long"] = _unique_swing_rows(existing_rows + added + closed_kept)
    sess["short"] = [r for r in (session.get("short") or []) if isinstance(r, dict)]
    sess["locked"] = True
    sess["cashHeld"] = False
    sess["updatedAt"] = committed_at
    sess["source"] = snap_src
    if skipped:
        prev = list(sess.get("skippedIncomplete") or [])
        for tag in skipped:
            if tag not in prev:
                prev.append(tag)
        sess["skippedIncomplete"] = prev
    _recompute_active_swing_totals(sess)
    hunt_ok, _hunt_code = swing_entry_hunt_allowed()
    active_n = len(_active_swing_rows(sess))
    sess["hunting"] = bool(hunt_ok and active_n < SWING_MATRIX_LOCK_COUNT)
    sess["selectionFinalized"] = not sess["hunting"]
    _atomic_write(_SWING_SESSION_PATH, sess)
    try:
        from .trade_outcome import emit_book_lock_alerts

        emit_book_lock_alerts(
            book="SWING",
            session_date=today,
            long_rows=added,
            short_rows=[],
        )
    except Exception as exc:
        log.warning("Swing fill-up alerts failed: %s", exc)
    log.info(
        "Swing entry fill-up: +%d name(s) %s (total %d/%d)",
        len(added),
        [r.get("symbol") for r in added],
        len(_active_swing_rows(sess)),
        SWING_MATRIX_LOCK_COUNT,
    )
    return {
        "success": True,
        "alreadyLocked": True,
        "filled": [str(r.get("symbol") or "").upper() for r in added],
        "session": sess,
    }


def lock_swing_session(*, force: bool = False, bypass_lock_window: bool = False) -> dict[str, Any]:
    """Lock a fully qualified BUY when found — hunt until 14:45, do not seal at 10:15.

    Daily rotation: a locked book from a prior IST sessionDate is treated as stale
    and re-locked from fresh Matrix BUY cards (force), irrespective of P&L.
    DHAN recommended tickers may fill remaining hunt slots only after the same
    Matrix BUY contract; ScanX LONG never confers side.

    Time gate: entry hunt 09:45–14:45 IST. Empty books stay hunting until a
    qualified entry appears; cash-held only after hunt close. Only
    ``bypass_lock_window=True`` skips the clock. ``force`` rebuilds during hunt
    — it does not open early and does not wipe a live book after 14:45.
    """
    existing = load_swing_session()
    today = _ist_today()
    existing_date = str(existing.get("sessionDate") or "").strip()[:10]
    stale_day = bool(existing.get("locked") and existing_date and existing_date != today)
    if stale_day and not force:
        log.info(
            "Swing sessionDate %s != today %s — forcing fresh deterministic BUY evaluation",
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
            log.warning("Prior-day swing EOD freeze failed for %s: %s", existing_date, exc)

    hunt_ok, hunt_code = swing_entry_hunt_allowed(
        allow_manual_override=bool(bypass_lock_window)
    )
    has_today_book = bool(
        existing.get("locked")
        and existing_date == today
        and any(
            isinstance(r, dict) and r.get("symbol")
            for r in (existing.get("long") or []) + (existing.get("short") or [])
        )
    )

    if has_today_book:
        rebuild = bool(force and hunt_ok)
        if not rebuild:
            if hunt_ok:
                filled = _append_new_swing_entries(existing)
                if filled is not None:
                    return filled
            scrubbed, removed_dup = _dedupe_swing_session_rows(existing)
            scrubbed, removed_gate = _scrub_ineligible_swing_rows(scrubbed)
            scrubbed, removed_cross = _scrub_cross_book_swing_rows(scrubbed)
            scrubbed, removed_cap = _enforce_swing_position_cap(scrubbed)
            removed = removed_dup + removed_gate + removed_cross + removed_cap
            if removed:
                scrubbed = _persist_swing_if_changed(existing, scrubbed)
            return {
                "success": True,
                "alreadyLocked": True,
                "scrubbed": removed,
                "crossBookExcluded": removed_cross,
                "capExcluded": removed_cap,
                "session": scrubbed,
            }

    if not hunt_ok and hunt_code != "after_hunt":
        return {
            "success": False,
            "error": swing_entry_hunt_block_message(hunt_code),
            "lockWindow": hunt_code,
            "huntWindow": swing_entry_hunt_config(),
            "session": existing,
        }

    session_date = today
    committed_at = _utc_now_iso()
    exclude = intraday_locked_symbols(today)
    skipped: list[str] = []
    snap_src = "asset_matrix_deterministic_buy"
    long_rows: list[dict[str, Any]] = []

    if hunt_ok:
        matrix_state = _ensure_today_matrix_snapshot()
        matrix_ready, matrix_reason = (
            matrix_state if isinstance(matrix_state, tuple) else (True, "READY")
        )
        if matrix_ready:
            raw_picks, snap_src = _picks_from_asset_matrix(exclude_symbols=exclude)
            long_rows, skipped = _normalize_candidate_rows(
                raw_picks,
                session_date,
                committed_at=committed_at,
                snap_src=snap_src,
            )
        else:
            skipped.append(matrix_reason)

    diagnostics = _swing_universe_diagnostics(exclude_symbols=exclude)
    hunt_started = committed_at
    if (
        existing_date == today
        and (existing.get("hunting") or existing.get("huntStartedAt"))
    ):
        hunt_started = str(existing.get("huntStartedAt") or existing.get("committedAt") or committed_at)

    if long_rows:
        sized = _size_new_swing_rows(long_rows)
        deployed = round(sum(float(r.get("deployedCapital") or 0) for r in sized), 2)
        portfolio_risk = round(sum(float(r.get("maxLoss") or 0) for r in sized), 2)
        if deployed > SWING_CAPITAL + 0.01 or portfolio_risk > SWING_CAPITAL * SWING_MAX_PORTFOLIO_RISK + 0.01:
            return {"success": False, "error": "SWING_CAPITAL_INVARIANT_VIOLATION", "session": existing}
        still_hunting = hunt_ok and len(sized) < SWING_MATRIX_LOCK_COUNT
        session = {
            "success": True,
            "locked": True,
            "hunting": still_hunting,
            "selectionFinalized": not still_hunting,
            "cashHeld": False,
            "book": "SWING",
            "sessionDate": session_date,
            "committedAt": committed_at,
            "updatedAt": committed_at,
            "huntStartedAt": hunt_started,
            "executionPolicy": "MANUAL_ONLY",
            "source": snap_src,
            "selectionContract": SWING_SELECTION_CONTRACT,
            "rotation": "DAILY",
            "priorSessionDate": existing_date if stale_day else None,
            "long": sized,
            "short": [],
            "skippedIncomplete": skipped,
            "excludedInvalidSelections": copy.deepcopy(existing.get("excludedInvalidSelections") or []),
            "preservedExecutionHistory": copy.deepcopy(existing.get("preservedExecutionHistory") or []),
            "capital": {
                "swingCapital": SWING_CAPITAL,
                "riskFraction": SWING_RISK_FRACTION,
                "slots": len(sized),
                "deployedCapital": deployed,
                "remainingCapital": round(max(0.0, SWING_CAPITAL - deployed), 2),
                "portfolioRisk": portfolio_risk,
            },
            "counts": {"long": len(sized), "short": 0, "total": len(sized)},
            "deskGates": {"minPrice": SWING_MIN_PRICE, "rejectDvr": True},
            "crossBookExcluded": sorted(exclude),
            "huntWindow": swing_entry_hunt_config(),
            "entryHuntDiagnostics": diagnostics,
        }
        _atomic_write(_SWING_SESSION_PATH, session)
        try:
            from .trade_outcome import emit_book_lock_alerts

            emit_book_lock_alerts(
                book="SWING",
                session_date=session_date,
                long_rows=sized,
                short_rows=[],
            )
        except Exception as exc:
            log.warning("Swing lock alerts failed: %s", exc)
        log.info(
            "Locked swing session from %s: %d LONGs (%s)%s%s",
            session["source"],
            len(sized),
            session_date,
            f" rotated from {existing_date}" if stale_day else "",
            f" excluded intradAy={sorted(exclude)}" if exclude else "",
        )
        return {
            "success": True,
            "alreadyLocked": False,
            "rotated": stale_day,
            "hunting": still_hunting,
            "session": session,
        }

    if hunt_ok:
        hunting_session = {
            "success": True,
            "locked": False,
            "hunting": True,
            "selectionFinalized": False,
            "cashHeld": False,
            "book": "SWING",
            "sessionDate": session_date,
            "committedAt": hunt_started,
            "updatedAt": committed_at,
            "huntStartedAt": hunt_started,
            "executionPolicy": "MANUAL_ONLY",
            "source": snap_src,
            "selectionContract": SWING_SELECTION_CONTRACT,
            "rotation": "DAILY",
            "priorSessionDate": existing_date if stale_day else None,
            "long": [],
            "short": [],
            "skippedIncomplete": skipped,
            "excludedInvalidSelections": copy.deepcopy(existing.get("excludedInvalidSelections") or []),
            "preservedExecutionHistory": copy.deepcopy(existing.get("preservedExecutionHistory") or []),
            "capital": {
                "swingCapital": SWING_CAPITAL,
                "riskFraction": SWING_RISK_FRACTION,
                "slots": 0,
                "deployedCapital": 0.0,
                "remainingCapital": SWING_CAPITAL,
                "portfolioRisk": 0.0,
            },
            "counts": {"long": 0, "short": 0, "total": 0},
            "deskGates": {"minPrice": SWING_MIN_PRICE, "rejectDvr": True},
            "crossBookExcluded": sorted(exclude),
            "cashReason": (
                "WAITING_FOR_QUALIFIED_BUY_ENTRY"
                if not skipped or not skipped[0].startswith("MATRIX_")
                else skipped[0]
            ),
            "huntWindow": swing_entry_hunt_config(),
            "entryHuntDiagnostics": diagnostics,
        }
        _atomic_write(_SWING_SESSION_PATH, hunting_session)
        log.info(
            "Swing entry hunt open for %s — no fully qualified BUY yet (evaluated=%s qualified=%s)",
            session_date,
            diagnostics.get("evaluated"),
            diagnostics.get("qualified"),
        )
        return {
            "success": True,
            "alreadyLocked": False,
            "hunting": True,
            "cashHeld": False,
            "reason": "WAITING_FOR_QUALIFIED_BUY_ENTRY",
            "skipped": skipped,
            "session": hunting_session,
            "staleDay": stale_day,
        }

    cash_session = {
        "success": True,
        "locked": True,
        "hunting": False,
        "selectionFinalized": True,
        "cashHeld": True,
        "book": "SWING",
        "sessionDate": session_date,
        "committedAt": committed_at,
        "updatedAt": committed_at,
        "huntStartedAt": hunt_started,
        "executionPolicy": "MANUAL_ONLY",
        "source": snap_src,
        "selectionContract": SWING_SELECTION_CONTRACT,
        "rotation": "DAILY",
        "priorSessionDate": existing_date if stale_day else None,
        "long": [],
        "short": [],
        "skippedIncomplete": skipped,
        "excludedInvalidSelections": copy.deepcopy(existing.get("excludedInvalidSelections") or []),
        "preservedExecutionHistory": copy.deepcopy(existing.get("preservedExecutionHistory") or []),
        "capital": {
            "swingCapital": SWING_CAPITAL,
            "riskFraction": SWING_RISK_FRACTION,
            "slots": 0,
            "deployedCapital": 0.0,
            "remainingCapital": SWING_CAPITAL,
            "portfolioRisk": 0.0,
        },
        "counts": {"long": 0, "short": 0, "total": 0},
        "deskGates": {"minPrice": SWING_MIN_PRICE, "rejectDvr": True},
        "crossBookExcluded": sorted(exclude),
        "cashReason": "NO_FULLY_QUALIFIED_EXPLICIT_BUY_CANDIDATES",
        "huntWindow": swing_entry_hunt_config(),
        "entryHuntDiagnostics": diagnostics,
    }
    _atomic_write(_SWING_SESSION_PATH, cash_session)
    return {
        "success": True,
        "alreadyLocked": False,
        "cashHeld": True,
        "hunting": False,
        "reason": "NO_FULLY_QUALIFIED_EXPLICIT_BUY_CANDIDATES",
        "skipped": skipped,
        "session": cash_session,
        "staleDay": stale_day,
    }


def _active_swing_rows(session: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for side in ("long", "short"):
        for row in session.get(side) or []:
            if isinstance(row, dict) and row.get("symbol") and not row.get("closed"):
                rows.append(row)
    return rows


def ensure_swing_session_locked(*, retry_empty: bool = False) -> dict[str, Any]:
    """Idempotent lock — hunt until a qualified BUY is found, then lock it.

    ``retry_empty=True`` (scheduler) re-evaluates Asset Matrix BUY candidates
    while the entry hunt is open: hunting/cash-held empty books, and remaining
    slots on a partial lock. Never fabricates fills; only locks fully qualified
    deterministic BUY rows.
    """
    existing = load_swing_session()
    today = _ist_today()
    existing_date = str(existing.get("sessionDate") or "").strip()[:10]
    if existing.get("locked") and existing_date == today:
        if retry_empty and not _active_swing_rows(existing):
            has_names = any(
                isinstance(r, dict) and r.get("symbol")
                for r in (existing.get("long") or []) + (existing.get("short") or [])
            )
            result = lock_swing_session(force=not has_names)
            return result.get("session") or existing
        if retry_empty:
            result = lock_swing_session(force=False)
            return result.get("session") or existing
        scrubbed, removed_dup = _dedupe_swing_session_rows(existing)
        scrubbed, removed_gate = _scrub_ineligible_swing_rows(scrubbed)
        scrubbed, removed_cross = _scrub_cross_book_swing_rows(scrubbed)
        scrubbed, removed_cap = _enforce_swing_position_cap(scrubbed)
        if removed_dup or removed_gate or removed_cross or removed_cap:
            return _persist_swing_if_changed(existing, scrubbed)
        return scrubbed
    if existing.get("hunting") and existing_date == today:
        result = lock_swing_session(force=False)
        return result.get("session") or existing
    result = lock_swing_session(force=True if (existing.get("locked") and existing_date != today) else False)
    return result.get("session") or existing


def refresh_swing_session_state() -> dict[str, Any]:
    """Scheduler single-writer: persist live marks + scale-trail closes.

    Mirrors intradAy ``refresh_session_state`` so SL / trail SL / EOD square-off
    survive without a browser tab open. Paper Book only (MANUAL_ONLY) — no broker
    orders. Never mutates symbols, entry levels, or selection evidence.
    """
    sess = load_swing_session()
    if not sess.get("locked"):
        return sess
    day = str(sess.get("sessionDate") or "")[:10]
    if day != _ist_today():
        return sess

    live = _compute_swing_session(live=True)
    changed = False
    sess, dupes = _dedupe_swing_session_rows(sess)
    if dupes:
        changed = True
    for side in ("long", "short"):
        orig_rows = _unique_swing_rows(
            [r for r in (sess.get(side) or []) if isinstance(r, dict)]
        )
        live_by = {
            str(r.get("symbol") or "").upper(): r
            for r in _unique_swing_rows(
                [r for r in (live.get(side) or []) if isinstance(r, dict)]
            )
            if r.get("symbol")
        }
        updated_rows: list[dict[str, Any]] = []
        for row in orig_rows:
            symbol = str(row.get("symbol") or "").upper()
            if row.get("closed") or str((row.get("exitState") or {}).get("pathReplay") or ""):
                updated_rows.append(row)
                continue
            live_row = live_by.get(symbol)
            if not live_row:
                updated_rows.append(row)
                continue
            merged = dict(row)
            for key in (
                "ltp",
                "currentPrice",
                "ltpSource",
                "dayChangePct",
                "realizedPnl",
                "unrealizedPnl",
                "unrealizedPnlPct",
                "totalPnl",
                "exitState",
                "outcome",
                "effectiveStop",
                "remainingQty",
                "exitPlan",
                "status",
                "bookExitReason",
                "executionStatus",
                "triggered",
                "skipped",
                "skipReason",
            ):
                if live_row.get(key) is not None and merged.get(key) != live_row.get(key):
                    merged[key] = live_row.get(key)
                    changed = True
            if live_row.get("closed") and not row.get("closed"):
                merged["closed"] = True
                merged["status"] = str(live_row.get("status") or "CLOSED")
                changed = True
            updated_rows.append(merged)
        sess[side] = updated_rows

    if isinstance(live.get("portfolio"), dict):
        if sess.get("portfolio") != live.get("portfolio"):
            sess["portfolio"] = copy.deepcopy(live["portfolio"])
            changed = True

    if not changed:
        return sess
    sess["updatedAt"] = _utc_now_iso()
    sess["priceOnly"] = True
    sess["automation"] = {
        "lastRefreshAt": sess["updatedAt"],
        "source": "refresh_swing_session_state",
        "executionPolicy": sess.get("executionPolicy") or "MANUAL_ONLY",
    }
    _atomic_write(_SWING_SESSION_PATH, sess)
    return sess


def _enrich_swing_row_prices(
    row: dict[str, Any],
    quotes: dict[str, Any],
    stocks_by: dict[str, Any],
    live_marks: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Price-only MTM — never mutate symbol / levels / lock fields."""
    out = dict(row)
    replay = str((out.get("exitState") or {}).get("pathReplay") or "")
    if replay:
        return out
    symbol = str(out.get("symbol") or "").upper()
    ltp = None
    ltp_source = "none"
    delta = None
    # Prefer Angel/Yahoo live marks when provided (market-hours desk poll)
    if live_marks and symbol in live_marks:
        try:
            mark = float(live_marks[symbol])
            if mark > 0:
                ltp = mark
                ltp_source = "live"
        except (TypeError, ValueError):
            pass
    q = quotes.get(symbol) if isinstance(quotes.get(symbol), dict) else None
    s = stocks_by.get(symbol) if isinstance(stocks_by.get(symbol), dict) else None
    if ltp is None and q:
        ltp = _parse_price(q.get("ltpRaw") or q.get("ltp"))
        if ltp is not None:
            ltp_source = "snapshot_quote"
        delta = _f(q.get("delta"))
    if ltp is None and s:
        ltp = _parse_price(s.get("ltpRaw") or s.get("ltp"))
        if ltp is not None:
            ltp_source = "snapshot_stock"
        if delta is None:
            delta = _f(s.get("delta"))
    if ltp is None:
        ltp = _parse_price(out.get("currentPrice") or out.get("ltp") or out.get("scanLtp") or out.get("entryPrice"))
        ltp_source = "cached" if ltp is not None else "none"

    entry = _parse_price(out.get("entryPrice")) or 0.0
    qty = int(out.get("approxQty") or 0)
    unrealized = None
    unrealized_pct = None
    if ltp is not None and entry > 0:
        unrealized = round((ltp - entry) * qty, 2) if qty else None
        unrealized_pct = round((ltp - entry) / entry * 100.0, 2)
    out["ltp"] = round(ltp, 2) if ltp is not None else None
    out["currentPrice"] = out["ltp"]
    out["ltpSource"] = ltp_source
    out["dayChangePct"] = delta if delta is not None else out.get("dayChangePct")
    out["unrealizedPnl"] = unrealized
    out["unrealizedPnlPct"] = unrealized_pct

    # Scale-trail live MTM when exitPlan present (or attachable)
    after_close = False
    try:
        after_close = not _is_market_open()
    except Exception:
        after_close = False

    try:
        attached = refresh_exit_policy(out, keep_exit_state=True)
        if isinstance(attached.get("exitPlan"), dict):
            out["exitPlan"] = attached["exitPlan"]
        if attached.get("bookedExitPlan"):
            out["bookedExitPlan"] = attached["bookedExitPlan"]
    except Exception:
        pass

    already_closed = bool(out.get("closed"))
    if already_closed:
        pass
    elif isinstance(out.get("exitPlan"), dict) and ltp is not None:
        try:
            ev = evaluate_scale_trail(out, ltp, after_close=after_close)
            if ev:
                out["outcome"] = {
                    "label": ev.get("label"),
                    "detail": ev.get("detail"),
                    "hitLevel": ev.get("hitLevel"),
                    "ltp": ev.get("ltp"),
                    "pctChange": ev.get("pctChange"),
                    "scaleTrail": True,
                    "closed": ev.get("closed"),
                }
                if isinstance(ev.get("exitState"), dict):
                    out["exitState"] = ev["exitState"]
                out["remainingQty"] = ev.get("remainingQty")
                out["realizedPnl"] = ev.get("realizedPnl")
                out["unrealizedPnl"] = ev.get("unrealizedPnl")
                out["effectiveStop"] = ev.get("effectiveStop")
                if entry > 0 and ltp is not None:
                    out["unrealizedPnlPct"] = round((ltp - entry) / entry * 100.0, 2)
                if ev.get("closed"):
                    out["closed"] = True
                    out["status"] = str(ev.get("label") or "CLOSED")
                elif ev.get("hitLevel") == "partial":
                    out["status"] = str(ev.get("label") or "PARTIAL")
                elif after_close:
                    st = str(out.get("status") or "").upper()
                    if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
                        out["status"] = "SESSION CLOSED"
            elif after_close:
                st = str(out.get("status") or "").upper()
                if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
                    out["status"] = "SESSION CLOSED"
        except Exception:
            if after_close:
                st = str(out.get("status") or "").upper()
                if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
                    out["status"] = "SESSION CLOSED"
    elif after_close:
        st = str(out.get("status") or "").upper()
        if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
            out["status"] = "SESSION CLOSED"
    # Symbols / levels stay immutable
    return out


def get_swing_session(*, live: bool = False) -> dict[str, Any]:
    """Return cached marks immediately and refresh them outside request workers.

    Always returns a deep copy. Concurrent GET callers cannot mutate the
    persisted portfolio or each other's response payloads. A slow broker/Yahoo
    call must never hold the response lock or exhaust FastAPI's sync worker pool.
    """
    global _SWING_RESPONSE_CACHE, _SWING_RESPONSE_CACHE_AT, _SWING_RESPONSE_REFRESHING
    if not live:
        return copy.deepcopy(_compute_swing_session(live=False))
    ttl = _SWING_RESPONSE_OPEN_TTL if _is_market_open() else _SWING_RESPONSE_CLOSED_TTL
    now = time.monotonic()
    if _SWING_RESPONSE_CACHE is not None and now - _SWING_RESPONSE_CACHE_AT < ttl:
        return copy.deepcopy(_SWING_RESPONSE_CACHE)

    start_refresh = False
    started_gen = 0
    with _SWING_RESPONSE_LOCK:
        now = time.monotonic()
        if _SWING_RESPONSE_CACHE is not None and now - _SWING_RESPONSE_CACHE_AT < ttl:
            return copy.deepcopy(_SWING_RESPONSE_CACHE)
        if _SWING_RESPONSE_CACHE is None:
            fallback = _compute_swing_session(live=False)
            fallback["dataStale"] = True
            fallback["liveRefreshPending"] = True
            _SWING_RESPONSE_CACHE = copy.deepcopy(fallback)
            _SWING_RESPONSE_CACHE_AT = 0.0
        if not _SWING_RESPONSE_REFRESHING:
            _SWING_RESPONSE_REFRESHING = True
            start_refresh = True
            started_gen = _SWING_RESPONSE_GEN
        result = copy.deepcopy(_SWING_RESPONSE_CACHE)
        result["liveRefreshPending"] = True

    if start_refresh:
        try:
            threading.Thread(
                target=_refresh_swing_response_cache,
                args=(started_gen,),
                name="swing-live-refresh",
                daemon=True,
            ).start()
        except Exception:
            with _SWING_RESPONSE_LOCK:
                _SWING_RESPONSE_REFRESHING = False
            log.exception("failed to start swing live refresh")
    return result


def _refresh_swing_response_cache(started_gen: int) -> None:
    """Populate live marks without occupying an AnyIO request worker."""
    global _SWING_RESPONSE_CACHE, _SWING_RESPONSE_CACHE_AT, _SWING_RESPONSE_REFRESHING
    try:
        result = _compute_swing_session(live=True)
        result["liveRefreshPending"] = False
        with _SWING_RESPONSE_LOCK:
            if started_gen != _SWING_RESPONSE_GEN:
                return
            _SWING_RESPONSE_CACHE = copy.deepcopy(result)
            _SWING_RESPONSE_CACHE_AT = time.monotonic()
    except Exception:
        log.exception("swing live refresh failed; serving persisted marks")
    finally:
        with _SWING_RESPONSE_LOCK:
            _SWING_RESPONSE_REFRESHING = False


def _compute_swing_session(*, live: bool = False) -> dict[str, Any]:
    """Return locked swing session; with live=True enrich LTP/Δ only.

    Read-only vs disk: never writes swing_session.json. Duplicate symbols are
    collapsed in the response so the desk shows one card per name.
    """
    sess = load_swing_session()
    if not sess:
        return {
            "locked": False,
            "hunting": False,
            "long": [],
            "short": [],
            "counts": {"total": 0},
            "cashReason": None,
            "entryHuntDiagnostics": None,
        }
    sess = dict(sess)
    long_rows = [r for r in (sess.get("long") or []) if isinstance(r, dict)]
    short_rows = [r for r in (sess.get("short") or []) if isinstance(r, dict)]
    unique_long = _unique_swing_rows(long_rows)
    unique_short = _unique_swing_rows(short_rows)
    sess["long"] = unique_long
    sess["short"] = unique_short
    if len(unique_long) != len(long_rows) or len(unique_short) != len(short_rows):
        _recompute_active_swing_totals(sess)
    if not live:
        return sess
    snap = _read_json(_matrix_snapshot_path())
    quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    stocks_by: dict[str, Any] = {}
    for s in snap.get("stocks") or []:
        if isinstance(s, dict):
            sym = str(s.get("ticker") or s.get("symbol") or "").upper().strip()
            if sym:
                stocks_by[sym] = s
    live_marks: dict[str, float] = {}
    try:
        from .trade_outcome import fetch_live_marks_for_symbols

        syms = [
            str(r.get("symbol") or "").upper()
            for r in (sess.get("long") or []) + (sess.get("short") or [])
            if isinstance(r, dict) and r.get("symbol")
        ]
        live_marks = fetch_live_marks_for_symbols(syms)
    except Exception:
        live_marks = {}
    out = dict(sess)
    out["long"] = [
        _enrich_swing_row_prices(r, quotes, stocks_by, live_marks)
        for r in (sess.get("long") or [])
        if isinstance(r, dict)
    ]
    out["short"] = [
        _enrich_swing_row_prices(r, quotes, stocks_by, live_marks)
        for r in (sess.get("short") or [])
        if isinstance(r, dict)
    ]

    # Once the cash session is closed, the cached Book is authoritative for
    # triggered/skipped classification and realized economics. This keeps the
    # SWING tab aligned with EOD instead of showing correct marks with ₹0 MTM.
    if not _is_market_open() and sess.get("sessionDate"):
        try:
            from datetime import date
            from .eod_swing_report import generate_swing_eod_report

            book = generate_swing_eod_report(
                date.fromisoformat(str(sess.get("sessionDate"))[:10]),
                force=False,
            )
            book_by_symbol = {
                str(row.get("symbol") or "").upper(): row
                for row in (book.get("picks") or [])
                if isinstance(row, dict) and row.get("symbol")
            }
            for row in [*out["long"], *out["short"]]:
                booked = book_by_symbol.get(str(row.get("symbol") or "").upper())
                if not booked:
                    continue
                pnl = float(booked.get("pnl") or 0)
                row.update({
                    "currentPrice": booked.get("currentPrice") or row.get("currentPrice"),
                    "ltp": booked.get("currentPrice") or row.get("ltp"),
                    "deployedCapital": float(booked.get("deployedCapital") or 0),
                    "realizedPnl": pnl,
                    "unrealizedPnl": 0.0,
                    "totalPnl": pnl,
                    "pnlPct": float(booked.get("pnlPct") or 0),
                    "triggered": bool(booked.get("triggered")),
                    "executionStatus": booked.get("executionStatus"),
                    "skipped": bool(booked.get("skipped")),
                    "skipReason": booked.get("skipReason"),
                    "bookExitReason": booked.get("exitReason"),
                    "closed": bool(booked.get("triggered")) or bool(booked.get("skipped")),
                })
                if booked.get("skipped"):
                    row["status"] = str(booked.get("status") or "NOT_TRIGGERED")
                    row["outcome"] = None
                    row["exitState"] = None
                    row["remainingQty"] = 0
        except Exception as exc:
            log.debug("Closed swing Book reconciliation skipped: %s", exc)

    all_rows = [*out["long"], *out["short"]]
    for row in all_rows:
        if row.get("totalPnl") is None:
            row["totalPnl"] = round(
                float(row.get("realizedPnl") or 0) + float(row.get("unrealizedPnl") or 0),
                2,
            )
    realized = sum(float(r.get("realizedPnl") or 0) for r in all_rows)
    unrealized = sum(float(r.get("unrealizedPnl") or 0) for r in all_rows)
    out["portfolio"] = {
        "swingCapital": (sess.get("capital") or {}).get("swingCapital", SWING_CAPITAL),
        "realizedPnl": round(realized, 2),
        "unrealizedPnl": round(unrealized, 2),
        "totalPnl": round(realized + unrealized, 2),
        "lockedCount": len(all_rows),
    }
    # Closed trades remain available for EOD/audit and realized P&L, but must
    # not be presented or counted as active portfolio positions.
    closed_rows = [r for r in all_rows if r.get("closed")]
    out["closedPositions"] = closed_rows
    out["long"] = [r for r in out["long"] if not r.get("closed")]
    out["short"] = [r for r in out["short"] if not r.get("closed")]
    out["counts"] = {
        "long": len(out["long"]),
        "short": len(out["short"]),
        "total": len(out["long"]) + len(out["short"]),
    }
    out["portfolio"]["lockedCount"] = out["counts"]["total"]
    out["priceOnly"] = True
    out["liveMarks"] = len(live_marks)
    out["updatedAt"] = _utc_now_iso()
    out["snapshotUpdatedAt"] = snap.get("updatedAt")
    try:
        from .trade_outcome import collect_hit_alerts_from_rows

        out["newAlerts"] = collect_hit_alerts_from_rows(
            list(out["long"]) + list(out["short"]),
            book="SWING",
        )
    except Exception:
        out["newAlerts"] = []
    return out
