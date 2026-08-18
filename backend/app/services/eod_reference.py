"""
Reference price provider for EOD analysis.

Fetches the 9:30 AM IST opening candle price for a given symbol from Angel One,
or falls back to a seed price table. Also provides mock EOD prices and
per-stock analysis (hedge-fund-style diagnosis).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time, timezone, timedelta
from typing import Any

log = logging.getLogger(__name__)

_IST_OFFSET = timezone(timedelta(hours=5, minutes=30))
_REFERENCE_DATE = date(2026, 7, 17)  # Friday
_REFERENCE_TIME = time(9, 30, 0)  # 9:30 AM IST

_SEED_REFERENCE_PRICES: dict[str, float] = {
    "KALAMANDIR": 91.97, "RAMASTEEL": 4.33, "GTLINFRA": 1.24, "VIKASLIFE": 1.34,
    "JAINREC": 328.80, "GREENPOWER": 9.95, "BSE": 3581.80, "BAJAJCON": 525.65,
    "VIKASECO": 1.15, "NCC": 139.60, "RELAXO": 439.95, "CUPID": 214.78,
    "NAVKARURB": 1.16, "BAJFINANCE": 1056.30, "ADANIENT": 3160.70, "ZEEL": 107.40,
    "BPCL": 315.55, "SBIN": 1044.30, "M&M": 3179.20, "PIRAMALFIN": 2144.30,
    "RELIANCE": 2950.00, "TCS": 4120.00, "HDFCBANK": 1680.00, "INFY": 1520.00,
    "BHARTIARTL": 1425.00, "LT": 3650.00, "SUNPHARMA": 1580.00, "TITAN": 3760.00,
    "MARUTI": 12450.00, "HINDUNILVR": 2650.00, "ITC": 480.00, "WIPRO": 510.00,
    "HCLTECH": 1680.00, "NTPC": 365.00, "POWERGRID": 320.00, "ONGC": 285.00,
    "COALINDIA": 490.00, "JSWSTEEL": 920.00, "TATASTEEL": 165.00, "INDUSINDBK": 1435.00,
    # --- Asset Matrix live picks (from today's ForensicPanel) ---
    "SYRMA": 1359.10, "BHEL": 422.00, "EXICOM": 161.51, "PERSISTENT": 5183.90,
    "COFORGE": 1508.40, "MPHASIS": 2394.20, "DATAPATTNS": 4085.80, "KAYNES": 3385.80,
    "NETWEB": 4244.30, "DIXON": 14329.00, "TATAELXSI": 3503.20, "HAL": 4500.70,
    "BEL": 409.45, "KPITTECH": 554.05, "ABCAPITAL": 401.55, "MAZDOCK": 2342.80,
    "GODREJPROP": 2102.10, "IRFC": 88.41, "SAPPHIRE": 182.08, "SMCGLOBAL": 81.67,
}

_REFERENCE_CACHE: dict[str, float] = {}

# ---------------------------------------------------------------------------
#  Per-symbol mock EOD prices — each symbol gets a unique move percent so
#  results are NOT all the same.  Moves are plausible for a single session
#  (Jul 19 is a Sunday, so the "EOD" represents where the stock would be
#  if the market were open).
# ---------------------------------------------------------------------------
_SYMBOL_MOVE_PCT: dict[str, float] = {
    # Scanner shorts (most moved against SHORT direction — good for longs, bad for shorts)
    "KALAMANDIR": +3.2, "RAMASTEEL": -2.1, "GTLINFRA": -1.5, "VIKASLIFE": +4.7,
    "JAINREC": -3.8, "GREENPOWER": +2.9, "BSE": +5.2, "BAJAJCON": -1.8,
    "VIKASECO": +3.5, "NCC": -2.5,
    # Scanner longs
    "RELAXO": -4.2, "CUPID": +2.1, "NAVKARURB": +1.8, "BAJFINANCE": +3.6,
    "ADANIENT": +4.8, "ZEEL": -3.0, "BPCL": +2.5, "SBIN": +3.1,
    "M&M": +1.2, "PIRAMALFIN": -2.8,
    # Swing longs
    "RELIANCE": +3.5, "TCS": -2.0, "HDFCBANK": +2.8, "INFY": -1.2,
    "BHARTIARTL": +4.1, "LT": +1.5, "TITAN": +2.2, "MARUTI": +3.9,
    "ITC": -0.5, "WIPRO": +1.8, "HCLTECH": +2.4, "NTPC": -3.3,
    "POWERGRID": +1.1, "COALINDIA": +2.7, "JSWSTEEL": -4.0, "TATASTEEL": -2.5,
    "INDUSINDBK": +3.3,
    # Swing shorts
    "SUNPHARMA": -2.5, "HINDUNILVR": -3.2, "ONGC": +1.5,
}

_MOCK_EOD_PRICES: dict[str, float] | None = None


def _build_mock_eod_prices() -> dict[str, float]:
    """Build July 19 mock EOD prices using per-symbol move % from reference."""
    eod: dict[str, float] = {}
    for sym, ref in _SEED_REFERENCE_PRICES.items():
        move_pct = _SYMBOL_MOVE_PCT.get(sym, 0.0)
        eod[sym] = round(ref * (1 + move_pct / 100), 2)
    return eod


def _angel_creds_available() -> bool:
    """Quick check if Angel One API credentials are set without connecting."""
    try:
        api_key = __import__('os').environ.get('ANGEL_API_KEY', '').strip()
        client_id = __import__('os').environ.get('ANGEL_CLIENT_ID', '').strip()
        totp = __import__('os').environ.get('ANGEL_TOTP_SECRET', '').strip()
        return bool(api_key and client_id and totp)
    except Exception:
        return False


def _fetch_930am_candle_from_angel(symbol: str) -> float | None:
    """Fetch 9:30 AM IST 5-minute candle open from Angel One for July 17, 2026.

    Validates the candle date matches July 17 before accepting the price.
    Otherwise returns None so the seed table is used instead.
    """
    if not _angel_creds_available():
        return None
    try:
        from .angel_one_feed import AngelOneClient
    except Exception:
        return None
    ref_dt = datetime.combine(_REFERENCE_DATE, _REFERENCE_TIME, tzinfo=_IST_OFFSET)
    from_dt = ref_dt
    to_dt = ref_dt + timedelta(minutes=5)
    client = AngelOneClient()
    try:
        from .angel_one_feed import _resolve_nse_equity
        resolved = _resolve_nse_equity(symbol, client=client)
        if not resolved:
            return None
        token, resolved_symbol = resolved
    except Exception as exc:
        log.debug("Angel equity resolve failed for %s: %s", symbol, exc)
        return None
    if not token:
        return None
    try:
        candles = client.fetch_candles("NSE", token, "FIVE_MINUTE", from_dt, to_dt)
    except Exception as exc:
        log.debug("Angel candle fetch failed for %s: %s", symbol, exc)
        return None
    if not candles or not isinstance(candles, list) or len(candles) < 1:
        log.debug("Angel returned no candles for %s on %s", symbol, _REFERENCE_DATE)
        return None
    row = candles[0]
    if isinstance(row, list) and len(row) >= 6:
        try:
            # Validate timestamp: row[0] should be the candle's datetime string
            ts_raw = str(row[0])
            if "2026-07-17" not in ts_raw and "2026-07-16" not in ts_raw:
                log.debug("Angel candle for %s has wrong date: %s — using seed table instead", symbol, ts_raw[:19])
                return None
            return float(row[1])  # open price
        except (TypeError, ValueError, IndexError):
            return None
    return None


def get_reference_price(symbol: str, *, allow_network: bool = True) -> float:
    """Return the 9:30 AM IST reference price on July 17, 2026.

    Priority:
      1. In-memory cache.
      2. Seed price table (fast — preferred for Book P&L rebuilds).
      3. Angel One 5-minute candle API when allow_network=True.
      4. Return 0.0 (caller handles gracefully).
    """
    upper = symbol.upper().strip()
    cached = _REFERENCE_CACHE.get(upper)
    if cached is not None:
        return cached

    # Seed first so Book P&L rebuilds never block on Angel candles
    seed = _SEED_REFERENCE_PRICES.get(upper)
    if seed is not None:
        _REFERENCE_CACHE[upper] = seed
        return seed

    if allow_network:
        angel_price = _fetch_930am_candle_from_angel(upper)
        if angel_price is not None and angel_price > 0:
            _REFERENCE_CACHE[upper] = angel_price
            return angel_price

    return 0.0


def get_mock_eod_price(symbol: str) -> float:
    """Return mock EOD price for July 19 demo seeds. Unknown → 0.0 (do not use for live desk)."""
    global _MOCK_EOD_PRICES
    if _MOCK_EOD_PRICES is None:
        _MOCK_EOD_PRICES = _build_mock_eod_prices()
    return _MOCK_EOD_PRICES.get(symbol.upper().strip(), 0.0)


_CLOSE_MARK_CACHE: dict[str, tuple[float, float]] = {}
_CLOSE_MARK_TTL_SEC = 120.0


def _yahoo_last_print(symbol: str, *, timeout: float = 2.5) -> float | None:
    try:
        import urllib.request

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        meta = (data.get("chart") or {}).get("result", [{}])[0].get("meta") or {}
        for key in ("regularMarketPrice", "postMarketPrice", "chartPreviousClose", "previousClose"):
            raw = meta.get(key)
            if raw is not None:
                px = float(raw)
                if px > 0:
                    return px
    except Exception:
        return None
    return None


def _snapshot_ltp(symbol: str) -> float | None:
    from .market_snapshot_store import readable_market_snapshot_path

    snap_path = str(readable_market_snapshot_path())
    try:
        with open(snap_path, "r", encoding="utf-8-sig") as fh:
            snap = json.load(fh)
        quotes = snap.get("stockQuotes") or {}
        q = quotes.get(symbol)
        if isinstance(q, dict):
            raw = q.get("ltpRaw") or q.get("ltp") or q.get("lastPrice") or q.get("close")
            if raw is not None:
                px = float(raw)
                if px > 0:
                    return px
    except Exception:
        pass
    return None


def get_close_mark_price(symbol: str) -> float | None:
    """Real last/close mark for Book P&L — never invents; never returns 0 as a fake mark.

    Prefer Yahoo last print (cached) over snapshot LTP. Fast timeout so Book UI does not hang.
    """
    import time as _time

    sym = (symbol or "").upper().strip()
    if not sym:
        return None

    now = _time.time()
    cached = _CLOSE_MARK_CACHE.get(sym)
    if cached and (now - cached[1]) < _CLOSE_MARK_TTL_SEC:
        return cached[0]

    # Use the same shared Angel/Yahoo mark path as Intraday and Swing first, so
    # all panels agree on a symbol within the shared quote-cache window.
    shared_px = None
    try:
        from .trade_outcome import fetch_live_marks_for_symbols
        shared_px = fetch_live_marks_for_symbols([sym]).get(sym)
    except Exception:
        shared_px = None
    if shared_px is not None and shared_px > 0:
        _CLOSE_MARK_CACHE[sym] = (float(shared_px), now)
        return float(shared_px)

    yahoo_px = _yahoo_last_print(sym)
    if yahoo_px is not None:
        _CLOSE_MARK_CACHE[sym] = (yahoo_px, now)
        return yahoo_px

    snap_px = _snapshot_ltp(sym)
    if snap_px is not None:
        _CLOSE_MARK_CACHE[sym] = (snap_px, now)
        return snap_px
    return None


def prefetch_close_marks(symbols: list[str]) -> dict[str, float]:
    """Parallel Yahoo/snapshot marks for a book rebuild (keeps EOD UI responsive)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: dict[str, float] = {}
    uniq = list(dict.fromkeys((s or "").upper().strip() for s in symbols if s))
    if not uniq:
        return out

    def _one(sym: str) -> tuple[str, float | None]:
        return sym, get_close_mark_price(sym)

    workers = min(8, max(1, len(uniq)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, s) for s in uniq]
        for fut in as_completed(futs):
            try:
                sym, px = fut.result()
                if px is not None:
                    out[sym] = px
            except Exception:
                continue
    return out


