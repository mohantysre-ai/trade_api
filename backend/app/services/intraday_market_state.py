"""In-memory authoritative live market state for the Intraday book.

Runtime chain (architecture V5):

    ANGEL_WS -> in-memory live market state -> atomic evaluation snapshot
             -> intraday session state -> live MTM / API / EOD projection

REST is bootstrap / historical / targeted-recovery only.  Disk is durability
only.  Transport/state patterns are adapted from ``angel_index_stream`` (the
Index Options radar behavior is unchanged); this module owns the Intraday
equity path for the full 750-symbol universe with no subscription churn when
trades lock/unlock.
"""
from __future__ import annotations

import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

IST_ZONE = ZoneInfo("Asia/Kolkata")
LOGGER = logging.getLogger(__name__)

EXCHANGE_TYPES = {"NSE": 1, "NFO": 2, "BSE": 3, "BFO": 4}
SOURCE_WS = "ANGEL_WS"
SOURCE_REST_BOOTSTRAP = "ANGEL_REST_BOOTSTRAP"
SOURCE_REST_RECOVERY = "ANGEL_REST_RECOVERY"

FRESH_SECONDS = float(os.getenv("INTRADAY_WS_FRESH_SECONDS", "8"))
STALE_SECONDS = float(os.getenv("INTRADAY_WS_STALE_SECONDS", "30"))
RECOVERY_SECONDS = float(os.getenv("INTRADAY_WS_RECOVERY_SECONDS", "60"))
MAX_SUBSCRIBE_CHUNK = int(os.getenv("INTRADAY_WS_SUBSCRIBE_CHUNK", "250"))
WS_ENABLED = os.getenv("INTRADAY_WS_ENABLED", "1") == "1"
UNIVERSE_LABEL = "INTRADAY_750"
WS_CORRELATION_ID = "intraday750"

LIVE = "LIVE"
DEGRADED = "DEGRADED"
STALE = "STALE"
UNAVAILABLE = "UNAVAILABLE"

_METRICS_LOCK = threading.Lock()
_METRICS: dict[str, float] = {
    "ws_tick_count": 0.0,
    "ws_tick_dropped_older": 0.0,
    "ws_tick_duplicate": 0.0,
    "ws_tick_invalid": 0.0,
    "ws_reconnect_count": 0.0,
    "rest_recovery_count": 0.0,
    "rest_recovery_failures": 0.0,
    "rest_bootstrap_count": 0.0,
}


def _metric(name: str, delta: float = 1.0) -> None:
    with _METRICS_LOCK:
        _METRICS[name] = _METRICS.get(name, 0.0) + delta


def metrics_snapshot() -> dict[str, float]:
    with _METRICS_LOCK:
        return dict(_METRICS)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _number(value: Any, *, scale: float = 1.0) -> float | None:
    try:
        result = float(value) / scale
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return result if result >= 0 else None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None


def _bucket5m(stamp: datetime) -> str:
    minute = stamp.minute - stamp.minute % 5
    return stamp.replace(minute=minute, second=0, microsecond=0).isoformat()


