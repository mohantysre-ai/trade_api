"""Rolling divergence monitor between the primary (Angel) and standby (Shoonya) lanes."""
from __future__ import annotations

import time
from typing import Callable


class DivergenceMonitor:
    def __init__(self, min_symbols: int, alert_pct: float, sustain_s: float = 10.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._min_symbols = max(1, int(min_symbols))
        self._alert_pct = float(alert_pct)
        self._sustain_s = float(sustain_s)
        self._clock = clock
        self._breach_since: float | None = None
        self._disabled = False
        self.last_offenders: dict[str, float] = {}

    def observe(self, deltas_pct: dict[str, float]) -> None:
        offenders = {s: d for s, d in deltas_pct.items() if abs(d) > self._alert_pct}
        self.last_offenders = offenders
        now = self._clock()
        if len(offenders) >= self._min_symbols:
            if self._breach_since is None:
                self._breach_since = now
            elif now - self._breach_since >= self._sustain_s:
                self._disabled = True
        else:
            self._breach_since = None

    @property
    def disabled(self) -> bool:
        return self._disabled

    def clear(self) -> None:
        self._disabled = False
        self._breach_since = None

    def snapshot(self) -> dict[str, object]:
        return {"disabled": self._disabled, "offenders": dict(self.last_offenders), "breachSinceMonotonic": self._breach_since}