def get_reference_and_eod(symbol: str) -> dict[str, Any]:
    ref = get_reference_price(symbol)
    eod = get_close_mark_price(symbol)
    if eod is None:
        eod = get_mock_eod_price(symbol) or None
    return {
        "symbol": symbol,
        "refPrice930": ref,
        "eodPrice": eod,
        "changePct": round((eod - ref) / ref * 100, 2) if ref and eod else None,
        "changeAbs": round(eod - ref, 2) if ref and eod else None,
    }


# ---------------------------------------------------------------------------
#  Hedge Fund Analysis — generates per-stock diagnosis text.
#  When LLM_PROVIDER is configured, calls Gemini/OpenAI for real analysis.
#  Otherwise returns rich per-stock template text based on direction & P&L.
# ---------------------------------------------------------------------------

_SECTOR_BY_SYMBOL: dict[str, str] = {
    "RELIANCE": "Energy & Telecom", "TCS": "IT Services", "HDFCBANK": "Banking",
    "INFY": "IT Services", "BHARTIARTL": "Telecom", "LT": "Infrastructure",
    "SUNPHARMA": "Pharma", "TITAN": "Consumer Discretionary", "MARUTI": "Auto",
    "HINDUNILVR": "FMCG", "ITC": "FMCG & Hospitality", "WIPRO": "IT Services",
    "HCLTECH": "IT Services", "NTPC": "Power", "POWERGRID": "Power",
    "ONGC": "Oil & Gas", "COALINDIA": "Mining", "JSWSTEEL": "Metals & Mining",
    "TATASTEEL": "Metals & Mining", "INDUSINDBK": "Banking",
    "KALAMANDIR": "Textiles", "RAMASTEEL": "Steel", "GTLINFRA": "Infrastructure",
    "VIKASLIFE": "Pharma", "JAINREC": "Recycling", "GREENPOWER": "Renewable Energy",
    "BSE": "Financial Services", "BAJAJCON": "Consumer Goods", "VIKASECO": "Eco Solutions",
    "NCC": "Infrastructure", "RELAXO": "Footwear", "CUPID": "Healthcare",
    "NAVKARURB": "Infrastructure", "BAJFINANCE": "NBFC", "ADANIENT": "Conglomerate",
    "ZEEL": "Media & Entertainment", "BPCL": "Oil & Gas", "SBIN": "Banking",
    "M&M": "Auto", "PIRAMALFIN": "Financial Services",
}

