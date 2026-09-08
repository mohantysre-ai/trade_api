from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _clock(value: str, name: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":"))
        return time(hour, minute)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be HH:MM") from exc


@dataclass(frozen=True)
class SwingV2Config:
    enabled: bool = False
    mode: str = "SHADOW"
    strategy_id: str = "SWING_2S_MOMENTUM_V2"
    policy_version: str = "2.0.0"
    feature_version: str = "swing_features_v2"
    universe: str = "NIFTY_TOTAL_MARKET_750"
    active_segments: tuple[str, ...] = ("NIFTY100", "NIFTY_MIDCAP150", "NIFTY_SMALLCAP250")
    microcap_mode: str = "SHADOW"
    max_positions: int = 5
    max_overnights: int = 2
    nav: float = 1_000_000.0
    core_risk_bps: int = 25
    microcap_risk_bps: int = 15
    max_portfolio_risk_bps: int = 100
    max_name_notional_pct: float = 20.0
    max_sector_notional_pct: float = 40.0
    max_sector_risk_bps: int = 50
    max_gap_stress_bps: int = 250
    stop_atr_mult: float = 0.80
    min_stop_pct: float = 0.75
    max_stop_core_pct: float = 2.25
    max_stop_small_pct: float = 2.50
    max_stop_micro_pct: float = 2.00
    t1_r: float = 1.0
    t1_qty_pct: float = 50.0
    trail_arm_r: float = 1.50
    trail_lock_r: float = 0.75
    t2_r: float = 2.0
    min_upside_capacity_r: float = 1.50
    min_planned_blended_r: float = 1.50
    min_expected_net_r: float = 0.12
    required_coverage: float = 0.99
    max_average_correlation: float = 0.70
    decision_start_ist: str = "14:30"
    decision_freeze_ist: str = "15:10"
    order_expire_ist: str = "15:20"
    mandatory_exit_ist: str = "15:15"
    ledger_path: str = ""
    live_promotion: bool = False

    def validate(self) -> None:
        if self.strategy_id != "SWING_2S_MOMENTUM_V2":
            raise ValueError("SWING_STRATEGY_ID must remain SWING_2S_MOMENTUM_V2")
        if self.mode not in {"SHADOW", "PAPER"}:
            raise ValueError("SWING_V2_MODE must be SHADOW or PAPER before live promotion")
        if self.microcap_mode not in {"DISABLED", "SHADOW"}:
            raise ValueError("SWING_MICROCAP_MODE must be DISABLED or SHADOW")
        if not 1 <= self.max_positions <= 5:
            raise ValueError("SWING_MAX_POSITIONS must be 1..5")
        if self.max_overnights not in {1, 2}:
            raise ValueError("SWING_MAX_OVERNIGHTS must be 1 or 2")
        if self.nav <= 0:
            raise ValueError("SWING_CAPITAL must be positive")
        if not 0 < self.required_coverage <= 1:
            raise ValueError("SWING_REQUIRED_UNIVERSE_COVERAGE must be in (0,1]")
        if not 0 < self.max_name_notional_pct <= 20:
            raise ValueError("single-name notional may not exceed 20% NAV")
        if not 0 < self.max_sector_notional_pct <= 40:
            raise ValueError("sector notional may not exceed 40% NAV")
        if self.max_portfolio_risk_bps > 100 or self.max_sector_risk_bps > 50:
            raise ValueError("portfolio/sector initial-risk limits exceed mandate")
        if self.max_gap_stress_bps > 250:
            raise ValueError("aggregate gap stress may not exceed 2.50% NAV")
        if self.t1_r < 1 or self.t2_r < self.t1_r or self.trail_arm_r < self.t1_r:
            raise ValueError("invalid T1/trail/T2 R ladder")
        if self.trail_lock_r >= self.trail_arm_r or not 0 < self.t1_qty_pct < 100:
            raise ValueError("invalid trail lock or T1 quantity")
        start = _clock(self.decision_start_ist, "SWING_DECISION_START_IST")
        freeze = _clock(self.decision_freeze_ist, "SWING_DECISION_FREEZE_IST")
        expire = _clock(self.order_expire_ist, "SWING_ORDER_EXPIRE_IST")
        mandatory = _clock(self.mandatory_exit_ist, "SWING_MANDATORY_EXIT_IST")
        if not start < freeze < expire:
            raise ValueError("decision clocks must satisfy start < freeze < order expiry")
        if mandatory >= expire:
            raise ValueError("mandatory exit must precede order expiry clock")
        if self.live_promotion:
            raise ValueError("SWING_LIVE_PROMOTION is not permitted by this implementation")


def load_config() -> SwingV2Config:
    repo_root = Path(__file__).resolve().parents[4]
    c = SwingV2Config(
        enabled=_bool("SWING_V2_ENABLED", False),
        mode=os.getenv("SWING_V2_MODE", "SHADOW").upper(),
        strategy_id=os.getenv("SWING_STRATEGY_ID", "SWING_2S_MOMENTUM_V2"),
        universe=os.getenv("SWING_UNIVERSE", "NIFTY_TOTAL_MARKET_750"),
        active_segments=tuple(p.strip().upper() for p in os.getenv("SWING_ACTIVE_SEGMENTS", "NIFTY100,NIFTY_MIDCAP150,NIFTY_SMALLCAP250").split(",") if p.strip()),
        microcap_mode=os.getenv("SWING_MICROCAP_MODE", "SHADOW").upper(),
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
        decision_start_ist=os.getenv("SWING_DECISION_START_IST", "14:30"),
        decision_freeze_ist=os.getenv("SWING_DECISION_FREEZE_IST", "15:10"),
        order_expire_ist=os.getenv("SWING_ORDER_EXPIRE_IST", "15:20"),
        mandatory_exit_ist=os.getenv("SWING_MANDATORY_EXIT_IST", "15:15"),
        ledger_path=os.getenv("SWING_V2_LEDGER_PATH", str(repo_root / "backend" / "app" / "data" / "swing_v2_ledger.sqlite3")),
        live_promotion=_bool("SWING_LIVE_PROMOTION", False),
    )
    c.validate()
    return c
