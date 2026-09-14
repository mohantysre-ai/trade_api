from __future__ import annotations

import math
from statistics import mean
from typing import Iterable


def shrunk_expectancy(outcomes: Iterable[float], setup_prior: Iterable[float], *, prior_strength: int = 25) -> dict[str, float | int | str | None]:
    bucket = [float(value) for value in outcomes]
    prior = [float(value) for value in setup_prior]
    if not bucket:
        return {"expectedNetR": None, "expectedNetRStatus": "UNRATED", "sampleCount": 0, "confidenceFloorR": None}
    prior_mean = mean(prior) if prior else 0.0
    expected = (sum(bucket) + prior_strength * prior_mean) / (len(bucket) + prior_strength)
    if len(bucket) < 2:
        floor = None
    else:
        sample_mean = mean(bucket)
        variance = sum((x - sample_mean) ** 2 for x in bucket) / (len(bucket) - 1)
        floor = expected - 1.645 * math.sqrt(variance / len(bucket))
    return {"expectedNetR": round(expected, 6), "expectedNetRStatus": "CALIBRATED" if len(bucket) >= 100 else "SHRUNK_INSUFFICIENT_SAMPLES", "sampleCount": len(bucket), "confidenceFloorR": None if floor is None else round(floor, 6)}
