"""Process-local Angel WebSocket cache for the Index Options radar.

The stream is advisory market data only.  It never exposes or invokes an order
method. REST remains the cold-start/backfill path and the radar's deterministic
gates remain authoritative.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

IST_ZONE = ZoneInfo("Asia/Kolkata")
EXCHANGE_TYPES = {"NSE": 1, "NFO": 2, "BSE": 3, "BFO": 4}


def _number(value: Any, *, scale: float = 1.0) -> float | None:
    try:
        result = float(value) / scale
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return result if result >= 0 else None


class AngelIndexStream:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._socket: Any = None
        self._opened = False
        self._thread: threading.Thread | None = None
        self._wanted: dict[tuple[int, str], dict[str, str]] = {}
        self._subscribed: set[tuple[int, str]] = set()
        self._quotes: dict[str, dict[str, Any]] = {}
        self._bars: dict[str, dict[str, list[Any]]] = {}
        self._stop = False
        self._client: Any = None

    def ensure(self, client: Any, instruments: list[dict[str, str]]) -> None:
        if os.getenv("INDEX_OPTIONS_STREAM_ENABLED", "1") != "1" or not callable(getattr(client, "connect", None)):
            return
        added = False
        with self._lock:
            self._client = client
            for item in instruments:
                exchange = str(item.get("exchange") or "").upper()
                token = str(item.get("token") or "")
                exchange_type = EXCHANGE_TYPES.get(exchange)
                if not exchange_type or not token:
                    continue
                key = (exchange_type, token)
                if key not in self._wanted:
                    self._wanted[key] = dict(item)
                    added = True
            if self._thread is None or not self._thread.is_alive():
                self._stop = False
                self._thread = threading.Thread(target=self._run, name="angel-index-stream", daemon=True)
                self._thread.start()
                return
            socket = self._socket
        if added and socket is not None:
            try:
                self._subscribe_missing(socket)
            except Exception:
                # The socket may exist but not have completed its open callback.
                # _on_open/reconnect will subscribe the same pending tokens.
                logging.getLogger(__name__).debug("Angel stream subscription deferred", exc_info=True)

    def quote(self, token: str, *, max_age_seconds: float = 12.0) -> dict[str, Any] | None:
        with self._lock:
            row = dict(self._quotes.get(str(token)) or {})
        received = row.get("receivedEpoch")
        if not row or not isinstance(received, (int, float)) or time.time() - received > max_age_seconds:
            return None
        return row

    def candles(self, key: str) -> list[list[Any]]:
        with self._lock:
            return list((self._bars.get(key) or {}).values())

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = max((row.get("receivedEpoch", 0) for row in self._quotes.values()), default=0)
            return {
                "connected": self._opened,
                "subscribed": len(self._subscribed),
                "lastTickAt": datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest else None,
            }

    def _credentials(self) -> tuple[str, str, str, str]:
        smart = self._client.connect()
        auth = str(getattr(smart, "access_token", "") or getattr(smart, "authToken", ""))
        feed = str(smart.getfeedToken() if hasattr(smart, "getfeedToken") else getattr(smart, "feed_token", ""))
        if auth.lower().startswith("bearer "):
            auth = auth.split(" ", 1)[1]
        if not auth or not feed:
            raise RuntimeError("Angel WebSocket session tokens unavailable")
        return auth, str(self._client.api_key), str(self._client.client_id), feed

    def _run(self) -> None:
        delay = 1.0
        log = logging.getLogger(__name__)
        while not self._stop:
            try:
                from SmartApi.smartWebSocketV2 import SmartWebSocketV2

                socket = SmartWebSocketV2(*self._credentials())
                socket.on_open = lambda ws: self._on_open(ws)
                socket.on_data = lambda ws, message: self._on_data(message)
                socket.on_error = lambda ws, error: log.warning("Angel index stream error: %s", error)
                socket.on_close = lambda ws: self._on_close()
                with self._lock:
                    self._socket = socket
                    self._subscribed.clear()
                socket.connect()
                delay = 1.0
            except Exception as exc:
                log.warning("Angel index stream reconnecting: %s", exc)
            finally:
                self._on_close()
            if not self._stop:
                time.sleep(delay)
                delay = min(delay * 2.0, 30.0)

    def _on_open(self, socket: Any) -> None:
        with self._lock:
            self._opened = True
        self._subscribe_missing(socket)

    def _on_close(self) -> None:
        with self._lock:
            self._socket = None
            self._opened = False
            self._subscribed.clear()

    def _subscribe_missing(self, socket: Any) -> None:
        with self._lock:
            missing = [item for item in self._wanted if item not in self._subscribed]
        grouped: dict[int, list[str]] = {}
        for exchange_type, token in missing:
            grouped.setdefault(exchange_type, []).append(token)
        if not grouped:
            return
        token_list = [{"exchangeType": exchange, "tokens": tokens} for exchange, tokens in grouped.items()]
        socket.subscribe("sigqixopt", 3, token_list)  # mode 3 = SNAP_QUOTE; correlation id <= 10 chars
        with self._lock:
            self._subscribed.update(missing)

    def _on_data(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        token = str(message.get("token") or "")
        if not token:
            return
        now = datetime.now(timezone.utc)
        raw_ltp = message.get("last_traded_price")
        ltp = _number(raw_ltp, scale=100.0)
        if ltp is None:
            ltp = _number(message.get("ltp"))
        if ltp is None or ltp <= 0:
            return
        row = {
            "ltp": ltp,
            "opnInterest": _number(message.get("open_interest")),
            "tradeVolume": _number(message.get("volume_trade_for_the_day")),
            "close": _number(message.get("closed_price"), scale=100.0),
            "receivedAt": now.isoformat(),
            "receivedEpoch": now.timestamp(),
            "source": "ANGEL_WEBSOCKET",
        }
        buy_depth = message.get("best_5_buy_data") if isinstance(message.get("best_5_buy_data"), list) else []
        sell_depth = message.get("best_5_sell_data") if isinstance(message.get("best_5_sell_data"), list) else []
        # Some SmartWebSocketV2 releases expose the parsed buy/sell arrays
        # reversed. Derive the executable spread defensively from both sides.
        depth_prices = [price for price in (
            _number(buy_depth[0].get("price"), scale=100.0) if buy_depth and isinstance(buy_depth[0], dict) else None,
            _number(sell_depth[0].get("price"), scale=100.0) if sell_depth and isinstance(sell_depth[0], dict) else None,
        ) if price is not None and price > 0]
        if len(depth_prices) == 2:
            row["bestBidPrice"] = min(depth_prices)
            row["bestAskPrice"] = max(depth_prices)
        with self._lock:
            self._quotes[token] = row
            wanted = self._wanted.get((int(message.get("exchange_type") or 0), token))
            if not wanted:
                wanted = next((value for (_, wanted_token), value in self._wanted.items() if wanted_token == token), None)
            index_key = str((wanted or {}).get("indexKey") or "")
            if not index_key or str((wanted or {}).get("kind")) != "INDEX":
                return
            stamp = now.astimezone(IST_ZONE)
            minute = stamp.minute - stamp.minute % 5
            bucket = stamp.replace(minute=minute, second=0, microsecond=0)
            bucket_key = bucket.isoformat()
            bars = self._bars.setdefault(index_key, {})
            current = bars.get(bucket_key)
            if current is None:
                bars[bucket_key] = [bucket_key, ltp, ltp, ltp, ltp, 0]
            else:
                current[2] = max(float(current[2]), ltp)
                current[3] = min(float(current[3]), ltp)
                current[4] = ltp


ANGEL_INDEX_STREAM = AngelIndexStream()
