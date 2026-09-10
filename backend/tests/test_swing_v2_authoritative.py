from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.swing_v2 import authoritative
from app.services.swing_v2.config import load_config
from app.services.swing_v2 import ingestion
from app.services.swing_v2.portfolio import construct_portfolio
from app.services.angel_one_feed import _intraday_metrics_usable
from app.services import angel_one_feed as market_feed
from app.utils.symbols import Instrument


def _candidate(now: datetime) -> dict:
    stamp = now.isoformat()
    return {
        "ticker": "ABC", "ltpRaw": 105.0,
        "swingV2": {
            "symbol": "ABC", "universeSegment": "NIFTY100", "sector": "IT",
            "decisionPrice": 105.0, "bestAsk": 105.0,
            "trendPriorPctile": 80.0, "residualStrengthPctile": 80.0,
            "setupQualityPctile": 80.0, "rvolPctile": 80.0,
            "clvPctile": 90.0, "sectorStrengthPctile": 70.0,
            "liquidityPctile": 90.0, "prior20dHigh": 104.0,
            "clv": .9, "rvolPaced": 1.8, "breakoutDistanceAtr": .5,
            "extensionAtr": 1.2, "upsideCapacityR": 2.0,
            "plannedMaxBlendedR": 1.5, "expectedNetR": None,
            "expectedNetRStatus": "UNRATED", "atr14": 2.0,
            "structureStop": 103.4, "mdtv20": 4_000_000_000.0,
            "modeledRoundTripCostPct": .2, "spreadPct": .05,
            "availableAskDepth": 10_000, "dailyObservationCount": 300,
            "dailyBarsThroughPreviousClose": True, "corporateEventsCurrent": True,
            "surveillanceCurrent": True, "universeCurrent": True,
            "sourceTimestamps": {"quote": stamp, "depth": stamp, "bars5m": stamp},
        },
    }


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V2")
    monkeypatch.setenv("SWING_V2_ENABLED", "true")
    monkeypatch.setenv("SWING_V2_MODE", "PAPER")
    monkeypatch.setenv("SWING_V2_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("SWING_V2_SESSION_FILE", str(tmp_path / "session.json"))


def test_v2_authority_requires_enabled_paper_mode(monkeypatch):
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V2")
    monkeypatch.setenv("SWING_V2_ENABLED", "false")
    monkeypatch.setenv("SWING_V2_MODE", "SHADOW")
    with pytest.raises(ValueError, match="V2 authority requires"):
        load_config()


def test_authoritative_cycle_locks_fills_and_feeds_eod(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    decision = datetime(2026, 9, 9, 9, 40, tzinfo=timezone.utc)  # 15:10 IST
    snapshot = {
        "swingV2UniverseSize": 500,
        "swingV2UniverseCoverage": 1.0,
        "swingV2Regime": "NORMAL",
        "stockQuotes": {"ABC": _candidate(decision)},
    }
    monkeypatch.setattr(authoritative, "_snapshot", lambda: snapshot)
    monkeypatch.setattr(authoritative, "_refresh_snapshot", lambda reason, **kwargs: snapshot)
    monkeypatch.setattr(authoritative, "_refresh_final_candidate_facts", lambda value, scan, now: value)
    monkeypatch.setattr(authoritative, "_quote_observations", lambda symbols, now: {
        "ABC": {"timestamp": now.astimezone(timezone.utc).isoformat(), "ask": 105.0, "askDepth": 10_000, "open": 105.0, "high": 105.0, "low": 105.0, "close": 105.0, "source": "TEST"}
    })
    monkeypatch.setattr("app.services.desk_book_symbols.intraday_locked_symbols", lambda day: set())

    locked = authoritative.run_authoritative_cycle(now=decision)
    assert locked["authority"] == "V2"
    assert locked["v1Enabled"] is False
    assert locked["locked"] is True
    assert locked["long"][0]["executionStatus"] == "LOCKED"

    filled = authoritative.run_authoritative_cycle(now=decision + timedelta(minutes=1))
    assert filled["long"][0]["executionStatus"] == "FILLED"
    report = authoritative.authoritative_eod_report(decision.astimezone(authoritative.IST).date())
    assert report["authoritative"] is True
    assert report["reconciled"] is True
    assert report["totalPicks"] == 1
    assert report["picks"][0]["symbol"] == "ABC"


def test_authoritative_cycle_keeps_cash_when_v2_data_is_blocked(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    decision = datetime(2026, 9, 9, 9, 40, tzinfo=timezone.utc)
    snapshot = {"swingV2UniverseSize": 500, "swingV2UniverseCoverage": .98, "swingV2Regime": "NORMAL", "stockQuotes": {}}
    monkeypatch.setattr(authoritative, "_snapshot", lambda: snapshot)
    monkeypatch.setattr(authoritative, "_refresh_snapshot", lambda reason, **kwargs: snapshot)
    monkeypatch.setattr(authoritative, "_quote_observations", lambda symbols, now: {})
    monkeypatch.setattr("app.services.desk_book_symbols.intraday_locked_symbols", lambda day: set())
    session = authoritative.run_authoritative_cycle(now=decision)
    assert session["cashHeld"] is True
    assert session["cashReason"] == "UNIVERSE_COVERAGE_BELOW_99PCT"
    assert session["long"] == []


def test_authoritative_cycle_final_refresh_never_poisons_cash_after_window(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    # 09:55 UTC == 15:25 IST: the scheduler tick reaches the final branch only
    # after the order window has already closed.
    decision = datetime(2026, 9, 9, 9, 55, tzinfo=timezone.utc)
    snapshot = {
        "swingV2UniverseSize": 500,
        "swingV2UniverseCoverage": 1.0,
        "swingV2Regime": "NORMAL",
        "stockQuotes": {"ABC": _candidate(decision)},
    }
    monkeypatch.setattr(authoritative, "_snapshot", lambda: snapshot)
    monkeypatch.setattr(authoritative, "_refresh_snapshot", lambda reason, **kwargs: snapshot)
    monkeypatch.setattr(authoritative, "_refresh_final_candidate_facts", lambda value, scan, now: value)
    monkeypatch.setattr(authoritative, "_quote_observations", lambda symbols, now: {})
    monkeypatch.setattr("app.services.desk_book_symbols.intraday_locked_symbols", lambda day: set())

    session = authoritative.run_authoritative_cycle(now=decision)

    assert session["selectionFinalized"] is True
    assert session.get("cashReason") != "FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW"
    state = authoritative._read_json(authoritative._state_path())
    assert state["scan"].get("blockReason") != "FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW"
    # Past the order window: the decision is surfaced but no locks are persisted,
    # and no poison block is recorded (cashReason stays None / honest or absent).
    assert state["scan"].get("blocked") is None or state["scan"].get("blockReason") is None


def test_authoritative_cycle_recovers_poisoned_missed_window_final(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    decision = datetime(2026, 9, 9, 9, 40, tzinfo=timezone.utc)  # 15:10 IST
    poisoned = {
        "sessionDate": "2026-09-09",
        "selectionFinalized": True,
        "scan": {
            "strategyId": "SWING_2S_MOMENTUM_V2", "policyVersion": "2.0.0",
            "enabled": True, "authoritative": True, "mode": "PAPER",
            "blocked": True, "blockReason": "FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW",
            "candidates": [], "funnel": {"universe": 0},
        },
    }
    authoritative._write_state(poisoned)
    snapshot = {
        "swingV2UniverseSize": 500,
        "swingV2UniverseCoverage": 1.0,
        "swingV2Regime": "NORMAL",
        "stockQuotes": {"ABC": _candidate(decision)},
    }
    monkeypatch.setattr(authoritative, "_snapshot", lambda: snapshot)
    monkeypatch.setattr(authoritative, "_refresh_snapshot", lambda reason, **kwargs: snapshot)
    monkeypatch.setattr(authoritative, "_refresh_final_candidate_facts", lambda value, scan, now: value)
    monkeypatch.setattr(authoritative, "_quote_observations", lambda symbols, now: {
        "ABC": {"timestamp": now.astimezone(timezone.utc).isoformat(), "ask": 105.0, "askDepth": 10_000, "open": 105.0, "high": 105.0, "low": 105.0, "close": 105.0, "source": "TEST"}
    })
    monkeypatch.setattr("app.services.desk_book_symbols.intraday_locked_symbols", lambda day: set())

    session = authoritative.run_authoritative_cycle(now=decision)

    assert session["selectionFinalized"] is True
    assert session.get("cashReason") != "FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW"
    state = authoritative._read_json(authoritative._state_path())
    assert state["scan"].get("blockReason") != "FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW"
    # The recovery is recorded on the scan so operators can see the self-heal.
    assert state["scan"].get("recoveredFrom") == "FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW"


def test_ingestion_publishes_active_coverage_and_enrichment(monkeypatch):
    monkeypatch.setenv("SWING_V2_ENABLED", "true")
    monkeypatch.setenv("SWING_V2_MODE", "SHADOW")
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V1")
    members = [
        {"symbol": "ABC", "universeSegment": "NIFTY100", "industry": "IT"},
        {"symbol": "XYZ", "universeSegment": "NIFTY_MIDCAP150", "industry": "BANK"},
    ]
    monkeypatch.setattr(ingestion, "_membership", lambda day: (members, True, None))
    monkeypatch.setattr(ingestion, "_surveillance", lambda: (set(), True, None))
    monkeypatch.setattr(ingestion, "_result_events", lambda day: (set(), True, None))
    monkeypatch.setattr(ingestion, "_regime_from_market", lambda rows: {"state": "NORMAL", "riskScale": 1.0})
    now = datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc)
    raw = {
        "dailyObservationCount": 300, "dailyBarsThroughPreviousClose": True,
        "mom6mRaw": .2, "mom12mRaw": .3, "return5dRaw": .04,
        "ema20Daily": 100, "atr14": 2, "prior20dHigh": 104,
        "mdtv20": 4_000_000_000, "last3Closes": [105, 105.1, 105.2],
        "intradayLow": 103, "last5mTimestamp": now.isoformat(), "previous52wHigh": 108,
    }
    rows = [{
        "ticker": symbol, "ltpRaw": 105, "high": 106, "low": 103, "bestBid": 104.95,
        "bestAsk": 105, "availableAskDepth": 1000, "quoteReceivedAt": now.isoformat(),
        "intraday": {"swingV2Raw": raw, "vwap": 104, "ema9": 104.5, "volume_multiplier": 1.8},
    } for symbol in ("ABC", "XYZ")]
    payload = {"stockQuotes": {row["ticker"]: row for row in rows}}
    out = ingestion.enrich_v2_market_snapshot(payload, rows, now=now)
    assert out["swingV2UniverseCoverage"] == 1.0
    assert out["swingV2UniverseSize"] == 2
    assert out["swingV2Regime"] == "NORMAL"
    assert rows[0]["swingV2"]["corporateEventsCurrent"] is True
    assert rows[0]["swingV2"]["trendPriorPctile"] is not None


def test_ingestion_uses_live_universe_when_membership_download_fails(monkeypatch):
    monkeypatch.setenv("SWING_V2_ENABLED", "true")
    monkeypatch.setenv("SWING_V2_MODE", "SHADOW")
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V1")
    monkeypatch.setattr(ingestion, "_membership", lambda day: ([], False, "timeout"))
    monkeypatch.setattr(ingestion, "_surveillance", lambda: (set(), True, None))
    monkeypatch.setattr(ingestion, "_result_events", lambda day: (set(), True, None))
    monkeypatch.setattr(ingestion, "_regime_from_market", lambda rows: {"state": "NORMAL", "riskScale": 1.0})
    now = datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc)
    raw = {
        "dailyObservationCount": 300, "dailyBarsThroughPreviousClose": True,
        "mom6mRaw": .2, "mom12mRaw": .3, "return5dRaw": .04,
        "ema20Daily": 100, "atr14": 2, "prior20dHigh": 104,
        "mdtv20": 4_000_000_000, "last3Closes": [105, 105.1, 105.2],
        "intradayLow": 103, "last5mTimestamp": now.isoformat(), "previous52wHigh": 108,
    }
    rows = [{
        "ticker": "ABC", "ltpRaw": 105, "high": 106, "low": 103,
        "bestBid": 104.95, "bestAsk": 105, "availableAskDepth": 1000,
        "quoteReceivedAt": now.isoformat(),
        "intraday": {"swingV2Raw": raw, "vwap": 104, "ema9": 104.5, "volume_multiplier": 1.8},
    }]
    payload = {"stockQuotes": {"ABC": rows[0]}}
    out = ingestion.enrich_v2_market_snapshot(payload, rows, now=now)
    assert out["swingV2UniverseCoverage"] == 1.0
    assert out["swingV2DataStatus"]["featureRows"] == 1
    assert out["swingV2DataStatus"]["membershipMode"] == "RESOLVED_LIVE_FALLBACK"
    assert out["swingV2Regime"] == "NORMAL"
    assert rows[0]["swingV2"]["universeSegment"] == "NIFTY500_FALLBACK"
    assert rows[0]["swingV2"]["membershipSource"] == "RESOLVED_LIVE_NIFTY500"


def test_membership_outage_reuses_latest_valid_official_snapshot(monkeypatch, tmp_path):
    snapshot_day = "2026-09-08"
    constituents = [
        {
            "symbol": f"SYM{index:03d}",
            "universeSegment": (
                "NIFTY100" if index < 100
                else "NIFTY_MIDCAP150" if index < 250
                else "NIFTY_SMALLCAP250" if index < 500
                else "NIFTY_MICROCAP250"
            ),
            "effectiveFrom": snapshot_day,
            "effectiveTo": None,
        }
        for index in range(750)
    ]
    (tmp_path / f"{snapshot_day}.json").write_text(
        json.dumps({"constituents": constituents}), encoding="utf-8"
    )
    monkeypatch.setenv("SWING_V2_UNIVERSE_DIR", str(tmp_path))
    monkeypatch.setattr(
        ingestion,
        "refresh_official_membership",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("membership source timeout")),
    )

    rows, current, error = ingestion._membership(datetime(2026, 9, 9).date())

    assert len(rows) == 750
    assert current is False
    assert "using cached official membership 2026-09-08.json" in str(error)
    assert rows[499]["universeSegment"] == "NIFTY_SMALLCAP250"


def test_surveillance_uses_current_nse_json_reports():
    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            if url.endswith("/"):
                return Response({})
            if url.endswith("reportASM"):
                return Response({
                    "longterm": {"data": [{"symbol": "ABC"}]},
                    "shortterm": {"data": [{"symbol": "XYZ-EQ"}]},
                })
            if url.endswith("reportGSM"):
                return Response([{"symbol": "GSMCO"}])
            if url.endswith("reportESM"):
                return Response([{"symbol": "ESMCO"}])
            raise AssertionError(url)

    symbols, current, error = ingestion._surveillance(session_factory=Session)

    assert symbols == {"ABC", "XYZ", "GSMCO", "ESMCO"}
    assert current is True
    assert error is None


def test_existing_v2_positions_consume_portfolio_slots(monkeypatch):
    monkeypatch.setenv("SWING_MAX_POSITIONS", "1")
    config = load_config()
    candidate = _candidate(datetime.now(timezone.utc))["swingV2"]
    candidate.update({"expectedNetR": .2, "expectedUtilityR": .2})
    existing = [{"symbol": "OLD", "sector": "BANK", "deployedCapital": 100_000, "initialRiskRupees": 2_000, "universeSegment": "NIFTY100"}]
    result = construct_portfolio([candidate], config, existing_positions=existing)
    assert result["selected"] == []
    assert result["rejected"][0]["portfolioRejectReason"] == "MAX_POSITIONS"


def test_v2_authority_does_not_invalidate_shared_intraday_cache(monkeypatch):
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V2")
    # This is a valid shared-book candle block even though it predates V2 and
    # therefore has no swingV2Raw section.  V2 must fail its own row closed
    # without forcing Intraday and Index Options to refetch their universe.
    cached = {
        "data_source": "candles",
        "vwap": 101.25,
        "atr_pct": 3.2,
        "turnover_cr": 80.0,
        "hard_filter_reasons": [],
    }
    assert _intraday_metrics_usable(cached) is True


def test_long_history_is_explicitly_swing_only(monkeypatch):
    observed = []

    def fake_metrics(*args, daily_lookback_days=45, **kwargs):
        observed.append(daily_lookback_days)
        return {"data_source": "candles", "vwap": 100}

    monkeypatch.setattr(market_feed, "_intraday_metrics", fake_metrics)
    instrument = Instrument("ABC", "NSE", "ABC-EQ", "1")
    row = {"ticker": "ABC", "ltpRaw": 100}
    now = datetime.now(timezone.utc)
    market_feed._fetch_intraday_chunk(None, [row], {"ABC": instrument}, now)
    market_feed._fetch_intraday_chunk(
        None, [row], {"ABC": instrument}, now, daily_lookback_days=430
    )
    assert observed == [45, 430]


def test_v2_daily_lookback_defaults_to_shallow_30_days(monkeypatch):
    monkeypatch.delenv("SWING_V2_DAILY_LOOKBACK_DAYS", raising=False)
    monkeypatch.delenv("DAILY_LOOKBACK_DEFAULT_DAYS", raising=False)
    # Regression: the V2 "full universe + swing history" refresh previously pulled
    # ~430 calendar days of ONE_DAY candles per candidate, flooding Angel's
    # getCandleData endpoint. Short-horizon V2 entries only need the near-term
    # window, so the default is now 30 calendar days.
    assert market_feed._daily_lookback_days(swing_v2_history=True) == 30
    assert market_feed._daily_lookback_days(swing_v2_history=False) == 45

def test_v2_env_override_restores_deep_lookback_and_legacy_readiness(monkeypatch):
    monkeypatch.setenv("SWING_V2_DAILY_LOOKBACK_DAYS", "430")
    assert market_feed._daily_lookback_days(swing_v2_history=True) == 430
    # The readiness gate clamps at 252 observations for a deep config so legacy
    # 12-month rows remain the only reusable ones; shallow rows stay non-ready..
    assert market_feed._v2_history_ready({"dailyObservationCount": 252}) is True
    assert market_feed._v2_history_ready({"dailyObservationCount": 251}) is False
    assert market_feed._v2_history_ready(None) is False

def test_v2_cache_readiness_scales_with_shallow_lookback(monkeypatch):
    monkeypatch.setenv("SWING_V2_DAILY_LOOKBACK_DAYS", "30")
    threshold = min(
        market_feed._SWING_V2_LONG_HORIZON_OBSERVATIONS, max(15, int(30 * 0.7))
    )
    assert threshold == 21
    assert market_feed._v2_history_ready({"dailyObservationCount": 21}) is True
    assert market_feed._v2_history_ready({"dailyObservationCount": 20}) is False
    assert market_feed._v2_history_ready({"dailyObservationCount": 300}) is True
