from datetime import date, datetime
from pathlib import Path

from app.services.index_options_live import (
    _apply_live_spot_risk_guard,
    compose_live_index_options_radar,
    finalize_closed_index_options_radar,
    replay_session_payload,
)
from app.services.index_options_engine import build_index_options_radar
from app.services.index_options_paper import reconcile_paper_book
from app.services.angel_index_options import IST_ZONE
from app.services.lemonn_options import apply_lemonn_fallback
from tests.test_index_options_replay import _ReplayClient, _master_for_replay


def test_handler_reaches_session_date_before_live_return():
    text = Path("app/services/angel_one_feed.py").read_text(encoding="utf-8")
    start = text.index("def index_options(")
    chunk = text[start:text.index("def dhan_scanner_matrix(")]
    assert "if sessionDate:" in chunk
    assert "replay_session_payload" in chunk
    assert "compose_live_index_options_radar" in chunk
    assert chunk.find("if sessionDate:") < chunk.find("return _compose()")
    assert "return result" not in chunk


def test_last_friday_replay_is_not_live_radar():
    payload = replay_session_payload(
        _ReplayClient(),
        "last-friday",
        today=date(2026, 8, 23),
        persist=False,
        master=_master_for_replay(),
    )
    assert payload["mode"] == "SESSION_REPLAY"
    assert payload["sessionDate"] == "2026-08-21"
    assert payload.get("buySideContracts") is not None


def test_invalid_session_date_raises():
    try:
        replay_session_payload(object(), "not-a-date", persist=False)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_live_spot_crossing_original_stop_invalidates_before_radar():
    inputs = {
        "indices": {
            "NIFTY": {
                "spot": 244.5,
                "direction": "CALL",
                "contract": {"ltp": 100, "delta": 0.55, "gamma": 0.001},
                "structure": {"last": 247, "ema9": 246, "orbHigh": 245, "orbLow": 235, "atr5m": 12},
                "gates": {"structure": True, "breakout": True, "riskReward": True},
                "gateEvidence": {"contractEconomics": {"spreadPct": 1.0}},
                "dataLimitations": [],
            }
        }
    }
    guarded = _apply_live_spot_risk_guard(inputs)["indices"]["NIFTY"]
    assert guarded["gates"]["structure"] is False
    assert guarded["gates"]["breakout"] is False
    assert guarded["gates"]["riskReward"] is False
    assert guarded["expectedR"] == 0.0
    assert guarded["gateEvidence"]["riskReward"]["basis"] == "LIVE_SPOT_STRUCTURAL_INVALIDATION"
    assert guarded["gateEvidence"]["riskReward"]["entryUnderlying"] == 244.5
    assert "LIVE_SPOT_CROSSED_STRUCTURAL_STOP" in guarded["dataLimitations"]


def test_live_risk_uses_current_spot_and_atr_floor_for_tiny_stop():
    inputs = {
        "indices": {
            "NIFTY": {
                "spot": 246.2,
                "direction": "CALL",
                "contract": {"ltp": 100, "delta": 0.55, "gamma": 0.001},
                "structure": {"last": 247, "ema9": 246, "orbHigh": 245, "orbLow": 235, "atr5m": 12},
                "gates": {"structure": True, "breakout": True, "riskReward": True},
                "gateEvidence": {"contractEconomics": {"spreadPct": 1.0}},
                "dataLimitations": [],
            }
        }
    }
    guarded = _apply_live_spot_risk_guard(inputs)["indices"]["NIFTY"]
    evidence = guarded["gateEvidence"]["riskReward"]
    assert evidence["basis"] == "LIVE_SPOT_ORB_INVALIDATION_WITH_ATR_SPREAD_RISK_FLOOR"
    assert evidence["entryUnderlying"] == 246.2
    assert evidence["structuralRiskPoints"] == 0.2
    assert evidence["atrRiskFloorPoints"] == 2.4
    assert evidence["riskPoints"] >= 2.4
    assert evidence["riskPoints"] > evidence["structuralRiskPoints"]
    assert evidence["expectedR"] < 10


def test_live_put_stop_invalidation_is_direction_aware():
    inputs = {
        "indices": {
            "BANKNIFTY": {
                "spot": 251.0,
                "direction": "PUT",
                "contract": {"ltp": 120, "delta": -0.52, "gamma": 0.001},
                "structure": {"last": 247, "ema9": 250, "orbHigh": 255, "orbLow": 249, "atr5m": 14},
                "gates": {"structure": True, "breakout": True, "riskReward": True},
                "gateEvidence": {"contractEconomics": {"spreadPct": 0.8}},
                "dataLimitations": [],
            }
        }
    }
    guarded = _apply_live_spot_risk_guard(inputs)["indices"]["BANKNIFTY"]
    assert guarded["gates"]["structure"] is False
    assert guarded["gateEvidence"]["riskReward"]["liveInvalidated"] is True