class IntradayUniverse:
    """Deterministic INTRADAY_750 registry (Nifty100+Mid150+Small250+Micro250).

    Built from the existing ``angel_one_feed`` constituent machinery; no
    fixture substitution and no invented members.
    """

    def __init__(self, rows: list[dict[str, Any]], label: str = UNIVERSE_LABEL) -> None:
        self.rows = rows
        self.label = label

    @classmethod
    def build(cls, loader: Callable[[], tuple[list[Any], str]] | None = None) -> "IntradayUniverse":
        if loader is None:
            def loader() -> tuple[list[Any], str]:
                from .angel_one_feed import INTRADAY_750_LABEL, _pool_watchlist

                return _pool_watchlist(INTRADAY_750_LABEL)

        instruments, _label = loader()
        rows: list[dict[str, Any]] = []
        seen_tokens: set[str] = set()
        missing_tokens = 0
        for inst in instruments:
            exchange = str(getattr(inst, "exchange", "") or "NSE").upper()
            token = str(getattr(inst, "token", "") or "").strip()
            symbol = str(getattr(inst, "key", "") or "").strip().upper()
            if not symbol:
                continue
            # Angel WebSocket needs a numeric Angel token.  Dhan-only
            # fallback instruments ("DHAN:<id>") stay in the registry but
            # cannot be WS-subscribed; they count as missingTokens and are
            # eligible for REST recovery instead of fabricating a token.
            active = token.isdigit()
            if not active:
                missing_tokens += 1
            elif token in seen_tokens:
                continue
            else:
                seen_tokens.add(token)
            rows.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "token": token if active else None,
                    "tradingsymbol": str(getattr(inst, "tradingsymbol", "") or symbol),
                    "indexGroup": getattr(inst, "indexGroup", None),
                    "active": active,
                }
            )
        return cls(rows, _label or UNIVERSE_LABEL)

    def active_rows(self) -> list[dict[str, Any]]:
        return [row for row in self.rows if row["active"]]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "universeLabel": UNIVERSE_LABEL,
            "universeCount": len(self.rows),
            "activeSymbols": len(self.active_rows()),
            "missingTokens": sum(1 for row in self.rows if not row["active"]),
            "duplicateTokens": duplicate_count(self.rows),
        }


def duplicate_count(rows: list[dict[str, Any]]) -> int:
    tokens = [row["token"] for row in rows if row["token"]]
    return len(tokens) - len(set(tokens))


def _new_symbol_row(universe_row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "symbol": (universe_row or {}).get("symbol"),
        "token": (universe_row or {}).get("token"),
        "ltp": None,
        "prevClose": None,
        "exchangeTimestamp": None,
        "receivedAt": None,
        "receivedMonotonic": 0.0,
        "sequence": None,
        "source": None,
        "connected": False,
        "stale": True,
        "oi": None,
        "tradeVolume": None,
        "tickCount": 0,
        "bar5m": None,
    }


def _parse_exchange_ts(message: dict[str, Any]) -> datetime | None:
    """Store the exchange timestamp if the feed provides one.

    Never used for ordering/rejection decisions (spec: no fragile timestamp
    heuristics; sequence + receipt monotonic time govern freshness).
    """
    raw = message.get("exchange_timestamp") or message.get("last_traded_timestamp")
    if isinstance(raw, (int, float)) and raw > 0:
        try:
            return datetime.fromtimestamp(float(raw) / 1000.0, tz=IST_ZONE)
        except (OverflowError, OSError, ValueError):
            return None
    return None


