"""Offline Alphalens-lite sanity check against eod_archive snapshots.

Research tooling only — not wired into the live server.
Prints decile spreads of composite score / intradayRet ranks across archived
snapshots. Does NOT claim predictive power; use before trusting live weights.

Usage:
  python -m scripts.validate_factors
  (from backend/ with PYTHONPATH=.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.intraday_session_engine import (  # noqa: E402
    _attach_percentile_ranks,
    _factor_scores,
    _universe_rows,
    detect_regime,
)

_ARCHIVE = Path(__file__).resolve().parents[1] / "app" / "services" / "eod_archive"
_SNAPSHOT = Path(__file__).resolve().parents[1] / "app" / "services" / "last_market_snapshot.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(f"skip {path.name}: {exc}")
        return {}


def _decile_table(bucket: list[dict], key: str = "score") -> list[tuple[int, float, int]]:
    """Return (decile 1-10, mean score, count) for scored rows."""
    vals = [float(r[key]) for r in bucket if r.get(key) is not None]
    if not vals:
        return []
    vals.sort()
    n = len(vals)
    out = []
    for d in range(10):
        lo = int(d * n / 10)
        hi = int((d + 1) * n / 10)
        chunk = vals[lo:hi]
        if not chunk:
            continue
        out.append((d + 1, sum(chunk) / len(chunk), len(chunk)))
    return out


def score_snapshot(snap: dict) -> dict:
    regime = detect_regime(snap)
    rows = _universe_rows(snap)
    long_scored: list[dict] = []
    for row in rows:
        scored = _factor_scores(row, regime, "LONG")
        if scored.get("score") is None:
            continue
        long_scored.append({
            "symbol": str(row.get("ticker") or "").upper(),
            "score": scored["score"],
            "intradayRet": scored.get("intradayRet"),
            "inPlay": scored.get("inPlay"),
            "gapPct": scored.get("gapPct"),
        })
    _attach_percentile_ranks(long_scored)
    return {
        "regime": regime.get("label"),
        "n": len(long_scored),
        "inPlay": sum(1 for r in long_scored if r.get("inPlay")),
        "scoreDeciles": _decile_table(long_scored, "score"),
        "top5": sorted(long_scored, key=lambda x: x["score"], reverse=True)[:5],
    }


def main() -> int:
    paths: list[Path] = []
    if _SNAPSHOT.is_file():
        paths.append(_SNAPSHOT)
    if _ARCHIVE.is_dir():
        paths.extend(sorted(_ARCHIVE.glob("*.json")))
    # de-dupe by name preference: live snapshot first
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in paths:
        if p.name in seen:
            continue
        seen.add(p.name)
        uniq.append(p)
    if not uniq:
        print("No last_market_snapshot.json or eod_archive/*.json found.")
        return 1

    print(f"validate_factors — {len(uniq)} snapshot(s)")
    print("NOTE: starting params — not proven optimal. Deciles are descriptive only.\n")
    scored_any = False
    for path in uniq[:6]:
        snap = _load_json(path)
        if not snap:
            continue
        result = score_snapshot(snap)
        if result["n"] == 0:
            print(f"=== {path.name} · skipped (no scorable universe / macros)")
            continue
        scored_any = True
        print(f"=== {path.name} · regime={result['regime']} · n={result['n']} · inPlay={result['inPlay']}")
        for d, mean, cnt in result["scoreDeciles"]:
            print(f"  D{d:02d} mean_score={mean:5.1f} n={cnt}")
        print("  top5:", [(t["symbol"], t["score"], t.get("scorePctRank")) for t in result["top5"]])
        print()
    if not scored_any:
        print("No snapshot produced scorable rows.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