def test_banknifty_early_breadth_rechecks_live_rr_and_auto_locks(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    inputs = {
        "indices": {
            "BANKNIFTY": {
                "spot": 249.0,
                "direction": "PUT",
                "providerStatus": "LIVE",
                "source": "ANGEL_ONE",
                "contract": {
                    "symbol": "BANKNIFTYTESTPE", "strike": 250, "expiry": "2026-09-01",
                    "ltp": 120, "delta": -0.52, "gamma": 0.001, "lotSize": 30,
                    "token": "12345", "exchange": "NFO",
                },
                "scores": {name: 100.0 for name in (
                    "trend", "breakout", "futuresOi", "optionChain", "contract", "regime"
                )} | {"breadth": 57.0},
                "structure": {"last": 247, "ema9": 251, "orbHigh": 260, "orbLow": 250, "atr5m": 10},
                "gates": {name: True for name in (
                    "fresh", "structure", "breakout", "futuresOi", "optionChain", "contractEconomics"
                )} | {"breadth": False, "riskReward": False},
                "gateEvidence": {
                    "futuresOi": {"state": "SHORT_BUILDUP", "aligned": True},
                    "optionChain": {"aligned": True, "reason": "DIRECTIONAL_PREMIUM_OI_BUILDUP"},
                    "breadth": {
                        "status": "LIVE", "aligned": False, "strictAligned": False,
                        "score": -0.14, "directionalScore": 0.14, "coveragePct": 100.0,
                        "adaptiveFloor": 0.50, "classification": "NEUTRAL",
                    },
                    "contractEconomics": {"aligned": True, "spreadPct": 0.2},
                },
                "breadth": {
                    "status": "LIVE", "aligned": False, "strictAligned": False,
                    "score": -0.14, "directionalScore": 0.14, "coveragePct": 100.0,
                    "adaptiveFloor": 0.50, "classification": "NEUTRAL",
                },
                "vixRegime": "NORMAL",
                "rawChain": [],
                "dataLimitations": [],
            }
        }
    }
    guarded = _apply_live_spot_risk_guard(inputs)
    bank = guarded["indices"]["BANKNIFTY"]
    assert bank["expectedR"] >= 3.0
    assert bank["gates"]["breadth"] is True
    assert bank["breadth"]["confirmationMode"] == "EARLY_EXCEPTIONAL_EVIDENCE"

    radar = build_index_options_radar({"indexOptions": guarded})
    assert radar["selected"][0]["key"] == "BANKNIFTY"
    assert radar["selected"][0]["state"] == "ELIGIBLE"

    book = reconcile_paper_book(
        radar, now=datetime(2026, 8, 31, 11, 0, tzinfo=IST_ZONE), persist=True,
    )
    assert book["entryCount"] == 1
    assert book["open"][0]["index"] == "BANKNIFTY"
    assert book["open"][0]["symbol"] == "BANKNIFTYTESTPE"


def test_compose_applies_lemonn_after_scanx(monkeypatch):
    empty = {
        "indices": {
            "NIFTY": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
            "BANKNIFTY": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
            "FINNIFTY": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
            "SENSEX": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
        }
    }
    lemonn_calls: list[str] = []

    def lemonn_fn(payload, expiries):
        lemonn_calls.append("hit")
        return apply_lemonn_fallback(
            payload,
            expiries,
            fetcher=lambda key, expiry: {"source": "LEMONN_FALLBACK", "status": "LIVE", "chain": [{"strike": 1}]},
        )

    monkeypatch.setattr(
        "app.services.index_options_live.ensure_fresh_market_snapshot",
        lambda snapshot, **kwargs: dict(snapshot),
    )
    result = compose_live_index_options_radar(
        {},
        live=True,
        client=object(),
        persist=False,
        snapshot_fn=lambda client: empty,
        scanx_fn=lambda payload, expiries: payload,
        lemonn_fn=lemonn_fn,
        expiries_fn=lambda: {
            "NIFTY": date(2026, 8, 25),
            "BANKNIFTY": date(2026, 8, 25),
            "FINNIFTY": date(2026, 8, 25),
            "SENSEX": date(2026, 8, 25),
        },
        lemonn_discover_fn=lambda keys: {},
        oi_enrichment_fn=lambda payload, expiries: payload,
    )
    assert lemonn_calls == ["hit"]
    assert result["provider"] == "ANGEL_ONE_WITH_SCANX_AND_LEMONN_FALLBACK"
    assert result["providerEvidence"]["thirdFallbackUsedFor"] == ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]


def test_closed_session_freezes_hunt_without_rebuilding_provider(monkeypatch):
    monkeypatch.setattr(
        "app.services.index_options_live.reconcile_paper_book",
        lambda radar, **kwargs: {"marketOpen": False, "open": [], "closed": []},
    )
    frozen = finalize_closed_index_options_radar(
        {"candidates": [], "selected": [], "limits": {"huntMode": "CONTINUOUS_MARKET_SESSION"}},
        client=object(),
        persist=False,
    )
    assert frozen["sessionStatus"] == "CLOSED"
    assert frozen["huntActive"] is False
    assert frozen["cacheStatus"] == "SESSION_FROZEN"
    assert frozen["limits"]["huntMode"] == "SESSION_CLOSED"
