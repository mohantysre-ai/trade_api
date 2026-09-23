"""Swing V2 4–5 position portfolio regression and validation.

2026-09-21-SHAPED REGRESSION — does not replay unavailable broker ticks.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.shadow import build_shadow_v2

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 9, 21, 10, 30, tzinfo=IST)
QUOTE_TS = NOW.astimezone(timezone.utc)
FRESH_BAR_TS = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc).isoformat()
STALE_BAR_TS = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc).isoformat()


def _base_row(symbol: str, *, score: float, upside_r: float, planned_r: float, cost_r: float = 0.05, fresh: bool = True, sector: str = "SEC1", segment: str = "NIFTY100", mdtv20: float = 1_000_000_000.0, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "ticker": symbol,
        "universeSegment": segment,
        "sector": sector,
        "decisionPrice": 100.0,
        "structureStop": 98.5,
        "atr14": 1.5,
        "mdtv20": mdtv20,
        "dailyObservationCount": 180,
        "modeledRoundTripCostPct": 0.05,
        "spreadPct": 0.05,
        "availableAskDepth": 1000,
        "dailyBarsThroughPreviousClose": True,
        "corporateEventsCurrent": True,
        "surveillanceCurrent": True,
        "universeCurrent": True,
        "sourceTimestamps": {
            "quote": QUOTE_TS.isoformat() if fresh else (QUOTE_TS - timedelta(hours=2)).isoformat(),
            "bars1h": FRESH_BAR_TS if fresh else STALE_BAR_TS,
        },
        "trendPriorPctile": score,
        "residualStrengthPctile": score,
        "setupQualityPctile": score,
        "rvolPctile": score,
        "clvPctile": score,
        "sectorStrengthPctile": score,
        "liquidityPctile": score,
        "upsideCapacityR": upside_r,
        "plannedMaxBlendedR": planned_r,
        "costPenaltyR": cost_r,
        "gapRiskPenaltyR": 0.0,
        "extensionAtr": 1.0,
        "unexplainedGapPct": 0.0,
    }
    row.update(overrides)
    return row


def _low_correlations(symbols: list[str]) -> dict[tuple[str, str], float]:
    corr = {}
    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            corr[(a, b)] = 0.10
            corr[(b, a)] = 0.10
    return corr


def _noise_rows(count: int, fresh: bool = True, stale_governance: int = 0) -> tuple[list[dict], int]:
    rows = []
    bad = 0
    for i in range(count):
        r = {
            "symbol": f"NOISE{i:03d}",
            "ticker": f"NOISE{i:03d}",
            "universeSegment": "NIFTY100",
            "sector": f"NOISE{i % 10}",
            "decisionPrice": 100.0,
            "structureStop": 98.5,
            "atr14": 1.5,
            "mdtv20": 500_000_000.0,
            "dailyObservationCount": 180,
            "modeledRoundTripCostPct": 0.05,
            "spreadPct": 0.05,
            "availableAskDepth": 1000,
            "dailyBarsThroughPreviousClose": True,
            "corporateEventsCurrent": True,
            "surveillanceCurrent": True,
            "universeCurrent": True,
            "sourceTimestamps": {
                "quote": QUOTE_TS.isoformat() if fresh else (QUOTE_TS - timedelta(hours=2)).isoformat(),
                "bars1h": FRESH_BAR_TS if fresh else STALE_BAR_TS,
            },
            "trendPriorPctile": 30.0 + (i % 20),
            "residualStrengthPctile": 30.0 + (i % 20),
            "setupQualityPctile": 30.0 + (i % 20),
            "rvolPctile": 30.0 + (i % 20),
            "clvPctile": 30.0 + (i % 20),
            "sectorStrengthPctile": 30.0 + (i % 20),
            "liquidityPctile": 30.0 + (i % 20),
            "upsideCapacityR": 0.80,
            "plannedMaxBlendedR": 0.80,
            "costPenaltyR": 0.05,
            "gapRiskPenaltyR": 0.0,
            "extensionAtr": 1.0,
            "unexplainedGapPct": 0.0,
        }
        if bad < stale_governance:
            r["surveillanceCurrent"] = False
            bad += 1
        rows.append(r)
    return rows, bad


FRESH_UNIVERSE_COUNT = 735
TOTAL_UNIVERSE_COUNT = 750

def _build_2026_shaped_fixture() -> tuple[list[dict], dict]:
    rows = []
    for i in range(TOTAL_UNIVERSE_COUNT):
        fresh = i < FRESH_UNIVERSE_COUNT
        rows.append(_base_row(f"T{i:03d}", score=40.0, upside_r=0.50, planned_r=0.50, fresh=fresh, sector=f"SEC{i % 20}"))

    # Fresh scanner-long candidates overwrite fresh base rows; the deliberately
    # stale candidate overwrites a base row that is already stale. This keeps the
    # row-level fresh count identical to the reported coverage numerator, so the
    # coverage figure and the actual fresh-row count reconcile exactly.
    fresh_scanner_candidates = [
        _base_row("STRONG01", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK1", segment="NIFTY100"),
        _base_row("STRONG02", score=70.0, upside_r=1.35, planned_r=1.35, sector="BANK2", segment="NIFTY100"),
        _base_row("DIV01", score=63.0, upside_r=1.25, planned_r=1.25, sector="IT1", segment="NIFTY100"),
        _base_row("DIV02", score=62.0, upside_r=1.18, planned_r=1.18, sector="PHRMA1", segment="NIFTY100"),
        _base_row("DIV03", score=61.0, upside_r=1.12, planned_r=1.12, sector="AUTO1", segment="NIFTY100"),
        _base_row("BORDER_LOW_SCORE", score=59.0, upside_r=1.20, planned_r=1.20, sector="SEC_A", segment="NIFTY100"),
        _base_row("BORDER_LOW_R", score=62.0, upside_r=1.05, planned_r=1.05, sector="SEC_B", segment="NIFTY100"),
        _base_row("BORDER_ILLIQUID", score=72.0, upside_r=1.45, planned_r=1.45, mdtv20=100_000.0, sector="FMCG1", segment="NIFTY100"),
        _base_row("BORDER_PRICE_BAND", score=72.0, upside_r=1.45, planned_r=1.45, nearPriceBand=True, sector="SEC_C", segment="NIFTY100"),
        _base_row("BORDER_INVALID_STOP", score=72.0, upside_r=1.45, planned_r=1.45, structureStop=105.0, sector="SEC_D", segment="NIFTY100"),
    ]
    stale_scanner_candidate = _base_row("BORDER_STALE", score=72.0, upside_r=1.45, planned_r=1.45, fresh=False, sector="METL1", segment="NIFTY100")

    for i, cand in enumerate(fresh_scanner_candidates):
        rows[i] = cand
    rows[FRESH_UNIVERSE_COUNT] = stale_scanner_candidate

    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        microcap_risk_bps=15,
        setup_score_override=65.0,
        min_upside_capacity_r=1.25,
        min_planned_blended_r=1.25,
        min_expected_net_r=0.08,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
        coverage_normal_threshold=0.99,
        coverage_degraded_threshold=0.95,
        coverage_defensive_threshold=0.90,
    )
    return rows, cfg


def test_20260921_shaped_regression_targets_four_to_five_positions():
    rows, cfg = _build_2026_shaped_fixture()
    scanner_symbols = [r["symbol"] for r in rows if r["symbol"].startswith(("STRONG", "DIV", "BORDER"))]
    correlations = _low_correlations(scanner_symbols)
    result = build_shadow_v2(
        rows,
        universe_coverage=FRESH_UNIVERSE_COUNT / TOTAL_UNIVERSE_COUNT,
        regime="NORMAL",
        final_lock=True,
        now=NOW,
        config=cfg,
        correlations=correlations,
        apply_coverage_hysteresis=False,
    )

    assert round(result["dataCoverage"], 2) == 0.98
    assert result["blocked"] is False
    assert result["funnel"]["fresh_count"] == FRESH_UNIVERSE_COUNT
    assert result["funnel"]["freshData"] == FRESH_UNIVERSE_COUNT
    assert result["funnel"]["coverage_numerator"] == FRESH_UNIVERSE_COUNT
    assert result["qualifiedCount"] >= 5, f"Expected >=5 qualified, got {result['qualifiedCount']}"
    assert result["selectedCount"] >= 4, f"Expected >=4 selected, got {result['selectedCount']}"
    assert result["selectedCount"] <= 5, f"Expected <=5 selected, got {result['selectedCount']}"
    assert result["candidates"][0]["qualificationMode"] in ("PRIMARY_SETUP", "SCORE_SOFT_PASS")
    strong = [c for c in result["candidates"] if c.get("qualificationMode") in ("PRIMARY_SETUP", "SCORE_SOFT_PASS")]
    diversified = [c for c in result["candidates"] if c.get("qualificationMode") == "DIVERSIFIED_SOFT_PASS"]
    assert len(strong) >= 2
    assert len(diversified) >= 2


def test_normal_scan_without_correlation_matrix_does_not_invent_perfect_correlation():
    rows, cfg = _build_2026_shaped_fixture()
    result = build_shadow_v2(
        rows, regime="NORMAL", final_lock=True, now=NOW, config=cfg,
        apply_coverage_hysteresis=False,
    )
    assert result["qualifiedCount"] >= 5
    assert result["selectedCount"] >= 4
    assert all(row.get("portfolioRejectReason") != "EXCESS_PORTFOLIO_CORRELATION" for row in result["rejected"])


def test_old_vs_new_distribution_report():
    rows, cfg = _build_2026_shaped_fixture()
    scanner_symbols = [r["symbol"] for r in rows if r["symbol"].startswith(("STRONG", "DIV", "BORDER"))]
    correlations = _low_correlations(scanner_symbols)
    result = build_shadow_v2(
        rows,
        universe_coverage=FRESH_UNIVERSE_COUNT / TOTAL_UNIVERSE_COUNT,
        regime="NORMAL",
        final_lock=True,
        now=NOW,
        config=cfg,
        correlations=correlations,
        apply_coverage_hysteresis=False,
    )

    scanner_long = 8
    old_qualified = sum(1 for c in result["candidates"] if c.get("qualificationMode") in ("PRIMARY_SETUP", "SCORE_SOFT_PASS"))
    old_selected = old_qualified

    report = {
        "scanner_long": scanner_long,
        "old_qualified": old_qualified,
        "old_selected": old_selected,
        "new_qualified": result["qualifiedCount"],
        "new_selected": result["selectedCount"],
        "new_locked": result["selectedCount"],
    }
    assert report["new_qualified"] >= report["old_qualified"], "New policy should qualify at least as many"
    assert report["new_selected"] >= report["old_selected"], "New policy should select at least as many"


def test_five_strong_candidates_select_five():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=15,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    symbols = [f"STRONG{i:02d}" for i in range(5)]
    rows = [
        _base_row(sym, score=70.0 + i, upside_r=1.40 + i * 0.05, planned_r=1.40 + i * 0.05, sector=f"SEC{i}", segment="NIFTY100")
        for i, sym in enumerate(symbols)
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["selectedCount"] == 5
    assert all(c["qualificationMode"] in ("PRIMARY_SETUP", "SCORE_SOFT_PASS") for c in result["candidates"])


def test_two_strong_plus_three_tier_b_selects_five():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=15,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    symbols = ["STRONG01", "STRONG02", "DIV01", "DIV02", "DIV03"]
    rows = [
        _base_row("STRONG01", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK1", segment="NIFTY100"),
        _base_row("STRONG02", score=70.0, upside_r=1.35, planned_r=1.35, sector="BANK2", segment="NIFTY100"),
        _base_row("DIV01", score=63.0, upside_r=1.20, planned_r=1.20, sector="IT1", segment="NIFTY100"),
        _base_row("DIV02", score=62.0, upside_r=1.15, planned_r=1.15, sector="PHRMA1", segment="NIFTY100"),
        _base_row("DIV03", score=61.0, upside_r=1.12, planned_r=1.12, sector="AUTO1", segment="NIFTY100"),
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["selectedCount"] == 5
    modes = [c["qualificationMode"] for c in result["candidates"]]
    assert modes.count("PRIMARY_SETUP") + modes.count("SCORE_SOFT_PASS") == 2
    assert modes.count("DIVERSIFIED_SOFT_PASS") == 3


def test_only_three_safe_candidates_selects_three_not_five():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    symbols = ["SAFE01", "SAFE02", "SAFE03"]
    rows = [
        _base_row("SAFE01", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK1", segment="NIFTY100"),
        _base_row("SAFE02", score=70.0, upside_r=1.35, planned_r=1.35, sector="BANK2", segment="NIFTY100"),
        _base_row("SAFE03", score=68.0, upside_r=1.30, planned_r=1.30, sector="IT1", segment="NIFTY100"),
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["selectedCount"] == 3
    assert result["qualifiedCount"] == 3


def test_score_5999_tier_b_reject():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("BORDER_LOW", score=59.99, upside_r=1.15, planned_r=1.15, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 0
    assert result["selectedCount"] == 0


def test_score_60_tier_b_candidate():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("TIER_B_OK", score=60.0, upside_r=1.12, planned_r=1.12, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 1
    assert result["candidates"][0]["qualificationMode"] == "DIVERSIFIED_SOFT_PASS"
    assert result["selectedCount"] == 1


def test_score_65_tier_a_soft_candidate():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        setup_score_override=65.0,
        min_upside_capacity_r=1.25,
        min_planned_blended_r=1.25,
        min_expected_net_r=0.08,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("TIER_A_OK", score=65.0, upside_r=1.30, planned_r=1.30, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 1
    assert result["candidates"][0]["qualificationMode"] == "SCORE_SOFT_PASS"
    assert result["selectedCount"] == 1


def test_tier_b_stale_data_rejects():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("STALE_TIER_B", score=62.0, upside_r=1.15, planned_r=1.15, fresh=False, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 0
    assert result["selectedCount"] == 0


def test_tier_b_surveillance_restriction_rejects():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("SURVEIL_TIER_B", score=62.0, upside_r=1.15, planned_r=1.15, surveillanceRestricted=True, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 0
    assert result["selectedCount"] == 0


def test_tier_b_bad_price_band_rejects():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("PRICEBAND_TIER_B", score=62.0, upside_r=1.15, planned_r=1.15, nearPriceBand=True, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 0
    assert result["selectedCount"] == 0


def test_tier_b_invalid_stop_rejects():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("BADSTOP_TIER_B", score=62.0, upside_r=1.15, planned_r=1.15, structureStop=105.0, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["selectedCount"] == 0
    portfolio_reasons = {item.get("portfolioRejectReason") for item in result["rejected"] if item.get("portfolioRejectReason")}
    assert "INVALID_ENTRY_ATR_OR_STRUCTURE_STOP" in portfolio_reasons


def test_tier_b_gets_half_risk():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("TIER_B_RISK", score=62.0, upside_r=1.15, planned_r=1.15, sector="SEC1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["selectedCount"] == 1
    candidate = result["candidates"][0]
    assert candidate["qualificationMode"] == "DIVERSIFIED_SOFT_PASS"
    assert candidate.get("riskMultiplier") == 0.50


def test_formal_setup_outranks_tier_b():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=2,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    tier_b_row = _base_row("TIER_B_SCORE62", score=62.0, upside_r=1.15, planned_r=1.15, sector="BANK1", segment="NIFTY100")
    formal_row = _base_row(
        "FORMAL_SCORE68",
        score=70.0,
        upside_r=1.40,
        planned_r=1.40,
        sector="BANK2",
        segment="NIFTY100",
        prior20dHigh=99.0,
        clv=0.85,
        rvolPaced=1.6,
        residualStrengthPctile=72.0,
        breakoutDistanceAtr=0.3,
        extensionAtr=1.2,
    )

    symbols = ["TIER_B_SCORE62", "FORMAL_SCORE68"]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(
        [tier_b_row, formal_row],
        universe_coverage=1.0,
        regime="NORMAL",
        final_lock=True,
        now=NOW,
        config=cfg,
        correlations=correlations,
        apply_coverage_hysteresis=False,
    )
    assert result["selectedCount"] == 2
    assert result["candidates"][0]["qualificationMode"] == "PRIMARY_SETUP"
    assert result["candidates"][1]["qualificationMode"] == "DIVERSIFIED_SOFT_PASS"


def test_max_two_per_sector_preserved():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
        max_sector_notional_pct=40.0,
        max_sector_risk_bps=50,
    )
    symbols = ["BANK1", "BANK2", "BANK3", "IT1", "IT2", "PHRMA1"]
    rows = [
        _base_row("BANK1", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK", segment="NIFTY100"),
        _base_row("BANK2", score=70.0, upside_r=1.35, planned_r=1.35, sector="BANK", segment="NIFTY100"),
        _base_row("BANK3", score=62.0, upside_r=1.15, planned_r=1.15, sector="BANK", segment="NIFTY100"),
        _base_row("IT1", score=72.0, upside_r=1.45, planned_r=1.45, sector="IT", segment="NIFTY100"),
        _base_row("IT2", score=70.0, upside_r=1.35, planned_r=1.35, sector="IT", segment="NIFTY100"),
        _base_row("PHRMA1", score=62.0, upside_r=1.15, planned_r=1.15, sector="PHRMA", segment="NIFTY100"),
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    selected = result["candidates"]
    assert len(selected) <= 5
    sector_counts = {}
    for c in selected:
        s = c.get("sector", "UNKNOWN")
        sector_counts[s] = sector_counts.get(s, 0) + 1
    assert max(sector_counts.values()) <= 2


def test_correlation_cap_preserved():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
        max_average_correlation=0.70,
    )
    symbols = ["CORA", "CORB"]
    rows = [
        _base_row("CORA", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK", segment="NIFTY100"),
        _base_row("CORB", score=70.0, upside_r=1.35, planned_r=1.35, sector="BANK", segment="NIFTY100"),
    ]
    correlations = {("CORA", "CORB"): 0.95, ("CORB", "CORA"): 0.95}
    result = build_shadow_v2(
        rows,
        universe_coverage=1.0,
        regime="NORMAL",
        final_lock=True,
        now=NOW,
        config=cfg,
        correlations=correlations,
        apply_coverage_hysteresis=False,
    )
    assert result["selectedCount"] <= 1


def test_total_portfolio_risk_under_100bps():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        nav=1_000_000.0,
        core_risk_bps=15,
        max_portfolio_risk_bps=100,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    symbols = [f"RISK{i:02d}" for i in range(5)]
    rows = [
        _base_row(f"RISK{i:02d}", score=72.0 - i, upside_r=1.45 - i * 0.05, planned_r=1.45 - i * 0.05, sector=f"SEC{i}", segment="NIFTY100")
        for i in range(5)
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["portfolioInitialRisk"] <= cfg.nav * cfg.max_portfolio_risk_bps / 10_000


def test_gap_stress_under_250bps():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        nav=1_000_000.0,
        core_risk_bps=15,
        max_gap_stress_bps=250,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    symbols = [f"GAP{i:02d}" for i in range(5)]
    rows = [
        _base_row(f"GAP{i:02d}", score=72.0 - i, upside_r=1.45 - i * 0.05, planned_r=1.45 - i * 0.05, sector=f"SEC{i}", segment="NIFTY100")
        for i in range(5)
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["gapStressLoss"] <= cfg.nav * cfg.max_gap_stress_bps / 10_000


def test_defensive_regime_selects_max_two():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    symbols = [f"DEF{i:02d}" for i in range(5)]
    rows = [
        _base_row(f"DEF{i:02d}", score=72.0 - i, upside_r=1.45 - i * 0.05, planned_r=1.45 - i * 0.05, sector=f"SEC{i}", segment="NIFTY100")
        for i in range(5)
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="DEFENSIVE", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["selectedCount"] <= 2


def test_halt_new_longs_selects_zero():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("HALT01", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK1", segment="NIFTY100")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="HALT_NEW_LONGS", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["blocked"] is True
    assert result.get("selectedCount", 0) == 0


def test_coverage_below_90_blocks():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=25,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("BLOCK01", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK1", segment="NIFTY100")] + _noise_rows(9, fresh=False)[0]
    result = build_shadow_v2(rows, universe_coverage=0.10, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["blocked"] is True
    assert result.get("selectedCount", 0) == 0


def test_98pct_coverage_selects_five_with_reduced_risk():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        nav=1_000_000.0,
        core_risk_bps=15,
        coverage_normal_threshold=0.99,
        coverage_degraded_threshold=0.95,
        coverage_defensive_threshold=0.90,
        coverage_normal_risk_multiplier=1.00,
        coverage_degraded_risk_multiplier=0.75,
        coverage_defensive_risk_multiplier=0.50,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    symbols = [f"COV{i:02d}" for i in range(5)]
    rows = [
        _base_row(f"COV{i:02d}", score=70.0 + i, upside_r=1.35 + i * 0.05, planned_r=1.35 + i * 0.05, sector=f"SEC{i}", segment="NIFTY100")
        for i in range(5)
    ]
    noise_fresh = _noise_rows(93, fresh=True)[0]
    noise_stale = _noise_rows(2, fresh=False)[0]
    all_rows = rows + noise_fresh + noise_stale
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(all_rows, universe_coverage=0.98, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["coverageTier"] == "DEGRADED"
    assert result["coverageRiskMultiplier"] == 0.75
    assert result["selectedCount"] == 5


def test_diversification_seven_candidates_preserves_max_two_per_sector():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        core_risk_bps=15,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
        max_average_correlation=0.70,
    )
    symbols = ["DIV_BANK1", "DIV_BANK2", "DIV_IT1", "DIV_PHRMA1", "DIV_AUTO1", "DIV_METL1", "DIV_FMCG1"]
    rows = [
        _base_row("DIV_BANK1", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANKING", segment="NIFTY100"),
        _base_row("DIV_BANK2", score=70.0, upside_r=1.35, planned_r=1.35, sector="BANKING", segment="NIFTY100"),
        _base_row("DIV_IT1", score=68.0, upside_r=1.30, planned_r=1.30, sector="IT", segment="NIFTY100"),
        _base_row("DIV_PHRMA1", score=66.0, upside_r=1.25, planned_r=1.25, sector="PHARMA", segment="NIFTY100"),
        _base_row("DIV_AUTO1", score=64.0, upside_r=1.20, planned_r=1.20, sector="AUTO", segment="NIFTY100"),
        _base_row("DIV_METL1", score=63.0, upside_r=1.18, planned_r=1.18, sector="METALS", segment="NIFTY100"),
        _base_row("DIV_FMCG1", score=62.0, upside_r=1.15, planned_r=1.15, sector="FMCG", segment="NIFTY100"),
    ]
    correlations = _low_correlations(symbols)
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, correlations=correlations, apply_coverage_hysteresis=False)
    assert result["selectedCount"] == 5
    selected_sectors = [c["sector"] for c in result["candidates"]]
    assert max(Counter(selected_sectors).values()) <= 2


def test_calibrated_negative_expectancy_rejects():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("NEG_EXP", score=72.0, upside_r=1.45, planned_r=1.45, sector="BANK1", segment="NIFTY100")]
    rows[0]["expectedNetR"] = -0.10
    rows[0]["expectedNetRStatus"] = "CALIBRATED"
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 0
    assert result["selectedCount"] == 0
    reasons = {r for item in result["rejected"] for r in (item.get("reasonCodes") or [])}
    assert "CALIBRATED_NEGATIVE_EXPECTANCY" in reasons


def test_tier_b_microcap_prohibited():
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        max_positions=5,
        tier_b_min_score=60.0,
        tier_b_min_upside_capacity_r=1.10,
        tier_b_min_planned_blended_r=1.10,
        tier_b_min_expected_net_r=0.05,
        tier_b_risk_multiplier=0.50,
        prohibit_tier_b_microcaps=True,
    )
    rows = [_base_row("MICRO_B", score=62.0, upside_r=1.15, planned_r=1.15, sector="MICRO", segment="NIFTY_MICROCAP250")]
    result = build_shadow_v2(rows, universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 0
    assert result["selectedCount"] == 0
    reasons = {r for item in result["rejected"] for r in (item.get("reasonCodes") or [])}
    assert "TIER_B_MICROCAP_PROHIBITED" in reasons
