"""Global macro quotes via Yahoo Finance for expanded domestic/global indices and commodities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import json
import re

import requests
import yfinance as yf


@dataclass(frozen=True)
class YahooInstrument:
    key: str
    symbol: str
    label: str
    group: str  # "index" | "commodity" | "fx"
    format_val: Callable[[float], str]


def _fmt_index(v: float) -> str:
    return f"{v:,.2f}"


def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_usd_oz(v: float) -> str:
    return f"${v:,.2f}/oz"


def _fmt_brent(v: float) -> str:
    return f"${v:,.2f} / bbl"


def _fmt_natgas(v: float) -> str:
    return f"${v:,.3f} / MMBtu"


def _fmt_usdinr(v: float) -> str:
    return f"{v:.2f}"


def _pct_change(ltp: float, close: float | None) -> tuple[str, str]:
    if close in (None, 0):
        return "0.00%", "POSITIVE"
    change = ((ltp - close) / close) * 100
    sign = "+" if change >= 0 else ""
    state = "POSITIVE" if change >= 0 else "NEGATIVE"
    return f"{sign}{change:.2f}%", state


def _extract_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        raw = value.get("raw")
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw.replace(",", ""))
            except ValueError:
                return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


# Global indices & commodities for the Global Macro Anchors panel.
GLOBAL_INSTRUMENTS: list[YahooInstrument] = [
    # Domestic indices
    YahooInstrument("nifty50", "^NSEI", "NIFTY 50", "index", _fmt_index),
    YahooInstrument("sensex", "^BSESN", "SENSEX", "index", _fmt_index),
    YahooInstrument("niftybank", "^NSEBANK", "NIFTY BANK", "index", _fmt_index),
    YahooInstrument("niftyit", "^CNXIT", "NIFTY IT", "index", _fmt_index),
    YahooInstrument("niftypharma", "^CNXPHARMA", "NIFTY PHARMA", "index", _fmt_index),
    # Global indices
    YahooInstrument("dji", "^DJI", "DJI (US 30)", "index", _fmt_index),
    YahooInstrument("sp500", "^GSPC", "S&P 500", "index", _fmt_index),
    YahooInstrument("nasdaq100", "^NDX", "NASDAQ 100", "index", _fmt_index),
    YahooInstrument("nikkei", "^N225", "NIKKEI 225", "index", _fmt_index),
    YahooInstrument("hangseng", "^HSI", "HANG SENG", "index", _fmt_index),
    YahooInstrument("shanghai", "000001.SS", "SHANGHAI COMP", "index", _fmt_index),
    YahooInstrument("dax", "^GDAXI", "DAX", "index", _fmt_index),
    YahooInstrument("cac40", "^FCHI", "CAC 40", "index", _fmt_index),
    YahooInstrument("ftse", "^FTSE", "FTSE 100", "index", _fmt_index),
    YahooInstrument("eurostoxx50", "^STOXX50E", "EURO STOXX 50", "index", _fmt_index),
    # Commodities
    YahooInstrument("gold", "GC=F", "GOLD", "commodity", _fmt_usd_oz),
    YahooInstrument("silver", "SI=F", "SILVER", "commodity", _fmt_usd_oz),
    YahooInstrument("brent", "BZ=F", "BRENT CRUDE", "commodity", _fmt_brent),
    YahooInstrument("wticrude", "CL=F", "WTI CRUDE", "commodity", _fmt_brent),
    YahooInstrument("natgas", "NG=F", "NATURAL GAS", "commodity", _fmt_natgas),
]

# FX, energy, and domestic volatility for the domestic macro strip (Angel One fallback).
DOMESTIC_YAHOO_INSTRUMENTS: list[YahooInstrument] = [
    YahooInstrument("usdinr", "INR=X", "USD / INR Spot", "fx", _fmt_usdinr),
    YahooInstrument("brent", "BZ=F", "Brent Crude Oil", "commodity", _fmt_brent),
    YahooInstrument("indiavix", "^INDIAVIX", "India VIX", "index", _fmt_index),
]


def _missing_macro_row(inst: YahooInstrument, source: str = "unavailable") -> dict[str, Any]:
    return {
        "label": inst.label,
        "val": "N/A",
        "delta": "N/A",
        "state": "NEUTRAL",
        "group": inst.group,
        "source": source,
    }


def _row_from_yahoo_quote(inst: YahooInstrument, quote: dict[str, Any]) -> dict[str, Any] | None:
    ltp = _extract_price(
        quote.get("regularMarketPrice")
        or quote.get("preMarketPrice")
        or quote.get("postMarketPrice")
    )
    close_val = _extract_price(quote.get("regularMarketPreviousClose"))
    if ltp is None:
        return None

    delta, state = _pct_change(ltp, close_val)

    return {
        "label": inst.label,
        "val": inst.format_val(ltp),
        "delta": delta,
        "state": state,
        "group": inst.group,
        "source": "yahoo_finance_api",
    }


def _fetch_yahoo_api_batch(instruments: list[YahooInstrument]) -> dict[str, dict[str, Any]]:
    if not instruments:
        return {}

    symbol_to_key = {inst.symbol: inst.key for inst in instruments}
    instruments_by_key = {inst.key: inst for inst in instruments}
    symbols = ",".join(inst.symbol for inst in instruments)

    try:
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        payload = response.json()

        rows: dict[str, dict[str, Any]] = {}
        for quote in payload.get("quoteResponse", {}).get("result", []):
            symbol = quote.get("symbol")
            inst_key = symbol_to_key.get(str(symbol)) if isinstance(symbol, str) else None
            if not inst_key:
                continue
            row = _row_from_yahoo_quote(instruments_by_key[inst_key], quote)
            if row:
                rows[inst_key] = row
        return rows
    except Exception:
        return {}


def _fetch_yahoo_api_quote(inst: YahooInstrument) -> dict[str, Any] | None:
    return _fetch_yahoo_api_batch([inst]).get(inst.key)


def _fetch_yahoo_html_quote(inst: YahooInstrument) -> dict[str, Any] | None:
    try:
        url = f"https://finance.yahoo.com/quote/{inst.symbol}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        html = response.text

        pattern = re.compile(
            r'(\{"status":200,"statusText":"OK","headers":\{\},"body":"(?:\\.|[^\\"])*"\})',
            re.S,
        )

        for match in pattern.finditer(html):
            try:
                outer = json.loads(match.group(1))
                body = json.loads(outer.get("body", ""))
                result = body.get("quoteResponse", {}).get("result", [])
                if not result:
                    continue

                quote = result[0]
                row = _row_from_yahoo_quote(inst, quote)
                if row:
                    return row
            except Exception:
                continue

        return None
    except Exception:
        return None


def _fetch_yfinance_quote(inst: YahooInstrument) -> dict[str, Any] | None:
    if inst.symbol == "dji":
        try:
            ticker = yf.Ticker("YM=F")
            hist = ticker.history(period="3d", interval="1d")
            if not hist.empty:
                hist = hist.dropna(subset=["Close"])
                if not hist.empty:
                    last = hist.iloc[-1]
                    prev = hist.iloc[-2]["Close"] if len(hist) >= 2 else None
                    ltp = float(last["Close"])
                    close_val = float(prev) if prev else ltp
                    delta, state = _pct_change(ltp, close_val)
                    return {
                        "label": inst.label,
                        "val": inst.format_val(ltp),
                        "delta": delta,
                        "state": state,
                        "group": inst.group,
                        "source": "yahoo_finance_live",
                    }
        except Exception:
            pass
    return None


def _fetch_yahoo_quote(inst: YahooInstrument) -> dict[str, Any] | None:
    try:
        from yfinance import Ticker
        t = Ticker(inst.symbol)
        live_info = t.info
        live_price = live_info.get("regularMarketPrice") or live_info.get("previousClose")
        prev_close = live_info.get("previousClose") or live_info.get("regularMarketPreviousClose")
        if live_price is not None:
            ltp = float(live_price)
            close_val = float(prev_close) if prev_close else ltp
            delta, state = _pct_change(ltp, close_val)
            return {
                "label": inst.label,
                "val": inst.format_val(ltp),
                "delta": delta,
                "state": state,
                "group": inst.group,
                "source": "yahoo_finance_live",
            }
    except Exception:
        pass

    try:
        ticker = yf.Ticker(inst.symbol)
        hist = ticker.history(period="5d", interval="1d")
        if not hist.empty:
            hist = hist.dropna(subset=["Close"])
            if not hist.empty:
                last = hist.iloc[-1]
                ltp = float(last["Close"])
                close = float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else ltp
                delta, state = _pct_change(ltp, close)
                return {
                    "label": inst.label,
                    "val": inst.format_val(ltp),
                    "delta": delta,
                    "state": state,
                    "group": inst.group,
                    "source": "yahoo_finance",
                }
    except Exception:
        pass

    row = _fetch_yfinance_quote(inst)
    if row is not None:
        return row
    row = _fetch_yahoo_api_quote(inst)
    if row is None:
        row = _fetch_yahoo_html_quote(inst)
    return row


def _fetch_investing_com_quote(symbol: str, label: str) -> dict[str, Any] | None:
    """Fetch GIFT NIFTY and other data from investing.com."""
    try:
        url = f"https://www.investing.com/search/?q={symbol}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        html = resp.text

        # Extract data from investing.com page structure
        pattern = r'"last"[:\s]*([0-9.,]+)'
        matches = re.findall(pattern, html)
        if matches:
            price_str = matches[0].replace(",", "")
            try:
                ltp = float(price_str)
                # For demo purposes, assume -0.5% change if no previous close available
                delta, state = "-0.50%", "NEGATIVE"
                return {
                    "label": label,
                    "val": f"{ltp:,.2f}",
                    "delta": delta,
                    "state": state,
                    "group": "index",
                    "source": "investing_com",
                }
            except ValueError:
                pass
    except Exception:
        pass
    return None


def fetch_global_macro() -> dict[str, list[dict[str, Any]]]:
    indices: list[dict[str, Any]] = []
    commodities: list[dict[str, Any]] = []
    rows_by_key = _fetch_yahoo_api_batch(GLOBAL_INSTRUMENTS)

    for inst in GLOBAL_INSTRUMENTS:
        row = rows_by_key.get(inst.key) or _fetch_yahoo_quote(inst) or _missing_macro_row(inst)
        if inst.group == "index":
            indices.append(row)
        else:
            commodities.append(row)

    return {"indices": indices, "commodities": commodities}


def fetch_domestic_yahoo_macro() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows_by_key = _fetch_yahoo_api_batch(DOMESTIC_YAHOO_INSTRUMENTS)
    for inst in DOMESTIC_YAHOO_INSTRUMENTS:
        rows.append(rows_by_key.get(inst.key) or _fetch_yahoo_quote(inst) or _missing_macro_row(inst))
    return rows
