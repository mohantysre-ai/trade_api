"""Tests for index_options_intraday_strategy.

Covers:
- Position creation with correct SL/target
- Initial stop hit closes position at correct P&L
- 40-point target triggers partial book + breakeven SL
- Trail SL hit after partial book
- EOD square off
- Pyramiding adds lots at profit triggers
- Parallel evaluation across positions
- Position serialization round-trip
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, time as dt_time
from threading import Thread

import pytest

from app.services.angel_index_options import IST_ZONE
from app.services.index_options_intraday_strategy import (
    INTRADAY_MAX_PYRAMID_LOTS,
    INTRADAY_PARTIAL_BOOK_PCT,
    INTRADAY_PYRAMID_ADD_LOTS,
    INTRADAY_PYRAMID_TRIGGER_POINTS,
    INTRADAY_SL_POINTS,
    INTRADAY_SQUARE_OFF_TIME,
    INTRADAY_TARGET_POINTS,
    INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS,
    LegState,
    IntradayPosition,
    create_position,
    evaluate_leg,
    evaluate_marks_parallel,
    evaluate_position,
    evaluate_positions,
    position_from_dict,
    position_to_dict,
    reconcile_intraday_book,
)

BASE = datetime(2026, 9, 23, 10, 0, tzinfo=IST_ZONE)
EOD = datetime(2026, 9, 23, 15, 29, tzinfo=IST_ZONE)
EOD_EARLY = datetime(2026, 9, 23, 15, 28, tzinfo=IST_ZONE)


def _make_leg(symbol="NIFTY24SEP24000CE", direction="LONG", entry=100.0, qty=50):
    return LegState(
        symbol=symbol,
        direction=direction,
        entry_price=round(entry, 2),
        initial_qty=qty,
        current_qty=qty,
        stop_price=round(entry - INTRADAY_SL_POINTS, 2) if direction == "LONG" else round(entry + INTRADAY_SL_POINTS, 2),
        target_price=round(entry + INTRADAY_TARGET_POINTS, 2) if direction == "LONG" else round(entry - INTRADAY_TARGET_POINTS, 2),
        peak_price=entry,
    )


def _make_position(index="NIFTY", direction="LONG", entry=100.0, qty=50, symbol="NIFTY24SEP24000CE"):
    stamp = BASE.date().isoformat()
    leg = _make_leg(symbol=symbol, direction=direction, entry=entry, qty=qty)
    return IntradayPosition(
        position_id=f"{stamp}-001-{index}-{direction}",
        index=index,
        direction=direction,
        legs=[leg],
        entry_time=BASE.isoformat(),
        remaining_qty=qty,
    )


class TestPositionCreation:
    def test_long_sl_and_target(self):
        p = _make_position(entry=100.0, qty=50)
        leg = p.legs[0]
        assert leg.stop_price == 80.0
        assert leg.target_price == 140.0

    def test_short_sl_and_target(self):
        p = _make_position(direction="SHORT", entry=120.0, qty=50)
        leg = p.legs[0]
        assert leg.stop_price == 140.0
        assert leg.target_price == 80.0


class TestInitialStopHit:
    def test_long_stop_closes_at_sl(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 79.0}, BASE)
        assert p.all_legs_closed()
        assert p.legs[0].exit_reason == "INITIAL_STOP"
        assert p.legs[0].exit_price == 79.0
        assert p.total_realized_pnl == pytest.approx(-1050.0, abs=1e-6)

    def test_short_stop_closes_at_sl(self):
        p = _make_position(direction="SHORT", entry=120.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 141.0}, BASE)
        assert p.all_legs_closed()
        assert p.legs[0].exit_reason == "INITIAL_STOP"
        assert p.legs[0].exit_price == 141.0
        assert p.total_realized_pnl == pytest.approx(-1050.0, abs=1e-6)

    def test_no_stop_above_level(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 81.0}, BASE)
        assert not p.any_leg_closed()


class TestTargetAndPartialBook:
    def test_single_quantity_target_closes_instead_of_leaving_zero_quantity_open(self):
        p = _make_position(entry=100.0, qty=1)
        evaluate_position(p, {p.legs[0].symbol: 140.0}, BASE)
        assert p.status == "CLOSED"
        assert p.legs[0].exit_reason == "TARGET"
        assert p.total_realized_pnl == 40.0

    def test_long_target_triggers_partial_book(self):
        p = _make_position(entry=100.0, qty=100)
        p = evaluate_position(p, {p.legs[0].symbol: 141.0}, BASE)
        leg = p.legs[0]
        assert leg.target_hit is True
        assert leg.partial_booked_qty == int(math.floor(100 * INTRADAY_PARTIAL_BOOK_PCT))
        assert leg.current_qty == 100 - leg.partial_booked_qty
        assert leg.stop_price == 121.0
        assert leg.trail_active is True

    def test_short_target_triggers_partial_book(self):
        p = _make_position(direction="SHORT", entry=120.0, qty=100)
        p = evaluate_position(p, {p.legs[0].symbol: 79.0}, BASE)
        leg = p.legs[0]
        assert leg.target_hit is True
        assert leg.partial_booked_qty == int(math.floor(100 * INTRADAY_PARTIAL_BOOK_PCT))
        assert leg.current_qty == 100 - leg.partial_booked_qty
        assert leg.stop_price == 99.0
        assert leg.trail_active is True


class TestTrailStopAfterPartialBook:
    def test_trail_sl_hit_after_partial(self):
        p = _make_position(entry=100.0, qty=100)
        p = evaluate_position(p, {p.legs[0].symbol: 141.0}, BASE)
        p = evaluate_position(p, {p.legs[0].symbol: 99.0}, BASE + timedelta(minutes=1))
        assert p.all_legs_closed()
        assert p.legs[0].exit_reason == "TRAIL_SL"
        assert p.legs[0].exit_price == 99.0

    def test_no_trail_below_breakeven_after_partial(self):
        p = _make_position(entry=100.0, qty=100)
        p = evaluate_position(p, {p.legs[0].symbol: 141.0}, BASE)
        p = evaluate_position(p, {p.legs[0].symbol: 121.5}, BASE + timedelta(minutes=1))
        assert not p.all_legs_closed()


class TestEodSquareOff:
    def test_eod_squares_off_open_position(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 105.0}, EOD)
        assert p.all_legs_closed()
        assert p.legs[0].exit_reason == "EOD_SQUAREOFF"
        assert p.legs[0].exit_price == 105.0
        assert p.legs[0].current_qty == 0

    def test_no_eod_before_time(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 105.0}, EOD_EARLY)
        assert not p.any_leg_closed()


class TestPyramiding:
    def test_target_then_later_pyramid_uses_actual_add_price(self):
        p = _make_position(entry=100.0, qty=50)
        symbol = p.legs[0].symbol
        evaluate_position(p, {symbol: 140.0}, BASE)
        assert p.pyramided_lots == 0
        assert p.legs[0].realized_pnl == 1000.0
        evaluate_position(p, {symbol: 160.0}, BASE + timedelta(minutes=1))
        assert p.pyramided_lots == 1
        assert p.legs[0].average_entry_price == 140.0
        assert p.legs[0].stop_price >= 140.0
        evaluate_position(p, {symbol: 160.0}, BASE + timedelta(minutes=2))
        assert p.pyramided_lots == 1
        evaluate_position(p, {symbol: 140.0}, BASE + timedelta(minutes=3))
        assert p.status == "CLOSED"
        assert p.total_realized_pnl == 1000.0

    def test_pyramid_adds_lot_after_trigger(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 161.0}, BASE)
        leg = p.legs[0]
        assert leg.pyramided_qty == INTRADAY_PYRAMID_ADD_LOTS * leg.initial_qty
        assert leg.target_hit is True
        assert leg.partial_booked_qty > 0
        assert leg.current_qty == leg.initial_qty + leg.pyramided_qty - leg.partial_booked_qty
        assert p.pyramided_lots == 1

    def test_pyramid_respects_max_lots(self):
        p = _make_position(entry=100.0, qty=50)
        for pts in [161.0, 181.0, 201.0, 221.0]:
            p = evaluate_position(p, {p.legs[0].symbol: pts}, BASE + timedelta(minutes=1))
        assert p.pyramided_lots <= INTRADAY_MAX_PYRAMID_LOTS - 1
        assert p.legs[0].current_qty <= INTRADAY_MAX_PYRAMID_LOTS * p.legs[0].initial_qty


class TestParallelEvaluation:
    def test_parallel_evaluation_independent(self):
        p1 = _make_position(index="NIFTY", entry=100.0, qty=50, symbol="LEG1")
        p2 = _make_position(index="BANKNIFTY", entry=200.0, qty=30, symbol="LEG2")
        marks = {"LEG1": 141.0, "LEG2": 80.0}
        results = evaluate_marks_parallel([p1, p2], marks, BASE)
        assert len(results) == 2
        r1 = next(r for r in results if r.index == "NIFTY")
        r2 = next(r for r in results if r.index == "BANKNIFTY")
        assert r1.legs[0].target_hit is True
        assert r2.all_legs_closed()
        assert r2.legs[0].exit_reason == "INITIAL_STOP"


class TestSerialization:
    def test_round_trip_position(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 141.0}, BASE)
        d = position_to_dict(p)
        restored = position_from_dict(d, sequence=1)
        assert restored is not None
        assert restored.legs[0].target_hit is True
        assert restored.legs[0].stop_price == 121.0

    def test_book_reconcile_persists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_OPTIONS_INTRADAY_BOOK_FILE", str(tmp_path / "book.json"))
        book = {
            "sessionDate": BASE.date().isoformat(),
            "open": [],
            "closed": [],
            "entryCount": 0,
        }
        row = {
            "id": "2026-09-23-001-NIFTY-LONG",
            "positionId": "2026-09-23-001-NIFTY-LONG",
            "index": "NIFTY",
            "key": "NIFTY",
            "direction": "LONG",
            "status": "OPEN",
            "exitReason": "",
            "pnl": 0.0,
            "realizedPnl": 0.0,
            "remainingQty": 50,
            "pyramidedLots": 0,
            "legs": [
                {
                    "symbol": "NIFTY24SEP24000CE",
                    "direction": "LONG",
                    "entryPrice": 100.0,
                    "qty": 50,
                    "initialQty": 50,
                    "pyramidedQty": 0,
                    "partialBookedQty": 0,
                    "stopPrice": 80.0,
                    "targetPrice": 140.0,
                    "peakPrice": 100.0,
                    "mfePoints": 0.0,
                    "targetHit": False,
                    "trailActive": False,
                    "closed": False,
                    "exitReason": "",
                    "exitPrice": 0.0,
                    "realizedPnl": 0.0,
                    "minuteMarks": [],
                }
            ],
            "strategyMode": "INTRADAY_PYRAMID",
            "strategyType": "LONG_PREMIUM_PYRAMID",
            "policyVersion": "intraday_20sl_40target_pyramid_v1",
            "entryTime": BASE.isoformat(),
        }
        book["open"] = [row]
        out = reconcile_intraday_book(book, {"NIFTY24SEP24000CE": 141.0}, now=BASE, persist=True, book_path=tmp_path / "book.json")
        assert len(out["open"]) == 1
        assert out["open"][0]["legs"][0]["targetHit"] is True
        assert out["open"][0]["remainingQty"] < 50


class TestEdgeCases:
    def test_negative_quantity_never_fabricates(self):
        p = _make_position(entry=100.0, qty=0)
        assert p.legs[0].current_qty == 0

    def test_zero_mark_skips_evaluation(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {p.legs[0].symbol: 0.0}, BASE)
        assert not p.any_leg_closed()

    def test_missing_mark_skips_evaluation(self):
        p = _make_position(entry=100.0, qty=50)
        p = evaluate_position(p, {}, BASE)
        assert not p.any_leg_closed()
