from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.lifecycle import evaluate_position, time_exit_due
from app.services.swing_v2.risk import build_exit_and_size
from app.services.swing_v2.setups import breakout_close_v1


def _breakout_row():
    return {
        "symbol": "TEST",
        "universeSegment": "NIFTY_MIDCAP_150",
        "decisionPrice": 105.0,
        "prior20dHigh": 104.0,
        "trendPriorPctile": 80,
        "clv": .9,
        "rvolPaced": 1.8,
        "residualStrengthPctile": 80,
        "sectorStrengthPctile": 70,
        "breakoutDistanceAtr": .4,
        "extensionAtr": 1.2,
    }


def test_breakout_close_contract_is_independent():
    ok, reasons = breakout_close_v1(_breakout_row())
    assert ok is True
    assert reasons == []


def test_swing_risk_never_allocates_full_sleeve_to_one_name():
    cfg = SwingV2Config()
    row = {**_breakout_row(), "executableEntry": 100.0, "atr14": 2.0, "structureStop": 98.5, "mdtv20": 5_000_000_000}
    sized = build_exit_and_size(row, cfg)
    assert sized["riskEligible"] is True
    assert sized["deployedCapital"] <= cfg.nav * .20
    assert sized["initialRiskRupees"] <= cfg.nav * .0025 + .01


def test_swing_stop_is_not_intraday_half_percent_cap():
    cfg = SwingV2Config()
    row = {**_breakout_row(), "executableEntry": 100.0, "atr14": 2.0, "structureStop": 98.5, "mdtv20": 5_000_000_000}
    sized = build_exit_and_size(row, cfg)
    assert sized["riskPct"] >= .75
    assert sized["riskPct"] > .50


def test_adverse_first_when_stop_and_t1_share_bar():
    pos = {"entryPrice": 100.0, "initialStop": 98.0, "effectiveStop": 98.0, "t1": 102.0, "t2": 104.0, "qty": 10, "remainingQty": 10, "t1Qty": 5}
    out = evaluate_position(pos, {"low": 97.5, "high": 102.5, "close": 101.0})
    assert out["exitReason"] == "STOP_LOSS_FILLED"
    assert out["pathQuality"] == "AMBIGUOUS"


def test_t1_books_half_then_moves_stop_only_after_fill():
    pos = {"entryPrice": 100.0, "initialStop": 98.0, "effectiveStop": 98.0, "t1": 102.0, "t2": 104.0, "qty": 10, "remainingQty": 10, "t1Qty": 5}
    out = evaluate_position(pos, {"low": 99.0, "high": 102.1, "close": 101.5})
    assert out["t1Filled"] is True
    assert out["remainingQty"] == 5
    assert out["effectiveStop"] == 100.0


def test_d2_time_exit_is_mandatory():
    ist = ZoneInfo("Asia/Kolkata")
    assert time_exit_due(datetime(2026, 9, 10, 15, 15, tzinfo=ist), 2) is True
    pos = {"entryPrice": 100.0, "initialStop": 98.0, "effectiveStop": 98.0, "t1": 102.0, "t2": 104.0, "qty": 10, "remainingQty": 10}
    out = evaluate_position(pos, {"low": 99.0, "high": 101.0, "close": 100.25}, is_d2_exit=True)
    assert out["exitReason"] == "TIME_EXIT_FILLED"
    assert out["exitPrice"] == 100.25
