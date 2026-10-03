from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import EventType, TERMINAL_EVENTS


class IdempotencyConflict(RuntimeError):
    pass


class TerminalStateConflict(RuntimeError):
    pass


class SwingLedger:
    _initialization_lock = threading.Lock()
    _initialized_paths: set[str] = set()
    _positions_state_locks: dict[str, threading.Lock] = {}

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        resolved = str(Path(path).resolve())
        if resolved not in self._initialized_paths:
            with self._initialization_lock:
                if resolved not in self._initialized_paths:
                    self._initialize()
                    self._initialized_paths.add(resolved)

    def _connect(self, *, initialize: bool = False) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        if initialize:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect(initialize=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS swing_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL UNIQUE,
                decision_id TEXT NOT NULL,
                position_id TEXT,
                symbol TEXT NOT NULL,
                session_date TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS swing_events_position_idx ON swing_events(position_id, sequence)")
            db.execute("CREATE INDEX IF NOT EXISTS swing_events_session_idx ON swing_events(session_date, sequence)")

    def append(self, *, idempotency_key: str, decision_id: str, symbol: str, session_date: str, event_type: EventType | str, payload: dict[str, Any], event_timestamp: str, position_id: str | None = None) -> dict[str, Any]:
        event = {
            "eventId": str(uuid.uuid4()), "idempotencyKey": idempotency_key,
            "decisionId": decision_id, "positionId": position_id, "symbol": symbol.upper(),
            "sessionDate": session_date, "eventType": str(event_type),
            "eventTimestamp": event_timestamp, "payload": payload,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        with self._connect() as db:
            existing = db.execute("SELECT * FROM swing_events WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                decoded = self._decode(existing)
                if decoded["eventType"] != str(event_type) or decoded["payload"] != payload:
                    raise IdempotencyConflict(f"idempotency key {idempotency_key} has different content")
                return decoded
            if position_id and str(event_type) != str(EventType.ADMIN_CORRECTION):
                terminal_values = tuple(str(value) for value in TERMINAL_EVENTS)
                placeholders = ",".join("?" for _ in terminal_values)
                terminal = db.execute(
                    f"SELECT 1 FROM swing_events WHERE position_id=? AND event_type IN ({placeholders}) LIMIT 1",
                    (position_id, *terminal_values),
                ).fetchone()
                if terminal:
                    raise TerminalStateConflict(f"position {position_id} is terminal")
            db.execute("INSERT INTO swing_events(event_id,idempotency_key,decision_id,position_id,symbol,session_date,event_type,event_timestamp,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (event["eventId"], idempotency_key, decision_id, position_id, event["symbol"], session_date, event["eventType"], event_timestamp, json.dumps(payload, sort_keys=True, default=str), event["createdAt"]))
        return event

    def events(self, *, session_date: str | None = None, position_id: str | None = None) -> list[dict[str, Any]]:
        query, values = "SELECT * FROM swing_events", []
        clauses = []
        if session_date:
            clauses.append("session_date=?"); values.append(session_date)
        if position_id:
            clauses.append("position_id=?"); values.append(position_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY sequence"
        with self._connect() as db:
            return [self._decode(row) for row in db.execute(query, values)]

    def _checkpoint_path(self) -> Path:
        return Path(f"{self.path}.positions.json")

    def _load_checkpoint(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._checkpoint_path().read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("positions"), dict):
            return None
        try:
            payload["maxSequence"] = int(payload.get("maxSequence") or 0)
        except (TypeError, ValueError):
            return None
        positions = {
            str(pid): dict(state)
            for pid, state in payload["positions"].items()
            if isinstance(state, dict)
        }
        payload["positions"] = positions
        return payload

    def _save_checkpoint(self, max_sequence: int, positions: dict[str, dict[str, Any]]) -> None:
        path = self._checkpoint_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps({"maxSequence": int(max_sequence), "positions": positions}, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError:
            pass

    def positions_state(self) -> dict[str, dict[str, Any]]:
        """Materialized per-position state, replaying only events newer than the
        sidecar checkpoint.

        The ledger is append-only with a monotonic sequence, so a checkpoint of
        each position's materialized state plus the sequence it reflects lets a
        cold read replay only newer events instead of the full history. This is
        what keeps first-read Swing sessions off a 100k+-event replay.
        """
        resolved = str(Path(self.path).resolve())
        lock = self._positions_state_locks.get(resolved)
        if lock is None:
            lock = self._positions_state_locks.setdefault(resolved, threading.Lock())
        with lock:
            return self._positions_state_locked()

    def _positions_state_locked(self) -> dict[str, dict[str, Any]]:
        terminal_names = {str(value) for value in TERMINAL_EVENTS}
        admin_type = str(EventType.ADMIN_CORRECTION)
        checkpoint = self._load_checkpoint()
        if checkpoint is not None:
            states = {pid: dict(state) for pid, state in checkpoint["positions"].items()}
            start_seq = int(checkpoint["maxSequence"])
        else:
            states = {}
            start_seq = 0
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM swing_events WHERE sequence>? AND position_id IS NOT NULL ORDER BY sequence",
                (start_seq,),
            ).fetchall()
            if not checkpoint:
                max_sequence = int(db.execute("SELECT COALESCE(MAX(sequence), 0) FROM swing_events").fetchone()[0])
            elif rows:
                max_sequence = int(rows[-1]["sequence"])
            else:
                max_sequence = start_seq
        for row in rows:
            event = self._decode(row)
            position_id = str(event.get("positionId") or "")
            if not position_id:
                continue
            state = states.get(position_id)
            if state is None:
                state = {}
            event_type = event["eventType"]
            if state.get("terminal") and event_type != admin_type:
                continue
            state.update(event.get("payload") or {})
            state.update({
                "decisionId": event.get("decisionId"),
                "positionId": position_id,
                "sessionDate": event.get("sessionDate"),
                "symbol": event.get("symbol"),
                "lastEventType": event_type,
                "lastEventAt": event.get("eventTimestamp"),
            })
            state["terminal"] = event_type in terminal_names
            states[position_id] = state
        self._save_checkpoint(max_sequence, states)
        return states

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        return {"sequence": row["sequence"], "eventId": row["event_id"], "idempotencyKey": row["idempotency_key"], "decisionId": row["decision_id"], "positionId": row["position_id"], "symbol": row["symbol"], "sessionDate": row["session_date"], "eventType": row["event_type"], "eventTimestamp": row["event_timestamp"], "payload": json.loads(row["payload_json"]), "createdAt": row["created_at"]}


def materialize_position(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    terminal = False
    terminal_names = {str(value) for value in TERMINAL_EVENTS}
    for event in events:
        if terminal and event["eventType"] != str(EventType.ADMIN_CORRECTION):
            continue
        state.update(event.get("payload") or {})
        state.update({"decisionId": event.get("decisionId"), "positionId": event.get("positionId"), "sessionDate": event.get("sessionDate"), "symbol": event.get("symbol"), "lastEventType": event.get("eventType"), "lastEventAt": event.get("eventTimestamp")})
        terminal = event["eventType"] in terminal_names
    state["terminal"] = terminal
    return state
