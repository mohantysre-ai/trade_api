from datetime import datetime, timedelta

import pytest

from app.services.angel_index_options import IST_ZONE
from app.services.angel_index_stream import ANGEL_INDEX_STREAM
from app.services.index_options_engine import build_index_options_radar
from app.services.index_options_paper import (
    EXITED_LIVE_AT_EOD,
    RECOVERED_AFTER_EOD,
    EOD_PRICE_UNAVAILABLE,
    reconcile_paper_book,
    SELLER_SQUARE_OFF_TIME,
)
from app.services.index_options_paper_supervisor import run_paper_supervisor_cycle, _session_active
from app.services.index_options_seller import (
    MIN_CREDIT_TO_RISK,
    MIN_CREDIT_TO_RISK_CHEAP_VOL,
    MIN_IV_EDGE_POINTS,
    MIN_IV_EDGE_RATIO,
    build_defined_risk_seller_setup,
)


def _contract(option_type, strike, delta, bid, ask, *, lot=75, iv=20.0):
    suffix = "CE" if option_type == "CALL" else "PE"
    mid = ((bid or 0) + (ask or 0)) / 2.0 if (bid is not None or ask is not None) else 0.0
    return {
        "symbol": f"NIFTY01SEP26{int(strike)}{suffix}", "token": f"{suffix}-{strike}", "exchange": "NFO",
        "optionType": option_type, "strike": strike, "delta": delta,
        "gamma": 0.0005 if abs(delta) < 0.15 else 0.001,
        "theta": -2.0 if abs(delta) < 0.15 else -5.0,
        "vega": 2.0 if abs(delta) < 0.15 else 3.0, "iv": iv, "ltp": mid,
        "close": max(3.0, mid),
        "bestBid": bid, "bestAsk": ask, "volume": 100_000, "oi": 500_000,
        "oiChange": 25_000, "lotSize": lot,
    }


def _chain(**kwargs):
    return [
        _contract("PUT", 90, -0.10, 0.60, 0.61, **kwargs),
        _contract("PUT", 95, -0.25, 2.80, 2.82, **kwargs),
        _contract("PUT", 100, -0.50, 4.80, 4.84, **kwargs),
        _contract("CALL", 100, 0.50, 4.80, 4.84, **kwargs),
        _contract("CALL", 105, 0.25, 2.80, 2.82, **kwargs),
        _contract("CALL", 110, 0.10, 0.60, 0.61, **kwargs),
    ]


