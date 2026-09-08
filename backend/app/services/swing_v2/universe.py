from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone
from datetime import date
from pathlib import Path
from typing import Any

import requests

SEGMENTS = {"NIFTY100", "NIFTY_MIDCAP150", "NIFTY_SMALLCAP250", "NIFTY_MICROCAP250"}
OFFICIAL_SEGMENT_URLS = {
    "NIFTY100": "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
    "NIFTY_MIDCAP150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "NIFTY_SMALLCAP250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "NIFTY_MICROCAP250": "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv",
}
EXPECTED_SEGMENT_COUNTS = {"NIFTY100": 100, "NIFTY_MIDCAP150": 150, "NIFTY_SMALLCAP250": 250, "NIFTY_MICROCAP250": 250}
MAX_OFFICIAL_TRANSITION_VARIANCE = 5


def point_in_time_members(rows: list[dict[str, Any]], on_date: date) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        start = date.fromisoformat(str(row.get("effectiveFrom") or "1900-01-01")[:10])
        end_raw = row.get("effectiveTo")
        end = date.fromisoformat(str(end_raw)[:10]) if end_raw else date.max
        segment = str(row.get("universeSegment") or "").upper()
        if start <= on_date <= end and segment in SEGMENTS:
            selected.append(dict(row))
    return selected


def activation_status(segment: str) -> str:
    return "SHADOW" if "MICROCAP" in segment.upper() else "ACTIVE_PAPER_CHAMPION"


def coverage(expected_symbols: set[str], fresh_symbols: set[str]) -> float:
    if not expected_symbols:
        return 0.0
    return len({s.upper() for s in expected_symbols} & {s.upper() for s in fresh_symbols}) / len(expected_symbols)


def refresh_official_membership(
    output_directory: str,
    *,
    effective_date: date,
    fetcher: Any = requests.get,
) -> dict[str, Any]:
    """Persist an immutable official constituent snapshot; never rewrite history."""
    rows, sources = [], []
    for segment, default_url in OFFICIAL_SEGMENT_URLS.items():
        env_name = f"SWING_{segment}_CONSTITUENTS_URL"
        url = os.getenv(env_name, default_url)
        response = fetcher(url, timeout=30)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        segment_rows = []
        for item in reader:
            symbol = str(item.get("Symbol") or item.get("SYMBOL") or "").strip().upper()
            if symbol:
                segment_rows.append({
                    "symbol": symbol,
                    "companyName": item.get("Company Name") or item.get("CompanyName"),
                    "industry": item.get("Industry"),
                    "universeSegment": segment,
                    "effectiveFrom": effective_date.isoformat(),
                    "effectiveTo": None,
                    "source": "NIFTY_INDICES_OFFICIAL",
                })
        expected = EXPECTED_SEGMENT_COUNTS[segment]
        if not expected - MAX_OFFICIAL_TRANSITION_VARIANCE <= len(segment_rows) <= expected + MAX_OFFICIAL_TRANSITION_VARIANCE:
            raise ValueError(f"{segment} baseline {expected} constituents, received implausible official count {len(segment_rows)}")
        rows.extend(segment_rows)
        sources.append({"segment": segment, "url": url, "count": len(segment_rows)})
    symbols = {row["symbol"] for row in rows}
    if not 750 - MAX_OFFICIAL_TRANSITION_VARIANCE <= len(symbols) <= 750 + MAX_OFFICIAL_TRANSITION_VARIANCE:
        raise ValueError(f"NIFTY_TOTAL_MARKET_750 baseline 750 unique symbols, received implausible official count {len(symbols)}")
    payload = {
        "schemaVersion": "swing_universe_v2",
        "universe": "NIFTY_TOTAL_MARKET_750",
        "baselineConstituentCount": 750,
        "effectiveDate": effective_date.isoformat(),
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
        "constituentCount": len(symbols),
        "officialTransitionVariance": len(symbols) - 750,
        "sources": sources,
        "constituents": sorted(rows, key=lambda row: (row["universeSegment"], row["symbol"])),
    }
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{effective_date.isoformat()}.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing.get("constituents") != payload["constituents"]:
            raise ValueError(f"point-in-time universe snapshot already exists with different content: {target}")
        return existing
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return payload


def angel_resolution_coverage(membership: list[dict[str, Any]], instrument_master: list[dict[str, Any]]) -> dict[str, Any]:
    master = {
        str(item.get("symbol") or item.get("tradingsymbol") or "").replace("-EQ", "").upper(): item
        for item in instrument_master
    }
    resolved, missing = [], []
    for member in membership:
        symbol = str(member.get("symbol") or "").upper()
        instrument = master.get(symbol)
        if instrument:
            resolved.append({**member, "angelInstrument": instrument})
        else:
            missing.append(symbol)
    return {"expected": len(membership), "resolved": len(resolved), "coverage": coverage({str(row.get("symbol")) for row in membership}, {str(row.get("symbol")) for row in resolved}), "missingSymbols": missing, "instruments": resolved}