class IntradayMarketState:
    """One authoritative in-memory live state for the Intraday universe.

    - Per-symbol freshness (LIVE/DEGRADED/STALE/UNAVAILABLE); one stale symbol
      never freezes the universe.
    - Latest-wins atomic tick updates with sequence/duplicate handling.
    - Monotonically increasing ``generation``; ``capture_snapshot`` produces an
      immutable evaluation snapshot for the scanner.
    - Subscription state follows the universe, never trade status.
    """

    def __init__(self, universe: IntradayUniverse | None = None) -> None:
        self._lock = threading.RLock()
        self._universe = universe
        self._universe_rows: dict[str, dict[str, Any]] = {}
        self._state: dict[str, dict[str, Any]] = {}
        self._generation = 0
        self._last_tick_at: datetime | None = None
        self._connected = False

    # ------------------------------------------------------------------ universe

    @property
    def universe(self) -> IntradayUniverse | None:
        return self._universe

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def ensure_universe(self, loader: Callable[[], tuple[list[Any], str]] | None = None) -> IntradayUniverse:
        """Load the 750 registry once; deterministic, never a silent fixture swap."""
        with self._lock:
            if self._universe is None:
                self._universe = IntradayUniverse.build(loader)
                self.update_universe(self._universe)
            return self._universe

    def update_universe(self, universe: IntradayUniverse) -> None:
        """Set the desired subscription set (universe/config changes only).

        Never wipes existing tick state: a reconnect or universe refresh must
        preserve in-memory prices.
        """
        with self._lock:
            self._universe = universe
            self._universe_rows = {
                row["token"]: row for row in universe.active_rows() if row["token"]
            }
            for token, row in self._universe_rows.items():
                state = self._state.get(token)
                if state is None:
                    self._state[token] = _new_symbol_row(row)
                else:
                    state["symbol"] = row["symbol"]

    # ------------------------------------------------------------------- ticks

    def apply_tick(self, token: str, exchange_type: int, message: Any) -> str:
        """Atomic latest-wins tick update.

        Returns one of: ``new`` / ``duplicate`` / ``older`` / ``invalid``.
        The full row is updated under one lock; readers never observe a
        half-updated row.
        """
        token = str(token or "")
        if not isinstance(message, dict) or not token:
            _metric("ws_tick_invalid")
            return "invalid"
        ltp = _number(message.get("last_traded_price"), scale=100.0)
        if ltp is None:
            ltp = _number(message.get("ltp"))
        if ltp is None or ltp <= 0:
            _metric("ws_tick_invalid")
            return "invalid"
        sequence = message.get("sequenceNumber", message.get("last_seq"))
        sequence = int(sequence) if isinstance(sequence, (int, float)) else None
        now = _now_utc()
        mono = time.monotonic()
        with self._lock:
            row = self._state.get(token)
            if row is None:
                # A REST bootstrap/recovery row may exist keyed under its
                # symbol before the first WS tick; re-key it under the token
                # so there is exactly one authoritative row per symbol.
                row = next(
                    (
                        s
                        for s in self._state.values()
                        if s.get("symbol") == str(
                            (self._universe_rows.get(token) or {}).get("symbol") or ""
                        ).upper()
                    ),
                    None,
                )
                if row is not None:
                    row["token"] = token
                    self._state[token] = row
            if row is None:
                row = _new_symbol_row(self._universe_rows.get(token))
                self._state[token] = row
            prev_sequence = row.get("sequence")

            if sequence is not None and prev_sequence is not None:
                if sequence < prev_sequence:
                    _metric("ws_tick_dropped_older")
                    return "older"
                if sequence == prev_sequence:
                    # Duplicate packet: keep the winning LTP, refresh receipt
                    # time only so retransmits do not fake freshness.
                    row["receivedMonotonic"] = mono
                    row["receivedAt"] = _iso(now)
                    _metric("ws_tick_duplicate")
                    return "duplicate"
            prev_close = _number(message.get("closed_price"), scale=100.0)
            if prev_close and prev_close > 0:
                row["prevClose"] = prev_close
            row.update(
                {
                    "ltp": ltp,
                    "exchangeTimestamp": _iso(_parse_exchange_ts(message)),
                    "receivedAt": _iso(now),
                    "receivedMonotonic": mono,
                    "sequence": sequence,
                    "source": SOURCE_WS,
                    "connected": True,
                    "tickCount": int(row.get("tickCount") or 0) + 1,
                }
            )
            oi = _number(message.get("open_interest"))
            if oi is not None:
                row["oi"] = oi
            volume = _number(message.get("volume_trade_for_the_day"))
            if volume is not None:
                row["tradeVolume"] = volume
            row["stale"] = False
            self._generation += 1
            self._last_tick_at = now
            self._update_bar_locked(token, ltp, now.astimezone(IST_ZONE))
        _metric("ws_tick_count")
        return "new"

    def _update_bar_locked(self, token: str, ltp: float, stamp: datetime) -> None:
        key = _bucket5m(stamp)
        row = self._state[token]
        bar = row.get("bar5m")
        if bar is None or bar.get("startTime") != key:
            if bar is not None:
                bar["immutable"] = True  # completed boundary; never mutated
            row["bar5m"] = {
                "startTime": key,
                "endTime": stamp.isoformat(),
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": 0,
                "complete": False,
                "quality": "DEGRADED",
            }
            return
        bar["high"] = max(float(bar["high"]), ltp)
        bar["low"] = min(float(bar["low"]), ltp)
        bar["close"] = ltp
        bar["endTime"] = stamp.isoformat()
        bar["quality"] = "OK"

    # -------------------------------------------------------------- freshness

    @staticmethod
    def _freshness_from_age(age: float | None) -> str:
        if age is None:
            return UNAVAILABLE
        if age <= FRESH_SECONDS:
            return LIVE
        if age <= STALE_SECONDS:
            return DEGRADED
        return STALE

    def freshness(self, token_or_symbol: str, *, now_mono: float | None = None) -> str:
        """Per-symbol freshness label. A single stale symbol stays isolated."""
        row = self.symbol_state(str(token_or_symbol))
        if row is None:
            return UNAVAILABLE
        return row["freshness"]

    def symbol_state(self, token_or_symbol: str) -> dict[str, Any] | None:
        """Public read-only copy of one symbol row (never a live reference)."""
        token = str(token_or_symbol)
        with self._lock:
            row = self._state.get(token)
            if row is None:
                row = next(
                    (s for s in self._state.values() if s.get("symbol") == token),
                    None,
                )
            if row is None:
                return None
            copy = dict(row)
            received = copy.get("receivedMonotonic") or 0.0
            copy["dataAge"] = (
                max(0.0, time.monotonic() - received) if received else None
            )
            copy["freshness"] = self._freshness_from_age(copy["dataAge"])
            copy["stale"] = copy["freshness"] in (STALE, UNAVAILABLE)
            copy["dataStale"] = copy["stale"]
            copy["bar5m"] = dict(copy["bar5m"]) if copy.get("bar5m") else None
            return copy

    # -------------------------------------------------- REST bootstrap/recovery

    def apply_rest_quote(
        self,
        symbol: str,
        quote: dict[str, Any] | None,
        source: str = SOURCE_REST_RECOVERY,
    ) -> bool:
        """Seed/repair one symbol from REST (bootstrap or targeted recovery).

        REST never becomes the heartbeat: the row keeps REST provenance until
        a fresh WebSocket tick resumes and restores ANGEL_WS authority.
        """
        if not isinstance(quote, dict):
            return False
        ltp = _number(quote.get("ltp")) or _number(
            (quote.get("data") or {}).get("ltp") if isinstance(quote.get("data"), dict) else None
        )
        if ltp is None or ltp <= 0:
            return False
        now = _now_utc()
        with self._lock:
            row = next(
                (
                    s
                    for s in self._state.values()
                    if s.get("symbol") == str(symbol).upper()
                ),
                None,
            )
            if row is None:
                row = _new_symbol_row(None)
                row["symbol"] = str(symbol).upper()
                self._state[row["symbol"]] = row
            close = _number(quote.get("close")) or _number(quote.get("prevClose"))
            if close and close > 0:
                row["prevClose"] = close
            row.update(
                {
                    "ltp": ltp,
                    "receivedAt": _iso(now),
                    "receivedMonotonic": time.monotonic(),
                    "source": source,
                    "connected": True,
                }
            )
            row["stale"] = False
            self._generation += 1
            self._last_tick_at = now
        if source == SOURCE_REST_RECOVERY:
            _metric("rest_recovery_count")
        else:
            _metric("rest_bootstrap_count")
        return True

    # -------------------------------------------------- snapshot / status

    def capture_snapshot(self, symbols: list[str] | None = None) -> dict[str, Any]:
        """Immutable evaluation snapshot (pull-to-push, spec §17).

        The scanner evaluates this coherent copy while ticks continue to
        update the live state underneath.
        """
        wanted = {s.upper() for s in symbols} if symbols else None
        with self._lock:
            quotes: dict[str, dict[str, Any]] = {}
            for row in self._state.values():
                symbol = row.get("symbol")
                if not symbol:
                    continue
                if wanted is not None and symbol not in wanted:
                    continue
                received = row.get("receivedMonotonic") or 0.0
                age = max(0.0, time.monotonic() - received) if received else None
                quotes[symbol] = {
                    "symbol": symbol,
                    "token": row.get("token"),
                    "ltp": row.get("ltp"),
                    "prevClose": row.get("prevClose"),
                    "source": row.get("source"),
                    "receivedAt": row.get("receivedAt"),
                    "dataAge": age,
                    "freshness": self._freshness_from_age(age),
                    "oi": row.get("oi"),
                    "tradeVolume": row.get("tradeVolume"),
                    "bar5m": dict(row["bar5m"]) if row.get("bar5m") else None,
                }
            return {
                "generation": self._generation,
                "capturedAt": _iso(_now_utc()),
                "quotes": quotes,
            }

    def set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = bool(connected)
            for row in self._state.values():
                row["connected"] = bool(connected)

    def stream_status(self) -> dict[str, Any]:
        """Global summary derived from real per-symbol health (spec §10/§43)."""
        with self._lock:
            rows = list(self._state.values())
            connected = self._connected
            last_tick_at = self._last_tick_at
        now_mono = time.monotonic()
        live = stale = unavailable = 0
        oldest_live: float | None = None
        ages: list[float] = []
        for row in rows:
            received = row.get("receivedMonotonic") or 0.0
            if not received:
                unavailable += 1
                continue
            age = now_mono - received
            label = self._freshness_from_age(age)
            ages.append(age)
            if label == LIVE:
                live += 1
                oldest_live = age if oldest_live is None else max(oldest_live, age)
            elif label in (DEGRADED, STALE):
                stale += 1
        expected = len(rows)
        health = "DISCONNECTED"
        if connected:
            if unavailable and not live:
                health = "DISCONNECTED"
            elif stale or unavailable:
                health = "DEGRADED"
            else:
                health = "OK"
        return {
            "wsConnected": connected,
            "symbolsExpected": expected,
            "symbolsLive": live,
            "symbolsStale": stale,
            "symbolsUnavailable": unavailable,
            "lastTickAt": _iso(last_tick_at),
            "oldestLiveTickAgeSeconds": oldest_live,
            "feedStatus": health,
        }

    def stale_symbols(
        self,
        *,
        recovery_seconds: float | None = None,
        include_unavailable: bool = True,
    ) -> list[dict[str, Any]]:
        """Symbols needing targeted REST recovery (never the whole universe)."""
        threshold = RECOVERY_SECONDS if recovery_seconds is None else recovery_seconds
        now_mono = time.monotonic()
        out: list[dict[str, Any]] = []
        with self._lock:
            rows = list(self._state.values())
        for row in rows:
            received = row.get("receivedMonotonic") or 0.0
            age = (now_mono - received) if received else None
            if age is None:
                if include_unavailable:
                    out.append({"symbol": row.get("symbol"), "token": row.get("token"), "age": None})
                continue
            if age > threshold:
                out.append({"symbol": row.get("symbol"), "token": row.get("token"), "age": age})
        return out

    def ltp_source_mix(self) -> dict[str, int]:
        with self._lock:
            mix: dict[str, int] = {}
            for row in self._state.values():
                source = row.get("source") or "UNKNOWN"
                mix[source] = mix.get(source, 0) + 1
            return mix

    def diagnostic_block(self, session: dict[str, Any] | None = None) -> str:
        """Compact startup/ops diagnostic (spec §73). Reflects real state only."""
        uni = self._universe.diagnostics() if self._universe else {
            "universeLabel": UNIVERSE_LABEL, "universeCount": 0,
            "activeSymbols": 0, "missingTokens": 0, "duplicateTokens": 0,
        }
        status = self.stream_status()
        session = session or {}
        last_tick = (status.get("lastTickAt") or "—")
        if last_tick != "—":
            try:
                last_tick = datetime.fromisoformat(last_tick).astimezone(IST_ZONE).strftime("%H:%M:%S")
            except ValueError:
                pass
        locked = len(session.get("openPositions") or [])
        free = int(session.get("freeSlots") or 0)
        data_health = "OK" if status["feedStatus"] == "OK" else status["feedStatus"]
        reason = ""
        if status["symbolsStale"]:
            reason = f"{status['symbolsStale']} stale symbols"
        if status["symbolsUnavailable"]:
            reason = (reason + "; " if reason else "") + f"{status['symbolsUnavailable']} unavailable"
        return (
            "INTRADAY LIVE STATE\n"
            "-------------------\n"
            f"Universe      : {uni['universeLabel']}\n"
            f"Symbols       : {uni['activeSymbols']} (registry {uni['universeCount']}, "
            f"missingTokens={uni['missingTokens']}, duplicates={uni['duplicateTokens']})\n"
            f"WS Connected  : {'YES' if status['wsConnected'] else 'NO'}\n"
            f"WS Live       : {status['symbolsLive']}\n"
            f"WS Stale      : {status['symbolsStale']}\n"
            f"WS Unavailable: {status['symbolsUnavailable']}\n"
            f"Market Gen    : {self._generation}\n"
            f"Last Tick     : {last_tick}\n"
            f"REST Mode     : RECOVERY_ONLY\n"
            f"Session Date  : {session.get('sessionDate', '—')}\n"
            f"Session State : {session.get('sessionStatus', '—')}\n"
            f"Locked        : {locked}\n"
            f"Free Slots    : {free}\n"
            f"Data Health   : {data_health}\n"
            + (f"Reason        : {reason}\n" if reason else "")
        )


