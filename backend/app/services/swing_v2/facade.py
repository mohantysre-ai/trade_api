from __future__ import annotations

import json
from datetime import date
from typing import Any

from .config import load_config
from .ledger import SwingLedger
from .reporting import ledger_eod_report
from .shadow import build_shadow_v2


def _read_snapshot(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8-sig") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for raw in snapshot.get("stocks") or []:
        if not isinstance(raw, dict):
            continue
        row = {**raw, **(raw.get("intraday") or {})}
        row["symbol"] = str(raw.get("ticker") or raw.get("symbol") or "").upper()
        row["decisionPrice"] = raw.get("ltpRaw") or raw.get("decisionPrice")
        # V2 enrichment must be provided by the governed ingestion pipeline.
        # The compatibility facade never upgrades V1 estimates into V2 facts.
        if isinstance(raw.get("swingV2"), dict):
            row.update(raw["swingV2"])
        result.append(row)
    return result


def build_from_market_snapshot(snapshot: dict[str, Any], *, final_lock: bool = False, persist_events: bool = False, occupied_symbols: set[str] | None = None) -> dict[str, Any]:
    universe_size = int(snapshot.get("swingV2UniverseSize") or snapshot.get("universeSize") or 0)
    coverage = float(snapshot.get("swingV2UniverseCoverage") or min(1.0, universe_size / 750.0))
    regime = str(snapshot.get("swingV2Regime") or (snapshot.get("selectionMeta") or {}).get("swingV2Regime") or "REGIME_UNRATED")
    return build_shadow_v2(_rows(snapshot), universe_coverage=coverage, regime=regime, final_lock=final_lock, persist_events=persist_events, occupied_symbols=occupied_symbols)


def attach_shadow_v2(session: dict[str, Any], snapshot_path: str, *, final_lock: bool = False, persist_events: bool = False) -> dict[str, Any]:
    out = dict(session)
    if not load_config().enabled:
        return out
    snapshot = _read_snapshot(snapshot_path)
    # V1 is a comparison champion while V2 shadows; it is not a separate
    # economic book. Genuine Intraday conflicts are supplied by the caller.
    out["shadowV2"] = build_from_market_snapshot(snapshot, final_lock=final_lock, persist_events=persist_events)
    return out


def eod_shadow_v2(for_date: date) -> dict[str, Any]:
    cfg = load_config()
    if not cfg.enabled:
        return {"strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version, "enabled": False, "authoritative": False, "validationState": "RESEARCH_HYPOTHESIS", "positions": []}
    return ledger_eod_report(SwingLedger(cfg.ledger_path), for_date.isoformat())
