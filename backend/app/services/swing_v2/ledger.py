from __future__ import annotations

import json
import sqlite3
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
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
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
