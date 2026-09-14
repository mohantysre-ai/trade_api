from __future__ import annotations

import math
from statistics import pstdev
from typing import Any, Iterable


def _return(closes: list[float], recent_offset: int, lookback: int) -> float | None:
    if len(closes) <= lookback or lookback <= recent_offset:
        return None
    end, start = closes[-1 - recent_offset], closes[-1 - lookback]
    return None if start <= 0 else end / start - 1


def _annualized_vol(closes: list[float], window: int) -> float | None:
    if len(closes) < window + 1:
        return None
    sample = closes[-(window + 1):]
    returns = [math.log(sample[i] / sample[i - 1]) for i in range(1, len(sample)) if sample[i] > 0 and sample[i - 1] > 0]
    return pstdev(returns) * math.sqrt(252) if len(returns) >= 2 else None


def momentum_prior_raw(adjusted_closes: Iterable[float]) -> dict[str, float | None]:
    closes = [float(value) for value in adjusted_closes]
    r6, r12 = _return(closes, 5, 126), _return(closes, 5, 252)
    v6, v12 = _annualized_vol(closes[:-5], 126), _annualized_vol(closes[:-5], 252)
    return {"mom6m": None if r6 is None or not v6 else r6 / v6, "mom12m": None if r12 is None or not v12 else r12 / v12}


def close_location(decision_price: float, day_low: float, day_high: float, tick_size: float) -> float:
    return (decision_price - day_low) / max(day_high - day_low, tick_size)


def paced_rvol(volume_so_far: float, expected_volume_so_far: float) -> float | None:
    return volume_so_far / expected_volume_so_far if expected_volume_so_far > 0 else None


def intraday_features(row: dict[str, Any]) -> dict[str, Any]:
    required = ("decisionPrice", "dayLow", "dayHigh", "tickSize", "vwap", "atr14", "ema20Daily")
    if any(row.get(key) is None for key in required):
        return {"featureStatus": "UNRATED", "reasonCodes": [f"MISSING_{key}" for key in required if row.get(key) is None]}
    price, atr = float(row["decisionPrice"]), float(row["atr14"])
    if atr <= 0:
        return {"featureStatus": "UNRATED", "reasonCodes": ["INVALID_ATR14"]}
    return {
        "featureStatus": "RATED",
        "clv": close_location(price, float(row["dayLow"]), float(row["dayHigh"]), float(row["tickSize"])),
        "rvolPaced": paced_rvol(float(row.get("volumeSoFar") or 0), float(row.get("expectedVolumeSoFar") or 0)),
        "vwapDistanceAtr": (price - float(row["vwap"])) / atr,
        "extensionAtr": (price - float(row["ema20Daily"])) / atr,
    }


def oi_treatment(*, is_fno: bool, current_oi: float | None, previous_oi: float | None) -> dict[str, str]:
    if not is_fno:
        return {"oiApplicability": "NOT_APPLICABLE", "oiStatus": "NOT_APPLICABLE"}
    if current_oi is None or previous_oi is None:
        return {"oiApplicability": "APPLICABLE", "oiStatus": "UNRATED"}
    return {"oiApplicability": "APPLICABLE", "oiStatus": "RATED"}


def winsorize(values: Iterable[float], lower: float = .01, upper: float = .99) -> list[float]:
    sample = sorted(float(value) for value in values)
    if not sample:
        return []
    low = sample[min(len(sample) - 1, int((len(sample) - 1) * lower))]
    high = sample[min(len(sample) - 1, int((len(sample) - 1) * upper))]
    return [max(low, min(high, value)) for value in sample]