def _seller(chain=None, **kwargs):
    defaults = {
        "structure": {"status": "NO_BREAKOUT", "direction": None, "last": 100, "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27},
        "breadth_neutral": {"status": "LIVE", "score": 0.02, "coveragePct": 100.0},
        "breadth_directional": {"status": "LIVE", "score": 0.60, "directionalScore": 0.60, "coveragePct": 100.0},
        "futures_oi": {"state": "LONG_UNWINDING", "priceChangePct": 0.10, "oiChangePct": -2.0},
        "directional_oi_aligned": True,
        "vix": 12.0, "vix_regime": "CALM", "provider_live": True,
        "now": datetime(2026, 8, 31, 11, 0, tzinfo=IST_ZONE),
    }
    defaults.update(kwargs)
    return build_defined_risk_seller_setup(
        chain=chain or _chain(), spot=100, expiry_value="2026-09-01", **defaults
    )


class TestFix1SpreadAwareShortWithWing:
    def test_lowest_delta_short_without_hedge_falls_back_to_valid_hedge(self):
        chain = [
            _contract("PUT", 95, -0.25, 2.80, 2.82),
            _contract("PUT", 97, -0.30, 1.50, 1.52),
            _contract("PUT", 100, -0.50, 4.80, 4.84),
            _contract("CALL", 100, 0.50, 4.80, 4.84),
            _contract("CALL", 105, 0.25, 2.80, 2.82),
            _contract("CALL", 110, 0.10, 0.60, 0.61),
        ]
        setup = _seller(chain=chain, structure={"status": "CONFIRMED", "direction": "CALL", "last": 104, "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27})
        assert setup is not None
        assert setup["strategyType"] == "BULL_PUT_CREDIT_SPREAD"
        short_put = next(leg for leg in setup["legs"] if leg["role"] == "SHORT_PUT")
        assert short_put["strike"] == 97

    def test_hedge_wing_without_executable_ask_is_rejected(self):
        chain = [
            _contract("PUT", 90, -0.10, 0.60, 0.61),
            _contract("PUT", 95, -0.25, 2.80, 2.82),
            _contract("PUT", 100, -0.50, 4.80, 4.84),
            _contract("CALL", 100, 0.50, 4.80, 4.84),
            _contract("CALL", 105, 0.25, 2.80, 2.82),
            _contract("CALL", 108, 0.30, None, None),
            _contract("CALL", 110, 0.10, None, None),
        ]
        setup = _seller(chain=chain, structure={"status": "CONFIRMED", "direction": "PUT", "last": 96, "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27})
        assert setup["constructionStatus"] == "CALL_HEDGE_WING_UNAVAILABLE"

    def test_hedge_wing_spread_too_wide_is_rejected(self):
        chain = [
            _contract("PUT", 90, -0.10, 0.60, 0.61),
            _contract("PUT", 95, -0.25, 2.80, 2.82),
            _contract("PUT", 100, -0.50, 4.80, 4.84),
            _contract("CALL", 100, 0.50, 4.80, 4.84),
            _contract("CALL", 105, 0.25, 2.80, 2.82),
            _contract("CALL", 110, 0.10, 0.60, 0.61),
        ]
        for row in chain:
            if row["optionType"] == "CALL" and row["strike"] == 110:
                row["bestBid"] = 0.60
                row["bestAsk"] = 0.70
        setup = _seller(chain=chain, structure={"status": "CONFIRMED", "direction": "PUT", "last": 96, "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27})
        assert setup["constructionStatus"] == "CALL_HEDGE_WING_UNAVAILABLE"


class TestFix2CheapVolatilityRegime:
    def test_negative_iv_edge_low_vix_disables_seller_when_compensation_insufficient(self):
        import app.services.index_options_seller as seller_mod
        original_spread = seller_mod.MAX_LEG_SPREAD_PCT
        original_hedge = seller_mod.MAX_HEDGE_SPREAD_PCT
        original_cost = seller_mod.ESTIMATED_COST_PER_ORDER_INR
        try:
            seller_mod.MAX_LEG_SPREAD_PCT = 100.0
            seller_mod.MAX_HEDGE_SPREAD_PCT = 100.0
            seller_mod.ESTIMATED_COST_PER_ORDER_INR = 0.0
            low_credit_chain = [
                _contract("PUT", 95, -0.25, 0.10, 0.15, iv=11.0),
                _contract("PUT", 90, -0.10, 0.05, 0.08, iv=11.0),
                _contract("CALL", 105, 0.25, 0.10, 0.15, iv=11.0),
                _contract("CALL", 110, 0.10, 0.05, 0.08, iv=11.0),
            ]
            setup = _seller(vix=12.0, chain=low_credit_chain, structure={
                "status": "NO_BREAKOUT", "direction": None, "last": 100,
                "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
            })
            assert setup.get("constructionStatus") is None
            assert setup["gates"]["volatilityEdge"] is False
            assert setup["gateEvidence"]["volatilityEdge"]["regime"] == "CHEAP_VOLATILITY_DISABLED"
            assert setup["gateEvidence"]["volatilityEdge"]["reason"] == "INSUFFICIENT_EXPECTED_COMPENSATION"
        finally:
            seller_mod.MAX_LEG_SPREAD_PCT = original_spread
            seller_mod.MAX_HEDGE_SPREAD_PCT = original_hedge
            seller_mod.ESTIMATED_COST_PER_ORDER_INR = original_cost

    def test_negative_iv_edge_low_vix_requires_stronger_evidence_when_compensation_sufficient(self):
        setup = _seller(vix=12.0, chain=_chain(iv=11.0), structure={
            "status": "NO_BREAKOUT", "direction": None, "last": 100,
            "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
        })
        assert setup["gateEvidence"]["volatilityEdge"]["regime"] == "CHEAP_VOLATILITY_STRONGER_GATE"
        assert setup["gateEvidence"]["volatilityEdge"]["minimumEdgePoints"] == MIN_IV_EDGE_POINTS * 2.0

    def test_low_vix_positive_edge_uses_normal_thresholds(self):
        setup = _seller(vix=12.0, chain=_chain(iv=14.0), structure={
            "status": "NO_BREAKOUT", "direction": None, "last": 100,
            "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
        })
        assert setup["gateEvidence"]["volatilityEdge"]["regime"] == "LOW_VIX_POSITIVE_EDGE_NO_RELAXATION"
        assert setup["gateEvidence"]["volatilityEdge"]["minimumEdgePoints"] == 0.75

    def test_vix_above_15_uses_normal_thresholds(self):
        setup = _seller(vix=18.0, structure={
            "status": "NO_BREAKOUT", "direction": None, "last": 100,
            "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
        })
        assert setup["gateEvidence"]["volatilityEdge"]["regime"] == "NORMAL"
        assert setup["gateEvidence"]["volatilityEdge"]["minimumEdgePoints"] == 0.75

    def test_credit_risk_boundary_cases(self):
        import app.services.index_options_seller as seller_mod
        original_spread = seller_mod.MAX_LEG_SPREAD_PCT
        original_hedge = seller_mod.MAX_HEDGE_SPREAD_PCT
        original_cost = seller_mod.ESTIMATED_COST_PER_ORDER_INR
        try:
            seller_mod.MAX_LEG_SPREAD_PCT = 100.0
            seller_mod.MAX_HEDGE_SPREAD_PCT = 100.0
            seller_mod.ESTIMATED_COST_PER_ORDER_INR = 0.0
            def make_chain(short_bid, short_ask):
                return [
                    _contract("PUT", 95, -0.25, short_bid, short_ask, iv=11.0),
                    _contract("PUT", 90, -0.10, 0.05, 0.08, iv=11.0),
                    _contract("CALL", 105, 0.25, short_bid, short_ask, iv=11.0),
                    _contract("CALL", 110, 0.10, 0.05, 0.08, iv=11.0),
                ]

            below_chain = make_chain(0.10, 0.12)
            setup_below = _seller(vix=12.0, chain=below_chain, structure={
                "status": "NO_BREAKOUT", "direction": None, "last": 100,
                "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
            })
            assert setup_below.get("constructionStatus") is None
            assert setup_below["gates"]["volatilityEdge"] is False
            assert setup_below["gateEvidence"]["volatilityEdge"]["regime"] == "CHEAP_VOLATILITY_DISABLED"

            above_chain = make_chain(0.50, 0.55)
            setup_above = _seller(vix=12.0, chain=above_chain, structure={
                "status": "NO_BREAKOUT", "direction": None, "last": 100,
                "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
            })
            assert setup_above.get("constructionStatus") is None
            assert setup_above["gateEvidence"]["volatilityEdge"]["regime"] == "CHEAP_VOLATILITY_STRONGER_GATE"
        finally:
            seller_mod.MAX_LEG_SPREAD_PCT = original_spread
            seller_mod.MAX_HEDGE_SPREAD_PCT = original_hedge
            seller_mod.ESTIMATED_COST_PER_ORDER_INR = original_cost


class TestFix3EODExitStateTracking:
    def test_ui_evidence_reports_effective_thresholds(self):
        setup = _seller(vix=12.0, chain=_chain(iv=11.0), structure={
            "status": "NO_BREAKOUT", "direction": None, "last": 100,
            "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
        })
        vol_evidence = setup["gateEvidence"]["volatilityEdge"]
        assert "minimumEdgePoints" in vol_evidence
        assert "minimumIvToVix" in vol_evidence
        assert "minimumCreditToRisk" in vol_evidence
        assert vol_evidence["minimumEdgePoints"] != 0.75

    def test_restart_at_1525_closes_with_exited_live_at_eod(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
        setup = _seller()
        supplied = {"spot": 100, "source": "ANGEL_ONE", "providerStatus": "LIVE", "expiry": "2026-09-01",
                    "rawChain": _chain(), "seller": setup}
        radar = build_index_options_radar({"indexOptions": {"indices": {"NIFTY": supplied}}})
        entry_now = datetime(2026, 8, 31, 11, 0, tzinfo=IST_ZONE)
        book = reconcile_paper_book(radar, now=entry_now)
        assert book["entryCount"] == 1
        assert len(book["open"]) == 1

        close_now = datetime(2026, 8, 31, 15, 25, tzinfo=IST_ZONE)
        book = reconcile_paper_book(radar, now=close_now)
        assert book["open"] == []
        assert book["closed"][0]["exitReason"] == "EOD_GAMMA_SQUAREOFF"
        assert book["closed"][0].get("eodExitState") == EXITED_LIVE_AT_EOD

    def test_restart_at_2236_closes_with_recovered_after_eod(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
        now = datetime(2026, 8, 31, 22, 36, tzinfo=IST_ZONE)
        assert _session_active(now) is False
        book = run_paper_supervisor_cycle(None, now=now, eod_exit_state=RECOVERED_AFTER_EOD)
        assert book["closed"] == []

    def test_saturday_restart_does_not_fabricate_friday_execution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
        friday = datetime(2026, 9, 4, 22, 36, tzinfo=IST_ZONE)
        assert friday.weekday() == 4
        book = run_paper_supervisor_cycle(None, now=friday, eod_exit_state=RECOVERED_AFTER_EOD)
        assert book["closed"] == []
        assert book["open"] == []

    def test_sunday_restart_does_not_fabricate_friday_execution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
        sunday = datetime(2026, 9, 6, 22, 36, tzinfo=IST_ZONE)
        assert sunday.weekday() == 6
        book = run_paper_supervisor_cycle(None, now=sunday, eod_exit_state=RECOVERED_AFTER_EOD)
        assert book["closed"] == []
        assert book["open"] == []

    def test_repeated_restart_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
        now = datetime(2026, 8, 31, 22, 36, tzinfo=IST_ZONE)
        book1 = run_paper_supervisor_cycle(None, now=now, eod_exit_state=RECOVERED_AFTER_EOD)
        book2 = run_paper_supervisor_cycle(None, now=now + timedelta(minutes=1), eod_exit_state=RECOVERED_AFTER_EOD)
        assert len(book1.get("closed", [])) == len(book2.get("closed", []))

    def test_missing_stale_marks_do_not_manufacture_exit_price(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
        now = datetime(2026, 8, 31, 11, 0, tzinfo=IST_ZONE)
        row = {"key": "NIFTY", "bucket": "FINANCIAL", "direction": "PUT", "state": "ELIGIBLE", "score": 95.0,
               "contract": {"symbol": "NIFTYTEST", "strike": 100, "expiry": "2026-09-01", "ltp": 100, "lotSize": 75,
                            "token": "12345", "exchange": "NFO"}, "chain": [], "dataSource": "ANGEL_ONE",
               "gateEvidence": {"riskReward": {"expectedR": 2.0}}}
        book = reconcile_paper_book({"candidates": [row], "selected": [row]}, now=now)
        assert len(book["open"]) == 1
        position = book["open"][0]
        assert position.get("eodExitState") is None