_HEDGE_FUND_ANALYSIS_PROMPT = """You are an elite hedge fund analyst. Given one asset's trade setup and outcome, provide a concise post-mortem (3-4 sentences). Include: why it moved, what worked/didn't, volume/volatility context, and the key lesson. Be specific — reference sector trends, price action, and technical levels. This goes into a daily fund performance journal."""


def generate_swing_analysis(symbol: str, direction: str, entry: float, current: float,
                             pnl: float, pnl_pct: float, status: str) -> str | None:
    """Deterministic swing note only — never call LLM (Book P&L must stay fast/cached)."""
    if status == "NOT_TRIGGERED":
        return (
            f"{symbol}: entry signal not triggered (price never crossed "
            f"{entry:.2f}). Skipped from swing Book P&L for the session."
        )
    sector = _SECTOR_BY_SYMBOL.get(symbol.upper(), "Diversified")
    direction_label = "bullish" if direction == "LONG" else "bearish"

    change_dir = "gained" if pnl >= 0 else "declined"
    perf = "outperformed" if pnl_pct >= 0 else "underperformed"
    volatility = "elevated" if abs(pnl_pct) > 3 else "moderate" if abs(pnl_pct) > 1.5 else "low"

    analyses = {
        "RELIANCE": f"Reliance moved {change_dir} {abs(pnl_pct):.1f}% in a {volatility} volatility session, tracking crude and retail trends. The {direction_label} thesis played out within expected risk parameters. Key monitor: OMC margin trajectory and telecom ARPU trends in the coming week.",
        "TCS": f"TCS {perf} the IT sector this week with a {abs(pnl_pct):.1f}% {change_dir}, reflecting deal pipeline sentiment. Q1 earnings season will be the next catalyst. The {direction_label} position sizing was appropriate for the volatility regime.",
        "HDFCBANK": f"HDFCBANK's {abs(pnl_pct):.1f}% {change_dir} was driven by {volatility} banking sector flows. The {direction_label} thesis rests on margin stability and loan growth reacceleration. Position held within day bucket {abs(pnl_pct):.1f}% away from avg entry.",
        "INFY": f"Infosys {change_dir} {abs(pnl_pct):.1f}% on {volatility} volume as IT spending outlook remains mixed. The {direction_label} position is tracking the sector rotation narrative. Key risk: discretionary spending slowdown in US/European markets.",
        "BHARTIARTL": f"Bharti {perf} with a {abs(pnl_pct):.1f}% {change_dir}, supported by tariff hike tailwinds and ARPU improvement. The {direction_label} stance aligns with sector consolidation trends. Next catalyst: spectrum auction outcomes and Jio response.",
        "LT": f"L&T {perf} the capital goods space with a {abs(pnl_pct):.1f}% {change_dir}. The {direction_label} thesis benefits from order book momentum and government capex push. Execution and working capital management are key watchpoints.",
        "SUNPHARMA": f"Sun Pharma's {direction_label} position {perf} with a {abs(pnl_pct):.1f}% {change_dir} as pharma sector saw {volatility} rotational flows. US generic pricing environment and specialty pipeline progress remain key catalysts to track.",
        "TITAN": f"Titan {change_dir} {abs(pnl_pct):.1f}% in {volatility} trading as discretionary consumption signals remain mixed. The {direction_label} position is calibrated for the wedding season demand uptick. Gold price trajectory will influence near-term performance.",
        "MARUTI": f"Maruti's {abs(pnl_pct):.1f}% {change_dir} reflects {volatility} auto sector sentiment and demand recovery expectations in rural markets. The {direction_label} position captures market share gains from new model launches. Margin levers include commodity cost moderation.",
        "HINDUNILVR": f"HUL {change_dir} {abs(pnl_pct):.1f}% in a {volatility} session, with FMCG sector facing urban demand headwinds. The {direction_label} position accounts for valuation re-rating risks. Margin recovery timeline and input cost trends are critical variables.",
        "ITC": f"ITC {perf} with a {abs(pnl_pct):.1f}% {change_dir}, supported by cigarette volume resilience and FMCG segment turnaround. The {direction_label} thesis captures the conglomerate discount narrowing. Hotel business monetization is a potential upside trigger.",
        "WIPRO": f"Wipro {change_dir} {abs(pnl_pct):.1f}% as IT services sector continues to navigate demand uncertainty. The {direction_label} position reflects cautious near-term outlook. Deal wins in consulting & digital could shift momentum positively.",
        "NTPC": f"NTPC {perf} the power sector with {volatility} volatility and a {abs(pnl_pct):.1f}% {change_dir}. The {direction_label} thesis is anchored in capacity addition plans and renewable energy transition. Regulatory tariff policy remains a monitoring point.",
        "ONGC": f"ONGC's {direction_label} position {change_dir} {abs(pnl_pct):.1f}% as crude prices exhibited {volatility} swings. The position sizing factors both subsidy burden risk and production growth visibility. Key monitor: government subsidy sharing mechanism.",
        "JSWSTEEL": f"JSW Steel {change_dir} {abs(pnl_pct):.1f}% with {volatility} metal sector volatility. The {direction_label} position reflects steel spread dynamics and China demand uncertainty. Capacity expansion execution and global trade flows deserve close monitoring.",
        "ZEEL": f"ZEEL's {direction_label} position {change_dir} {abs(pnl_pct):.1f}% in a {volatility} media sector session. The thesis factors regulatory clarity on broadcast reforms and ad revenue recovery timeline. Content pipeline strength is a near-term catalyst.",
        "SBIN": f"SBI {perf} with a {abs(pnl_pct):.1f}% {change_dir} on {volatility} banking sector momentum. The {direction_label} position benefits from credit growth acceleration and NIM stability. Asset quality trends in agricultural and MSME portfolios are key to track.",
        "BPCL": f"BPCL {change_dir} {abs(pnl_pct):.1f}% as OMCs faced {volatility} crude price swings and marketing margin uncertainty. The {direction_label} position incorporates valuation support from potential divestment. GRM recovery timeline is a crucial catalyst.",
        "M&M": f"M&M {perf} with a {abs(pnl_pct):.1f}% {change_dir} in {volatility} auto sector trading. The {direction_label} thesis enjoys SUV demand tailwinds and EV business optionality. Tractor segment performance and rural demand signals are complementary variables.",
        "PIRAMALFIN": f"Piramal Finance {change_dir} {abs(pnl_pct):.1f}% amid {volatility} NBFC sector dynamics. The {direction_label} position accounts for wholesale book resolution progress and retail franchise buildout. Funding cost trajectory and credit costs are primary risks.",
    }

    template = analyses.get(symbol.upper())
    if template:
        return template

    return (
        f"{symbol} ({sector}) {perf} in this {volatility}-volatility session with a "
        f"{abs(pnl_pct):.1f}% {change_dir} against its 9:30 AM reference. The {direction_label} "
        f"position remains active within the planned risk framework. Status={status}."
    )
