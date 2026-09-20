from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any


def trade_id(row: dict[str, Any]) -> str:
    identity = row.get("strategyPositionId") or row.get("id")
    if identity:
        return str(identity)
    identity = {key: row.get(key) for key in (
        "symbol", "index", "strategyType", "enteredAt", "entryPrice", "quantity",
    )}
    return sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:24]


def merge_paper_books(paper: dict[str, Any], strategy: dict[str, Any] | None) -> dict[str, Any]:
    book = deepcopy(paper)
    rows: dict[str, dict[str, Any]] = {}
    for status, source in (("OPEN", paper.get("open")), ("CLOSED", paper.get("closed"))):
        for supplied in source or []:
            if not isinstance(supplied, dict):
                continue
            row = deepcopy(supplied)
            row.update({"id": trade_id(row), "status": status})
            rows[row["id"]] = row
    strategy_rows = [deepcopy(r) for r in (strategy or {}).get("positions") or [] if isinstance(r, dict)]
    if strategy_rows:
        durable_ids = {str(r.get("strategyPositionId") or "") for r in strategy_rows}
        durable_keys = {
            (str(r.get("index") or ""), str(r.get("strategyId") or r.get("strategy") or ""))
            for r in strategy_rows
        }
        rows = {
            key: value
            for key, value in rows.items()
            if str(value.get("strategyPositionId") or "") not in durable_ids
            and (str(value.get("index")), str(value.get("strategyType"))) not in durable_keys
        }
        for supplied in strategy_rows:
            identity = trade_id(supplied)
            rows[identity] = {
                **supplied,
                "id": identity,
                "symbol": supplied.get("symbol") or supplied.get("strategyId") or supplied.get("strategy"),
                "strategyType": supplied.get("strategyId") or supplied.get("strategy"),
                "strategyMode": "QUANT_V2",
                "projectionOnly": True,
                "pnl": supplied.get("realizedPnl") or 0.0,
            }
    book["open"] = [r for r in rows.values() if r.get("status") == "OPEN"]
    book["closed"] = [r for r in rows.values() if r.get("status") == "CLOSED"]
    book["entryCount"] = len(book["open"]) + len(book["closed"])
    book["closedCount"] = len(book["closed"])
    book["openCount"] = len(book["open"])
    book["realizedPnl"] = round(sum(float(r.get("pnl") or 0) for r in book["closed"]), 2)
    book["openPnl"] = round(sum(float(r.get("unrealizedPnl") or 0) for r in book["open"]), 2)
    book["totalPnl"] = round(book["realizedPnl"] + book["openPnl"], 2)
    book["projectionAuthority"] = "MULTI_LEG_STRATEGY_BOOK_FOR_DEFINED_RISK_SELLERS"
    return book


def eod_positions(book: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**r, "pnl": round(float(r.get("unrealizedPnl") or 0), 2), "pnlKind": "unrealised"}
        for r in book.get("open") or []
    ] + [
        {**r, "pnl": round(float(r.get("pnl") or 0), 2), "pnlKind": "realised"}
        for r in book.get("closed") or []
    ]
