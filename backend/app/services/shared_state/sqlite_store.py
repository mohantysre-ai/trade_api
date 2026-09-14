"""SQLite WAL durable cache for restart recovery and historical state."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .schemas import ViewVersion


_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "shared_state.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA_STATEMENTS = [
    "CREATE TABLE IF NOT EXISTS quotes_latest (symbol TEXT PRIMARY KEY, ltp REAL, bid REAL, ask REAL, volume REAL, oi REAL, source TEXT, updated_at INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS bars_5m (symbol TEXT NOT NULL, bucket TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, bucket))",
    "CREATE TABLE IF NOT EXISTS view_snapshot (namespace TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL, updated_at INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS trade_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS strategy_events (id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL)",
]


class SQLiteStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path else _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_queue: list[tuple[str, tuple[Any, ...]]] = []
        self._write_lock = threading.Lock()
        self._writer_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-64000")
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.commit()
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._connect()
        return self._local.conn

    def _ensure_writer(self) -> None:
        if self._started:
            return
        self._started = True
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def _writer_loop(self) -> None:
        while not self._stop.is_set():
            batch: list[tuple[str, tuple[Any, ...]]] = []
            with self._write_lock:
                if self._write_queue:
                    batch = self._write_queue[:50]
                    self._write_queue[: len(batch)] = []
            if not batch:
                self._stop.wait(0.1)
                continue
            try:
                conn = self._connect()
                with conn:
                    for stmt, args in batch:
                        conn.execute(stmt, args)
            except Exception:
                pass

    def enqueue(self, stmt: str, args: tuple[Any, ...]) -> None:
        self._ensure_writer()
        with self._write_lock:
            self._write_queue.append((stmt, args))

    def execute(self, stmt: str, args: tuple[Any, ...] = ()) -> Any:
        conn = self._get_conn()
        try:
            return conn.execute(stmt, args)
        except sqlite3.OperationalError:
            conn = self._connect()
            self._local.conn = conn
            return conn.execute(stmt, args)

    def persist_quote(self, quote: dict[str, Any]) -> None:
        self.enqueue(
            """
            INSERT INTO quotes_latest (symbol, ltp, bid, ask, volume, oi, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                ltp=excluded.ltp, bid=excluded.bid, ask=excluded.ask,
                volume=excluded.volume, oi=excluded.oi, source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (
                quote.get("symbol"),
                quote.get("ltp"),
                quote.get("bid"),
                quote.get("ask"),
                quote.get("volume"),
                quote.get("oi"),
                quote.get("source", ""),
                int(time.time()),
            ),
        )

    def persist_bar(self, symbol: str, interval: str, bar: dict[str, Any]) -> None:
        bucket = bar.get("bucket") or ""
        self.enqueue(
            """
            INSERT INTO bars_5m (symbol, bucket, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, bucket) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume
            """,
            (
                symbol,
                bucket,
                bar.get("open"),
                bar.get("high"),
                bar.get("low"),
                bar.get("close"),
                bar.get("volume"),
            ),
        )

    def persist_view_snapshot(self, namespace: str, version: ViewVersion) -> None:
        self.enqueue(
            """
            INSERT INTO view_snapshot (namespace, version, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace) DO UPDATE SET
                version=excluded.version, payload=excluded.payload,
                updated_at=excluded.updated_at
            """,
            (
                namespace,
                version.version,
                json.dumps(version.payload),
                int(version.updated_at),
            ),
        )

    def load_view_snapshot(self, namespace: str) -> dict[str, Any] | None:
        row = self.execute(
            "SELECT version, payload, updated_at FROM view_snapshot WHERE namespace = ?",
            (namespace,),
        ).fetchone()
        if not row:
            return None
        return {
            "version": row[0],
            "payload": json.loads(row[1]),
            "updatedAt": row[2],
        }

    def load_all_view_snapshots(self) -> dict[str, Any]:
        rows = self.execute("SELECT namespace, version, payload, updated_at FROM view_snapshot").fetchall()
        result: dict[str, Any] = {}
        for ns, ver, payload, ts in rows:
            result[ns] = {
                "version": ver,
                "payload": json.loads(payload),
                "updatedAt": ts,
            }
        return result

    def load_latest_quotes(self) -> dict[str, Any]:
        rows = self.execute("SELECT symbol, ltp, bid, ask, volume, oi, source, updated_at FROM quotes_latest").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            result[row[0]] = {
                "symbol": row[0],
                "ltp": row[1],
                "bid": row[2],
                "ask": row[3],
                "volume": row[4],
                "oi": row[5],
                "source": row[6],
                "updated_at": row[7],
            }
        return result

    def persist_trade_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.enqueue(
            "INSERT INTO trade_events (event_type, payload, created_at) VALUES (?, ?, ?)",
            (event_type, json.dumps(payload), int(time.time())),
        )

    def persist_strategy_event(self, strategy: str, event_type: str, payload: dict[str, Any]) -> None:
        self.enqueue(
            "INSERT INTO strategy_events (strategy, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (strategy, event_type, json.dumps(payload), int(time.time())),
        )

    def shutdown(self) -> None:
        self._stop.set()
        if self._writer_thread:
            self._writer_thread.join(timeout=2)


SQLITE_STORE: SQLiteStore | None = None


def get_sqlite_store() -> SQLiteStore:
    global SQLITE_STORE
    if SQLITE_STORE is None:
        SQLITE_STORE = SQLiteStore()
    return SQLITE_STORE
