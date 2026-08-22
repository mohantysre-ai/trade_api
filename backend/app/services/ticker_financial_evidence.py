"""On-demand, source-labelled financial evidence for one NSE ticker.

This module is deliberately outside the deterministic selection path.  It is
called only when a user opens Terminal Intelligence for a ticker, and caches
the result so a 500-name snapshot never fans out into 500 fundamentals calls.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .json_atomic import atomic_update_json, load_json_with_fallback

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CACHE_PATH = BASE_DIR.parent / "data" / "ticker_financial_evidence.json"
CACHE_TTL_SECONDS = int(os.getenv("TICKER_FINANCIAL_EVIDENCE_TTL_SECONDS", "86400"))
FAILURE_TTL_SECONDS = int(os.getenv("TICKER_FINANCIAL_EVIDENCE_FAILURE_TTL_SECONDS", "600"))
FETCH_TIMEOUT_SECONDS = float(os.getenv("TICKER_FINANCIAL_EVIDENCE_TIMEOUT_SECONDS", "18"))


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _row(frame: Any, aliases: Iterable[str], period: int = 0) -> float | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    wanted = {_norm(alias) for alias in aliases}
    for label in getattr(frame, "index", []):
        if _norm(label) not in wanted:
            continue
        try:
            values = frame.loc[label]
            value = values.iloc[period] if hasattr(values, "iloc") else values
        except (IndexError, KeyError, TypeError):
            return None
        return _finite(value)
    return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _beneish(income: Any, balance: Any, cashflow: Any) -> float | None:
    revenue = [_row(income, ("Total Revenue", "Operating Revenue"), i) for i in (0, 1)]
    cogs = [_row(income, ("Cost Of Revenue", "Cost Of Goods Sold"), i) for i in (0, 1)]
    receivables = [_row(balance, ("Accounts Receivable", "Net Receivables"), i) for i in (0, 1)]
    current_assets = [_row(balance, ("Current Assets", "Total Current Assets"), i) for i in (0, 1)]
    ppe = [_row(balance, ("Net PPE", "Property Plant Equipment"), i) for i in (0, 1)]
    total_assets = [_row(balance, ("Total Assets",), i) for i in (0, 1)]
    depreciation = [_row(cashflow, ("Depreciation And Amortization", "Depreciation"), i) for i in (0, 1)]
    sga = [_row(income, ("Selling General And Administration", "Selling And Marketing Expense"), i) for i in (0, 1)]
    current_liabilities = [_row(balance, ("Current Liabilities", "Total Current Liabilities"), i) for i in (0, 1)]
    total_debt = [_row(balance, ("Total Debt",), i) for i in (0, 1)]
    operating_income = _row(income, ("Net Income", "Net Income Common Stockholders"), 0)
    operating_cash = _row(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"), 0)

    required = revenue + cogs + receivables + current_assets + ppe + total_assets + depreciation + sga + current_liabilities + total_debt
    if any(value is None for value in required) or operating_income is None or operating_cash is None:
        return None

    if any(value == 0 for value in (revenue[0], revenue[1], total_assets[0], total_assets[1])):
        return None
    gross_margin = [(revenue[i] - cogs[i]) / revenue[i] for i in (0, 1)]  # type: ignore[operator]
    dsri = _ratio(_ratio(receivables[0], revenue[0]), _ratio(receivables[1], revenue[1]))
    gmi = _ratio(gross_margin[1], gross_margin[0])
    asset_quality_current = _ratio((current_assets[0] or 0) + (ppe[0] or 0), total_assets[0])
    asset_quality_prior = _ratio((current_assets[1] or 0) + (ppe[1] or 0), total_assets[1])
    if asset_quality_current is None or asset_quality_prior is None:
        return None
    aqi = _ratio(
        1 - asset_quality_current,
        1 - asset_quality_prior,
    )
    sgi = _ratio(revenue[0], revenue[1])
    depi = _ratio(
        _ratio(depreciation[1], (ppe[1] or 0) + (depreciation[1] or 0)),
        _ratio(depreciation[0], (ppe[0] or 0) + (depreciation[0] or 0)),
    )
    sgai = _ratio(_ratio(sga[0], revenue[0]), _ratio(sga[1], revenue[1]))
    lvgi = _ratio(
        _ratio((current_liabilities[0] or 0) + (total_debt[0] or 0), total_assets[0]),
        _ratio((current_liabilities[1] or 0) + (total_debt[1] or 0), total_assets[1]),
    )
    tata = _ratio(operating_income - operating_cash, total_assets[0])
    components = (dsri, gmi, aqi, sgi, depi, sgai, lvgi, tata)
    if any(value is None for value in components):
        return None
    return (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )


def _altman(income: Any, balance: Any, market_cap: float | None) -> float | None:
    current_assets = _row(balance, ("Current Assets", "Total Current Assets"))
    current_liabilities = _row(balance, ("Current Liabilities", "Total Current Liabilities"))
    total_assets = _row(balance, ("Total Assets",))
    retained_earnings = _row(balance, ("Retained Earnings",))
    total_liabilities = _row(balance, ("Total Liabilities Net Minority Interest", "Total Liabilities"))
    ebit = _row(income, ("EBIT", "Operating Income"))
    revenue = _row(income, ("Total Revenue", "Operating Revenue"))
    if any(value is None for value in (current_assets, current_liabilities, total_assets, retained_earnings, total_liabilities, ebit, revenue, market_cap)):
        return None
    if total_assets == 0 or total_liabilities == 0:
        return None
    working_capital = current_assets - current_liabilities  # type: ignore[operator]
    return (
        1.2 * working_capital / total_assets
        + 1.4 * retained_earnings / total_assets
        + 3.3 * ebit / total_assets
        + 0.6 * market_cap / total_liabilities
        + revenue / total_assets
    )


def _mansfield(stock_history: Any, benchmark_history: Any) -> float | None:
    try:
        stock_close = stock_history["Close"].dropna()
        bench_close = benchmark_history["Close"].dropna()
        aligned = stock_close.to_frame("stock").join(bench_close.to_frame("bench"), how="inner")
        aligned = aligned[(aligned["stock"] > 0) & (aligned["bench"] > 0)].tail(252)
        if len(aligned) < 60:
            return None
        relative = aligned["stock"] / aligned["bench"]
        mean_relative = float(relative.mean())
        return ((float(relative.iloc[-1]) / mean_relative) - 1.0) * 100.0 if mean_relative else None
    except Exception:
        return None


def _money_cr(value: float | None) -> float | None:
    return round(value / 10_000_000, 2) if value is not None else None


def _screener_value(frame: Any, aliases: Iterable[str], column: Any) -> float | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    label_column = frame.columns[0]
    wanted = {_norm(alias) for alias in aliases}
    for _, row in frame.iterrows():
        if _norm(row.get(label_column)) not in wanted:
            continue
        raw = str(row.get(column) or "").replace(",", "").replace("%", "").strip()
        return _finite(raw)
    return None


def _fetch_screener_fallback(ticker: str, primary_error: str) -> dict[str, Any]:
    """Use Screener's public annual tables when Yahoo is temporarily rate-limited."""
    from io import StringIO

    import pandas as pd
    import requests

    url = f"https://www.screener.in/company/{quote(ticker, safe='')}/consolidated/"
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; sigq-terminal/1.0)"},
        timeout=(5, 15),
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    pnl = None
    cashflow = None
    for frame in tables:
        labels = {_norm(item) for item in frame.iloc[:, 0].tolist()} if not frame.empty else set()
        if {"sales", "operatingprofit"}.issubset(labels):
            annual_columns = [column for column in frame.columns[1:] if re.fullmatch(r"Mar \d{4}", str(column))]
            if len(annual_columns) >= 2:
                pnl = frame
        if "cashfromoperatingactivity" in labels:
            cashflow = frame
    if pnl is None or cashflow is None:
        raise RuntimeError("Screener annual financial tables were not found")

    annual_columns = [column for column in pnl.columns[1:] if re.fullmatch(r"Mar \d{4}", str(column))]
    latest, previous = annual_columns[-1], annual_columns[-2]
    revenue_now = _screener_value(pnl, ("Sales",), latest)
    revenue_prev = _screener_value(pnl, ("Sales",), previous)
    operating_profit = _screener_value(pnl, ("Operating Profit",), latest)
    ocf = _screener_value(cashflow, ("Cash from Operating Activity",), latest)
    ocf_operating_profit = _ratio(ocf, operating_profit)
    revenue_growth = ((revenue_now / revenue_prev) - 1.0) * 100.0 if revenue_now is not None and revenue_prev not in (None, 0) else None

    return {
        "ticker": ticker,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Screener.in",
        "sourceSymbol": ticker,
        "sourceUrl": url,
        "status": "PARTIAL",
        "metrics": {
            "beneish_m_score": "NOT_CALCULATED — receivables/current-asset line items are absent from the fallback source",
            "altman_z_score": "NOT_CALCULATED — working-capital and market-value inputs are absent from the fallback source",
            "ocf_ebitda_ratio": (
                f"{ocf_operating_profit:.2f}x (OCF/operating profit; Screener.in)"
                if ocf_operating_profit is not None
                else "NOT_CALCULATED — cash flow or operating profit is absent from the fallback source"
            ),
            "mansfield_relative_strength": "NOT_CALCULATED — benchmark-relative price history is absent from the fallback source",
        },
        "missingMetrics": ["beneish_m_score", "altman_z_score", "mansfield_relative_strength"],
        "financialSnapshot": {
            "reportedRevenueCr": round(revenue_now, 2) if revenue_now is not None else None,
            "reportedRevenueGrowthPct": round(revenue_growth, 2) if revenue_growth is not None else None,
            "operatingCashFlowCr": round(ocf, 2) if ocf is not None else None,
            "ebitdaCr": round(operating_profit, 2) if operating_profit is not None else None,
            "marketCapCr": None,
            "forwardPe": None,
            "priceToBook": None,
        },
        "primarySourceError": primary_error[:240],
    }


