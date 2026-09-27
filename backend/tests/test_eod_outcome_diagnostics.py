"""EOD outcome diagnostics: MAE/MFE, root cause, and R must survive every book path.

Guards three regressions:
1. A book row without a ``missDiagnostic`` renders a blank Why (root), because the
   UI reads root cause only from the diagnostic.
2. Book-specific exit reasons (``STOP_LOSS_FILLED``) are not in the taxonomy
   vocabulary, so classification silently fell through to ``UNKNOWN``.
3. Economic R computed from a trailed stop is wrong; R must use original risk.
"""
import json
from datetime import date

import pytest

from app.services import eod_book_cache
from app.services.quant_desk_exit_policy import (
    build_trade_outcome,
    canonical_exit_reason,
    classify_taxonomy,
    desk_exit_label,
    desk_miss_diagnostic,
)


V2_REASON_ALIASES = {
    "STOP_LOSS_FILLED": "SL_HIT",
    "STOP_FILLED": "SL_HIT",
    "TRAIL_STOP_FILLED": "TRAIL_SL_HIT",
    "TIME_EXIT_FILLED": "EOD_SQUAREOFF",
    "T1_FILLED": "T1_HIT",
    "T2_FILLED": "T2_HIT",
}


@pytest.mark.parametrize("raw,expected", sorted(V2_REASON_ALIASES.items()))
def test_canonical_exit_reason_maps_book_vocabulary(raw, expected):
    assert canonical_exit_reason(raw) == expected


@pytest.mark.parametrize("raw,expected", sorted(V2_REASON_ALIASES.items()))
def test_book_exit_reason_never_classifies_as_unknown(raw, expected):
    root, factors = classify_taxonomy(
        execution_status="FILLED", exit_reason=raw, pnl=0.5, mfe_r=0.4
    )
    assert root != "UNKNOWN"
    assert factors


def test_stop_loss_with_partial_excursion_is_failed_followthrough():
    root, factors = classify_taxonomy(
        execution_status="FILLED", exit_reason="STOP_LOSS_FILLED", pnl=-1.12, mfe_r=0.34
    )
    assert root == "FAILED_FOLLOWTHROUGH"
    assert "STOP_HIT" in factors


def test_trail_stop_capturing_gains_is_trail_captured():
    root, factors = classify_taxonomy(
        execution_status="FILLED", exit_reason="TRAIL_STOP_FILLED", pnl=0.36, mfe_r=1.17
    )
    assert root == "TRAIL_CAPTURED"
    assert "TRAIL_LOCKED_GAINS" in factors


def test_time_exit_without_followthrough_is_stall():
    root, _ = classify_taxonomy(
        execution_status="FILLED", exit_reason="TIME_EXIT_FILLED", pnl=-0.72, mfe_r=0.22
    )
    assert root == "STALL"


def test_desk_exit_label_uses_canonical_vocabulary():
    assert desk_exit_label("STOP_LOSS_FILLED", -1.0) == "INITIAL_SL"
    assert desk_exit_label("TIME_EXIT_FILLED", -1.0) == "EOD_SQUAREOFF"
    assert desk_exit_label("TRAIL_STOP_FILLED", 0.3) == "TRAIL_STOP"


def test_diagnostic_carries_root_cause_and_excursion():
    desk = build_trade_outcome(
        triggered=True,
        realized_pnl=-1.12,
        exit_reason="STOP_LOSS_FILLED",
        entry=100.0,
        exit_price=98.0,
        risk_per_share=2.0,
        qty=10,
    )
    diag = desk_miss_diagnostic(desk, move_pct=-1.75)

    assert diag["rootCause"] == desk["rootCause"]
    assert diag["rootCause"] is not None
    assert diag["maeR"] == desk["maeR"]
    assert diag["mfeR"] == desk["mfeR"]
    assert diag["movePct"] == -1.75
    assert isinstance(diag["factors"], list)
    assert diag["source"] == "BOOK"


