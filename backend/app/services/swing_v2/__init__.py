"""SWING_2S_MOMENTUM_V2.

Shadow-only deterministic swing engine.  V1 remains authoritative until the
research/paper promotion gates are satisfied.
"""
from .config import SwingV2Config, load_config
from .shadow import build_shadow_v2

__all__ = ["SwingV2Config", "load_config", "build_shadow_v2"]