def _fetch_uncached(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    symbol = f"{ticker}.NS"
    instrument = yf.Ticker(symbol)
    income = instrument.financials
    balance = instrument.balance_sheet
    cashflow = instrument.cashflow
    try:
        info = instrument.info or {}
    except Exception:
        info = {}
    market_cap = _finite(info.get("marketCap"))
    if market_cap is None:
        try:
            market_cap = _finite(instrument.fast_info.get("market_cap"))
        except Exception:
            market_cap = None

    beneish = _beneish(income, balance, cashflow)
    altman = _altman(income, balance, market_cap)
    ocf = _row(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"))
    ebitda = _row(income, ("EBITDA", "Normalized EBITDA"))
    ocf_ebitda = _ratio(ocf, ebitda)

    stock_history = instrument.history(period="18mo", interval="1d", auto_adjust=True)
    benchmark_history = yf.Ticker("^NSEI").history(period="18mo", interval="1d", auto_adjust=True)
    mansfield = _mansfield(stock_history, benchmark_history)

    revenue_now = _row(income, ("Total Revenue", "Operating Revenue"), 0)
    revenue_prev = _row(income, ("Total Revenue", "Operating Revenue"), 1)
    revenue_growth = None
    if revenue_now is not None and revenue_prev not in (None, 0):
        revenue_growth = ((revenue_now / revenue_prev) - 1.0) * 100.0

    metrics: dict[str, str] = {}
    missing: list[str] = []
    calculated = {
        "beneish_m_score": beneish,
        "altman_z_score": altman,
        "ocf_ebitda_ratio": ocf_ebitda,
        "mansfield_relative_strength": mansfield,
    }
    labels = {
        "beneish_m_score": "financial-statement line items",
        "altman_z_score": "balance-sheet/market-cap line items",
        "ocf_ebitda_ratio": "operating cash flow or EBITDA",
        "mansfield_relative_strength": "aligned 52-week NSE price history",
    }
    for key, value in calculated.items():
        if value is None:
            metrics[key] = f"NOT_CALCULATED — missing {labels[key]} from Yahoo Finance"
            missing.append(key)
        elif key == "ocf_ebitda_ratio":
            metrics[key] = f"{value:.2f}x"
        elif key == "mansfield_relative_strength":
            metrics[key] = f"{value:+.2f}% vs NIFTY 50"
        else:
            metrics[key] = f"{value:.2f}"

    return {
        "ticker": ticker,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance",
        "sourceSymbol": symbol,
        "sourceUrl": f"https://finance.yahoo.com/quote/{symbol}/financials/",
        "status": "READY" if not missing else "PARTIAL" if len(missing) < len(calculated) else "SOURCE_UNAVAILABLE",
        "metrics": metrics,
        "missingMetrics": missing,
        "financialSnapshot": {
            "reportedRevenueCr": _money_cr(revenue_now),
            "reportedRevenueGrowthPct": round(revenue_growth, 2) if revenue_growth is not None else None,
            "operatingCashFlowCr": _money_cr(ocf),
            "ebitdaCr": _money_cr(ebitda),
            "marketCapCr": _money_cr(market_cap),
            "forwardPe": _finite(info.get("forwardPE")),
            "priceToBook": _finite(info.get("priceToBook")),
        },
    }


def _fetch_with_fallback(ticker: str) -> dict[str, Any]:
    try:
        return _fetch_uncached(ticker)
    except Exception as exc:
        log.warning("Yahoo financial evidence failed for %s; trying Screener.in: %s", ticker, exc)
        return _fetch_screener_fallback(ticker, str(exc))


def _load_cache() -> dict[str, Any]:
    try:
        data = load_json_with_fallback(CACHE_PATH)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _fresh(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    generated = entry.get("generatedAt")
    if not generated:
        return False
    try:
        stamp = datetime.fromisoformat(str(generated).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    ttl = FAILURE_TTL_SECONDS if str(entry.get("status") or "").upper() == "SOURCE_UNAVAILABLE" else CACHE_TTL_SECONDS
    return (time.time() - stamp) <= ttl


def get_ticker_financial_evidence(ticker: str, *, force: bool = False) -> dict[str, Any]:
    symbol = str(ticker or "").upper().strip()
    cache = _load_cache()
    cached = cache.get(symbol)
    if not force and _fresh(cached):
        return dict(cached)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"ticker-evidence-{symbol}")
    future = executor.submit(_fetch_with_fallback, symbol)
    try:
        result = future.result(timeout=FETCH_TIMEOUT_SECONDS)
    except FutureTimeout:
        future.cancel()
        result = {
            "ticker": symbol,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo Finance",
            "status": "SOURCE_UNAVAILABLE",
            "metrics": {},
            "error": f"financial evidence fetch exceeded {FETCH_TIMEOUT_SECONDS:g}s",
        }
    except Exception as exc:
        result = {
            "ticker": symbol,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo Finance",
            "status": "SOURCE_UNAVAILABLE",
            "metrics": {},
            "error": str(exc)[:240],
        }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    atomic_update_json(CACHE_PATH, lambda data: {**data, symbol: result})
    return result


def ensure_ticker_financial_evidence(snapshot: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Attach one cached/on-demand evidence pack without touching selection fields."""
    if os.getenv("TICKER_FINANCIAL_EVIDENCE_ENABLED", "true").strip().lower() not in {"1", "true", "yes"}:
        return snapshot
    symbol = str(ticker or "").upper().strip()
    if not symbol:
        return snapshot
    block = dict(snapshot.get("tickerEvidenceByTicker") or {})
    existing = block.get(symbol)
    if _fresh(existing):
        return snapshot
    block[symbol] = get_ticker_financial_evidence(symbol)
    snapshot["tickerEvidenceByTicker"] = block
    return snapshot


__all__ = ["ensure_ticker_financial_evidence", "get_ticker_financial_evidence"]