class AngelIntradayStream:
    """Process-wide Intraday WebSocket manager (all 750 -> WS, spec §5/§27).

    Transport pattern adapted from ``angel_index_stream.AngelIndexStream``:
    process-local manager, background socket worker owning reconnect/backoff,
    SDK wrapper retained for subscriptions, atomic tick updates through
    ``IntradayMarketState.apply_tick``.  The desired subscription set is the
    Intraday universe itself — locking/closing/replacing trades never
    changes it.
    """

    def __init__(self, market_state: IntradayMarketState) -> None:
        self._market_state = market_state
        self._lock = threading.RLock()
        self._socket: Any = None
        self._opened = False
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._stop = False
        self._subscribed: set[tuple[int, str]] = set()

    @property
    def market_state(self) -> IntradayMarketState:
        return self._market_state

    def ensure(self, client: Any, rows: list[dict[str, Any]] | None = None) -> bool:
        """Register the client + universe and start the background worker.

        Idempotent: later calls do NOT resubscribe unless the desired token
        set actually changed (no subscription churn from trade events).
        """
        if not WS_ENABLED:
            return False
        if rows is None:
            rows = self._market_state.ensure_universe().active_rows()
        else:
            self._market_state.update_universe(IntradayUniverse(rows))
        if not callable(getattr(client, "connect", None)):
            return False
        with self._lock:
            self._client = client
            if self._thread is None or not self._thread.is_alive():
                self._stop = False
                self._thread = threading.Thread(
                    target=self._run, name="angel-intraday-stream", daemon=True
                )
                self._thread.start()
        return True

    def _credentials(self) -> tuple[str, str, str, str]:
        smart = self._client.connect()
        auth = getattr(smart, "authToken", "") or ""
        feed = getattr(smart, "feedToken", "") or ""
        return auth, str(self._client.api_key), str(self._client.client_id), feed

    def _run(self) -> None:
        log = logging.getLogger(__name__)
        delay = 1.0
        while not self._stop:
            try:
                from SmartApi.smartWebSocketV2 import SmartWebSocketV2

                # Disable the SDK's recursive reconnect loop; this worker owns
                # reconnect/backoff and guarantees there is only one socket.
                socket = SmartWebSocketV2(*self._credentials(), max_retry_attempt=0)
                socket.on_open = lambda _ws, sdk=socket: self._on_open(sdk)
                socket.on_data = lambda ws, message: self._on_data(message)
                socket.on_error = lambda ws, error: log.warning(
                    "Angel intraday stream error: %s", error
                )
                socket.on_close = lambda ws: self._on_close()
                with self._lock:
                    self._socket = socket
                    self._subscribed.clear()
                LOGGER.info("WS_CONNECT universe=%s", WS_CORRELATION_ID)
                socket.connect()
                delay = 1.0
            except Exception as exc:
                _metric("ws_reconnect_count")
                log.warning("Angel intraday stream reconnecting: %s", exc)
            finally:
                self._on_close()
            if not self._stop:
                # Bounded exponential backoff with jitter (spec §25).
                sleep_for = delay + random.uniform(0.0, delay * 0.25)
                time.sleep(sleep_for)
                delay = min(delay * 2.0, 30.0)

    def _on_open(self, socket: Any) -> None:
        with self._lock:
            self._opened = True
            self._subscribed.clear()
        self._subscribe_desired(socket)
        self._market_state.set_connected(True)
        LOGGER.info("WS_CONNECTED correlationId=%s", WS_CORRELATION_ID)

    def _subscribe_desired(self, socket: Any) -> None:
        with self._lock:
            if socket is not self._socket or not self._opened:
                return
            missing = [
                (EXCHANGE_TYPES.get(row["exchange"], 1), token)
                for token, row in self._market_state._universe_rows.items()
                if (EXCHANGE_TYPES.get(row["exchange"], 1), token) not in self._subscribed
            ]
        grouped: dict[int, list[str]] = {}
        for exchange_type, token in missing:
            grouped.setdefault(exchange_type, []).append(token)
        for exchange_type, tokens in grouped.items():
            for start in range(0, len(tokens), MAX_SUBSCRIBE_CHUNK):
                chunk = tokens[start : start + MAX_SUBSCRIBE_CHUNK]
                socket.subscribe(
                    WS_CORRELATION_ID,
                    3,
                    [{"exchangeType": exchange_type, "tokens": chunk}],
                )
        if missing:
            with self._lock:
                self._subscribed.update(missing)
            LOGGER.info(
                "WS_SUBSCRIBE correlationId=%s tokens=%d", WS_CORRELATION_ID, len(missing)
            )

    def _on_close(self) -> None:
        with self._lock:
            self._opened = False
            had_socket = self._socket is not None
            self._socket = None
            self._subscribed.clear()
        self._market_state.set_connected(False)
        if had_socket:
            LOGGER.warning("WS_DISCONNECTED correlationId=%s", WS_CORRELATION_ID)

    def resubscribe(self) -> None:
        """Explicit recovery hook: resubscribe the full desired universe."""
        socket = self._socket
        if socket is not None:
            with self._lock:
                self._subscribed.clear()
            self._subscribe_desired(socket)
            LOGGER.info("WS_RESUBSCRIBE correlationId=%s", WS_CORRELATION_ID)

    def _on_data(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        token = str(message.get("token") or "")
        if not token:
            return
        self._market_state.apply_tick(
            token, int(message.get("exchange_type") or 0), message
        )


_TICK_LOG_SAMPLE = int(os.getenv("INTRADAY_WS_TICK_LOG_SAMPLE", "500"))


class _RecoveryCircuit:
    """Bounded circuit breaker for repeated quote-recovery failures (§49)."""

    def __init__(self, threshold: int = 5, cooldown: float = 300.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at == 0.0:
            self.opened_at = time.monotonic()
            _metric("rest_circuit_open")
            LOGGER.warning("REST_CIRCUIT_OPEN reason=recovery_failures=%d", self.failures)

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        if self.opened_at == 0.0:
            return True
        if time.monotonic() - self.opened_at >= self.cooldown:
            # Half-open: allow one probing cycle.
            self.opened_at = 0.0
            self.failures = self.threshold - 1
            return True
        return False


def start_intraday_recovery_worker(client: Any) -> threading.Thread | None:
    """Targeted REST recovery for stale symbols only (spec §12D/§50/§57).

    - Reconnect/resubscribe of the WebSocket is the primary recovery path;
      this worker never fires while the socket is down (it just waits).
    - Fires only for symbols stale beyond the configured threshold, in small
      bounded batches through the existing Angel client (limiter preserved).
    - Daemon thread; never touches the tick path.
    """
    interval = float(os.getenv("INTRADAY_RECOVERY_INTERVAL_SEC", "60"))
    batch_size = int(os.getenv("INTRADAY_RECOVERY_BATCH", "25"))
    circuit = _RecoveryCircuit()
    stream = get_intraday_stream()
    market_state = stream.market_state

    def _recover_once() -> int:
        if market_state.stream_status().get("wsConnected") is not True:
            return 0  # WS restoration is primary; REST recovery waits.
        if not circuit.allow():
            return 0
        stale = market_state.stale_symbols()
        symbols = [
            str(row.get("symbol") or "").upper()
            for row in stale
            if row.get("symbol")
        ][:batch_size]
        if not symbols:
            return 0
        LOGGER.info("REST_RECOVERY symbols=%d", len(symbols))
        try:
            from .trade_outcome import _fetch_angel_plan_prices

            quotes = _fetch_angel_plan_prices(symbols) or {}
        except Exception as exc:
            circuit.record_failure()
            _metric("rest_recovery_failures")
            LOGGER.warning("REST_RECOVERY failed: %s", exc)
            return 0
        repaired = 0
        for sym in symbols:
            price = quotes.get(sym)
            if price is not None and market_state.apply_rest_quote(sym, {"ltp": price}):
                repaired += 1
        if repaired:
            circuit.record_success()
            LOGGER.info("REST_RECOVERY repaired=%d/%d", repaired, len(symbols))
        else:
            circuit.record_failure()
        return repaired

    def _run() -> None:
        while True:
            time.sleep(interval)
            try:
                _recover_once()
            except Exception:
                LOGGER.exception("intraday recovery cycle failed")

    if not WS_ENABLED:
        return None
    thread = threading.Thread(
        target=_run, name="intraday-recovery-worker", daemon=True
    )
    thread.start()
    return thread


def _ws_tick_log_due() -> bool:
    with _METRICS_LOCK:
        count = _METRICS["ws_tick_count"]
    return count > 0 and int(count) % _TICK_LOG_SAMPLE == 0


INTRADAY_MARKET_STATE: IntradayMarketState | None = None
INTRADAY_STREAM: AngelIntradayStream | None = None
_SINGLETON_LOCK = threading.Lock()


def get_intraday_market_state() -> IntradayMarketState:
    global INTRADAY_MARKET_STATE, INTRADAY_STREAM
    with _SINGLETON_LOCK:
        if INTRADAY_MARKET_STATE is None:
            INTRADAY_MARKET_STATE = IntradayMarketState()
            INTRADAY_STREAM = AngelIntradayStream(INTRADAY_MARKET_STATE)
        return INTRADAY_MARKET_STATE


def get_intraday_stream() -> AngelIntradayStream:
    get_intraday_market_state()
    return INTRADAY_STREAM  # type: ignore[return-value]


__all__ = [
    "AngelIntradayStream",
    "IntradayMarketState",
    "IntradayUniverse",
    "get_intraday_market_state",
    "get_intraday_stream",
    "metrics_snapshot",
]







