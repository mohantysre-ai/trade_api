from __future__ import annotations

from typing import Any

from .config import SwingV2Config
from .risk import build_exit_and_size, gap_stress_loss


def _average_correlation(symbol: str, selected: list[dict[str, Any]], correlations: dict[tuple[str, str], float]) -> float:
    if not selected:
        return 0.0
    values = [float(correlations.get((symbol, str(row.get("symbol"))), correlations.get((str(row.get("symbol")), symbol), 1.0))) for row in selected]
    return sum(values) / len(values)


def construct_portfolio(rows: list[dict[str, Any]], cfg: SwingV2Config, *, correlations: dict[tuple[str, str], float] | None = None, occupied_symbols: set[str] | None = None) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    correlations, occupied = correlations or {}, {value.upper() for value in (occupied_symbols or set())}
    remaining_risk = cfg.nav * cfg.max_portfolio_risk_bps / 10_000
    sector_notional: dict[str, float] = {}
    sector_risk: dict[str, float] = {}
    stress = 0.0
    microcaps = 0
    ordered = sorted(rows, key=lambda row: (float(row.get("expectedUtilityR") if row.get("expectedUtilityR") is not None else row.get("expectedNetR") or -999), float(row.get("score") or 0)), reverse=True)
    for row in ordered:
        symbol, sector = str(row.get("symbol") or "").upper(), str(row.get("sector") or "UNKNOWN")
        reason = None
        if len(selected) >= cfg.max_positions:
            reason = "MAX_POSITIONS"
        elif symbol in occupied:
            reason = "CROSS_BOOK_CONFLICT"
        elif sum(1 for item in selected if str(item.get("sector") or "UNKNOWN") == sector) >= 2:
            reason = "MAX_TWO_NAMES_PER_SECTOR"
        elif _average_correlation(symbol, selected, correlations) > cfg.max_average_correlation:
            reason = "EXCESS_PORTFOLIO_CORRELATION"
        elif "MICRO" in str(row.get("universeSegment") or "").upper() and microcaps >= 1:
            reason = "MAX_ONE_MICROCAP_SATELLITE"
        if reason:
            rejected.append({"symbol": symbol, "portfolioRejectReason": reason}); continue
        sized = build_exit_and_size(row, cfg, remaining_risk_rupees=remaining_risk)
        if not sized.get("riskEligible"):
            rejected.append({"symbol": symbol, "portfolioRejectReason": sized.get("riskRejectReason")}); continue
        notional, risk = float(sized["deployedCapital"]), float(sized["initialRiskRupees"])
        if sector_notional.get(sector, 0) + notional > cfg.nav * cfg.max_sector_notional_pct / 100:
            rejected.append({"symbol": symbol, "portfolioRejectReason": "SECTOR_NOTIONAL_CAP"}); continue
        if sector_risk.get(sector, 0) + risk > cfg.nav * cfg.max_sector_risk_bps / 10_000:
            rejected.append({"symbol": symbol, "portfolioRejectReason": "SECTOR_RISK_CAP"}); continue
        next_stress = stress + gap_stress_loss(sized)
        if next_stress > cfg.nav * cfg.max_gap_stress_bps / 10_000:
            rejected.append({"symbol": symbol, "portfolioRejectReason": "GAP_STRESS_CAP"}); continue
        selected.append(sized); occupied.add(symbol)
        if "MICRO" in str(row.get("universeSegment") or "").upper():
            microcaps += 1
        sector_notional[sector] = sector_notional.get(sector, 0) + notional
        sector_risk[sector] = sector_risk.get(sector, 0) + risk
        remaining_risk -= risk; stress = next_stress
    return {"selected": selected, "rejected": rejected, "portfolioInitialRisk": round(cfg.nav * cfg.max_portfolio_risk_bps / 10_000 - remaining_risk, 2), "gapStressLoss": round(stress, 2), "cash": round(cfg.nav - sum(float(row["deployedCapital"]) for row in selected), 2)}
