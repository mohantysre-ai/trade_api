"""Shoonya symbol master (NSE_symbols.txt.zip) -> symbol/token maps. Fails closed when stale."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from typing import Iterable

from .config import IST
from .mapper import norm_symbol

_TOKEN_COLS = ("token", "tokenid")
_TRADING_COLS = ("tradingsymbol", "trading_symbol", "tsym")
_EXCH_COLS = ("exchange", "exch")
_INSTR_COLS = ("instrument", "series")
_SERIES_RANK = {"-EQ": 0, "-BE": 1, "-BZ": 2}


def _pick(header: list[str], names: Iterable[str]) -> int | None:
    lowered = [h.strip().lower() for h in header]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    return None


def _rank(trading_symbol: str) -> int:
    upper = trading_symbol.upper()
    for suffix, rank in _SERIES_RANK.items():
        if upper.endswith(suffix):
            return rank
    return 99


class InstrumentRegistry:
    def __init__(self) -> None:
        self._by_symbol: dict[str, str] = {}
        self._by_token: dict[str, str] = {}
        self.loaded_on: date | None = None
        self.exchange = "NSE"

    def __len__(self) -> int:
        return len(self._by_symbol)

    def load_text(self, text: str, *, today: date | None = None) -> int:
        text = text.lstrip("﻿")
        first = text.splitlines()[0] if text else ""
        delimiter = "|" if first.count("|") > first.count(",") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        header = next(reader, [])
        i_tok = _pick(header, _TOKEN_COLS)
        i_ts = _pick(header, _TRADING_COLS)
        i_exch = _pick(header, _EXCH_COLS)
        i_instr = _pick(header, _INSTR_COLS)
        if i_tok is None or i_ts is None:
            raise ValueError("symbol master header missing Token/TradingSymbol columns")
        best: dict[str, tuple[int, str]] = {}
        for row in reader:
            if len(row) <= max(i_tok, i_ts):
                continue
            trading = row[i_ts].strip()
            token = row[i_tok].strip()
            if not trading or not token:
                continue
            if i_exch is not None and len(row) > i_exch and row[i_exch].strip().upper() not in ("", "NSE"):
                continue
            if i_instr is not None and len(row) > i_instr and row[i_instr].strip().upper() not in ("", "EQ", "BE", "BZ"):
                continue
            rank = _rank(trading)
            if rank == 99:
                continue
            symbol = norm_symbol(trading)
            if symbol not in best or rank < best[symbol][0]:
                best[symbol] = (rank, token)
        if not best:
            raise ValueError("symbol master contained no NSE equity rows")
        self._by_symbol = {sym: tok for sym, (_r, tok) in best.items()}
        self._by_token = {tok: sym for sym, tok in self._by_symbol.items()}
        self.loaded_on = today or datetime.now(IST).date()
        return len(self._by_symbol)

    def load_zip(self, payload: bytes, *, today: date | None = None) -> int:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
            if not names:
                raise ValueError("empty symbol master archive")
            return self.load_text(archive.read(names[0]).decode("utf-8", "replace"), today=today)

    def token_for(self, symbol: str) -> str | None:
        return self._by_symbol.get(norm_symbol(symbol))

    def symbol_for(self, exch: str, token: str) -> str | None:
        if str(exch).upper() != self.exchange:
            return None
        return self._by_token.get(str(token))

    def is_stale(self, today: date | None = None, max_age_days: int = 1) -> bool:
        if self.loaded_on is None or not self._by_symbol:
            return True
        now = today or datetime.now(IST).date()
        return (now - self.loaded_on).days > max_age_days

    def mismatches(self, other: dict[str, str]) -> list[str]:
        return sorted(
            sym for sym, tok in other.items()
            if self._by_symbol.get(norm_symbol(sym)) not in (None, str(tok))
        )
