from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SwingV2Config:
    enabled: bool = False
    mode: str = "SHADOW"
    strategy_id: str = "SWING_2S_MOMENTUM_V2"
    policy_version: str = "2.0.0"
    universe: str = "NIFTY_TOTAL_MARKET_750"
    max_positions: int = 5
    max_overnights: int = 2
    nav: float = 1_000_000.0
    core_risk_bps: int = 25
    microcap_risk_bps: int = 15
    max_portfolio_risk_bps: int = 100
    max_name_notional_pct: float = 20.0
    max_sector_notional_pct: float = 40.0
    stop_atr_mult: float = 0.80
    min_stop_pct: float = 0.75
    max_stop_core_pct: float = 2.25
    max_stop_small_pct: float = 2.50
    t1_r: float = 1.0
    t1_qty_pct: float = 50.0
    trail_arm_r: float = 1.50
    trail_lock_r: float = 0.75
    t2_r: float = 2.0
    min_upside_capacity_r: float = 1.50
    min_expected_net_r: float = 0.12
    required_coverage: float = 0.99
    live_promotion: bool = False

    def validate(self) -> None:
        if self.mode not in {"SHADOW", "PAPER"}:
            raise ValueError("SWING_V2_MODE must be SHADOW or PAPER before live promotion")
        if self.max_positions < 1 or self.max_positions > 5:
            raise ValueError("SWING_MAX_POSITIONS must be 1..5")
        if self.max_overnights not in {1, 2}:
            raise ValueError("SWING_MAX_OVERNIGHTS must be 1 or 2")
        if not (0.0 < self.required_coverage <= 1.0):
            raise ValueError("SWING_REQUIRED_UNIVERSE_COVERAGE must be in (0,1]")
        if self.max_name_notional_pct > 20.0:
            raise ValueError("single-name notional may not exceed 20% NAV")
        if self.max_portfolio_risk_bps > 100:
            raise ValueError("open initial risk may not exceed 1.00% NAV")
        if self.t1_r < 1.0 or self.t2_r < self.t1_r:
            raise ValueError("invalid T1/T2 R ladder")
        if self.live_promotion:
            raise ValueError("SWING_LIVE_PROMOTION is not permitted by this implementation")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> SwingV2Config:
    c = SwingV2Config(
        enabled=_bool("SWING_V2_ENABLED", False),
        mode=os.getenv("SWING_V2_MODE", "SHADOW").upper(),
        max_positions=int(os.getenv("SWING_MAX_POSITIONS", "5")),
        max_overnights=int(os.getenv("SWING_MAX_OVERNIGHTS", "2")),
        nav=float(os.getenv("SWING_CAPITAL", "1000000")),
        core_risk_bps=int(os.getenv("SWING_CORE_RISK_BPS", "25")),
        microcap_risk_bps=int(os.getenv("SWING_MICROCAP_RISK_BPS", "15")),
        max_portfolio_risk_bps=int(os.getenv("SWING_MAX_PORTFOLIO_RISK_BPS", "100")),
        max_name_notional_pct=float(os.getenv("SWING_MAX_NAME_NOTIONAL_PCT", "20")),
        max_sector_notional_pct=float(os.getenv("SWING_MAX_SECTOR_NOTIONAL_PCT", "40")),
        stop_atr_mult=float(os.getenv("SWING_STOP_ATR_MULT", "0.80")),
        min_stop_pct=float(os.getenv("SWING_MIN_STOP_PCT", "0.75")),
        max_stop_core_pct=float(os.getenv("SWING_MAX_STOP_CORE_PCT", "2.25")),
        max_stop_small_pct=float(os.getenv("SWING_MAX_STOP_SMALL_PCT", "2.50")),
        t1_r=float(os.getenv("SWING_T1_R", "1.00")),
        t1_qty_pct=float(os.getenv("SWING_T1_QTY_PCT", "50")),
        trail_arm_r=float(os.getenv("SWING_TRAIL_ARM_R", "1.50")),
        trail_lock_r=float(os.getenv("SWING_TRAIL_LOCK_R", "0.75")),
        t2_r=float(os.getenv("SWING_T2_R", "2.00")),
        min_upside_capacity_r=float(os.getenv("SWING_MIN_UPSIDE_CAPACITY_R", "1.50")),
        min_expected_net_r=float(os.getenv("SWING_MIN_EXPECTED_NET_R", "0.12")),
        required_coverage=float(os.getenv("SWING_REQUIRED_UNIVERSE_COVERAGE", "0.99")),
        live_promotion=_bool("SWING_LIVE_PROMOTION", False),
    )
    c.validate()
    return c