def test_ledger_excursion_is_reused_not_re_derived():
    """A position carrying maeR/mfeR must not have them recomputed from one close."""
    position = {
        "mfeR": 1.17,
        "maeR": -0.232,
        "riskPerShare": 99.1857,
    }
    desk = build_trade_outcome(
        triggered=True,
        realized_pnl=462.16,
        exit_reason="TRAIL_STOP_FILLED",
        exit_state=position,
        entry=8347.0,
        exit_price=8353.997692307692,
        risk_per_share=99.1857,
        qty=13,
    )

    assert desk["mfeR"] == pytest.approx(1.17, abs=1e-3)
    assert desk["maeR"] == pytest.approx(-0.232, abs=1e-3)


def test_economic_r_uses_original_risk_not_trailing_stop():
    """Trailing stop must never inflate R; original risk is the denominator."""
    position = {"mfeR": 1.17, "maeR": -0.232, "riskPerShare": 99.1857}
    desk = build_trade_outcome(
        triggered=True,
        realized_pnl=462.16,
        exit_reason="TRAIL_STOP_FILLED",
        exit_state=position,
        entry=8347.0,
        exit_price=8353.997692307692,
        risk_per_share=99.1857,
        qty=13,
        effective_stop=8353.997692307692,
    )

    assert desk["economicR"] == pytest.approx(0.358, abs=0.001)


def test_book_cache_coerces_rupee_formatted_values_on_read(tmp_path, monkeypatch):
    monkeypatch.setattr(eod_book_cache, "book_cache_path", lambda *_a, **_k: str(tmp_path / "book_swing.json"))
    (tmp_path / "book_swing.json").write_text(
        json.dumps({
            "bookCacheSchemaVersion": eod_book_cache.BOOK_CACHE_SCHEMA_VERSION,
            "picks": [{
                "symbol": "AUROPHARMA",
                "currentPrice": "₹1,734.50",
                "entryPrice": "1730.8",
                "exitPrice": "1,703.65",
                "pnl": -882.35,
                "deployedCapital": "₹50,300.50",
            }],
        }),
        encoding="utf-8",
    )

    cached = eod_book_cache.load_book_cache(date(2026, 9, 25), "swing")
    row = cached["picks"][0]

    assert row["currentPrice"] == pytest.approx(1734.5)
    assert row["entryPrice"] == pytest.approx(1730.8)
    assert row["exitPrice"] == pytest.approx(1703.65)
    assert row["deployedCapital"] == pytest.approx(50300.5)
    assert isinstance(row["pnl"], float)


def test_book_cache_leaves_native_numbers_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(eod_book_cache, "book_cache_path", lambda *_a, **_k: str(tmp_path / "book_swing.json"))
    (tmp_path / "book_swing.json").write_text(
        json.dumps({
            "bookCacheSchemaVersion": eod_book_cache.BOOK_CACHE_SCHEMA_VERSION,
            "picks": [{"symbol": "POLYCAB", "exitPrice": 8353.997692307692, "pnl": 462.16}],
        }),
        encoding="utf-8",
    )

    row = eod_book_cache.load_book_cache(date(2026, 9, 25), "swing")["picks"][0]

    assert row["exitPrice"] == 8353.997692307692
    assert row["pnl"] == 462.16


def test_unparseable_text_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(eod_book_cache, "book_cache_path", lambda *_a, **_k: str(tmp_path / "book_swing.json"))
    (tmp_path / "book_swing.json").write_text(
        json.dumps({
            "bookCacheSchemaVersion": eod_book_cache.BOOK_CACHE_SCHEMA_VERSION,
            "picks": [{"symbol": "X", "executionStatus": "FILLED", "currentPrice": "N/A"}],
        }),
        encoding="utf-8",
    )

    row = eod_book_cache.load_book_cache(date(2026, 9, 25), "swing")["picks"][0]

    assert row["currentPrice"] is None
    assert row["executionStatus"] == "FILLED"
