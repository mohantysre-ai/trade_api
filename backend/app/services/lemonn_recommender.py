"""
Lemoon Intraday Recommendation Service
=======================================
Fetches 10 stock intraday recommendations from lemonn.co.in and normalises
them into a ScanResult-compatible shape for the INTRA DAY MATRIX frontend tab.

Each recommendation includes BUY price, SELL/target price, and stop loss,
along with the ticker symbol and company name.
"""

import http.client
import json
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional


LEMONN_HOST = "lemonn.co.in"
LEMONN_PATH = "/api/get-lemonn-recommendation"
LEMONN_TIMEOUT = 15
MAX_RETRIES = 2


@dataclass
class IntradayRecommendation:
    """Normalised recommendation row for the frontend INTRA DAY MATRIX tab."""
    symbol: str
    name: str
    direction: str               # "BUY" | "SELL"
    buy_price: float
    sell_price: float            # target
    stop_loss: float
    risk_per_share: float
    confidence: Optional[float] = None   # 0-100 or similar, if API provides it
    reasons: List[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _request_with_retry(retries: int = MAX_RETRIES) -> dict:
    """POST to lemonn.co.in and return parsed JSON with retry/backoff."""
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            conn = http.client.HTTPSConnection(LEMONN_HOST, timeout=LEMONN_TIMEOUT)
            conn.request("POST", LEMONN_PATH, "", {})
            res = conn.getresponse()
            raw = res.read()
            conn.close()
            if res.status != 200:
                raise RuntimeError(
                    f"Lemoon API HTTP {res.status}: {raw[:300].decode('utf-8', errors='replace')}"
                )
            return json.loads(raw)
        except (json.JSONDecodeError, Exception) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Lemoon API unreachable after {retries + 1} attempts: {last_err}")


def _parse_recommendation(item: Any) -> Optional[IntradayRecommendation]:
    """Parse a single recommendation object from the lemoon API response.

    The API response shape is unknown ahead of time, so this parser is
    deliberately flexible — it tries the most common field names used by
    Indian advisory APIs and falls back gracefully.
    """
    if not isinstance(item, dict):
        return None

    # --- Symbol -----------------------------------------------------------
    # Try top-level first, then symObj.symbol (lemoon nested structure)
    sym = item.get("symbol") or item.get("ticker") or item.get("stock") or item.get("Sym") or ""
    if not sym:
        symObj = item.get("symObj", {})
        if isinstance(symObj, dict):
            sym = symObj.get("symbol") or symObj.get("Sym") or ""
    if not sym:
        return None
    sym = str(sym).strip().upper()

    # --- Name -------------------------------------------------------------
    name_raw = (
        item.get("name")
        or item.get("company")
        or item.get("DispSym")
        or item.get("company_name")
    )
    if not name_raw:
        symObj = item.get("symObj", {})
        if isinstance(symObj, dict):
            name_raw = symObj.get("compName") or symObj.get("DispSym") or symObj.get("companyName")
    name = str(name_raw or sym)

    # --- Direction (BUY / SELL) -------------------------------------------
    direction_raw = str(
        item.get("direction")
        or item.get("action")
        or item.get("recommendation")
        or item.get("signal")
        or "BUY"
    ).upper()
    if "SELL" in direction_raw or "SHORT" in direction_raw:
        direction = "SELL"
    else:
        direction = "BUY"

    # --- Prices -----------------------------------------------------------
    def _float(*keys: str) -> Optional[float]:
        for k in keys:
            v = item.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    buy_price = _float("buy_price", "buy", "entry", "entry_price", "ltp", "Ltp", "buyPrice")
    sell_price = _float("sell_price", "sell", "target", "target_price", "sellPrice", "targetPrice")
    stop_loss = _float("stop_loss", "stop", "sl", "stoploss", "stopLoss")

    if buy_price is None or sell_price is None:
        return None  # can't construct a useful row without buy and target
    if buy_price <= 0:
        return None

    # Derive stop loss if not provided: use 3% below buy for BUY, 3% above for SELL
    if stop_loss is None:
        if direction == "BUY":
            stop_loss = round(buy_price * 0.97, 2)  # 3% stop
        else:
            stop_loss = round(buy_price * 1.03, 2)
    if stop_loss <= 0:
        return None

    risk = abs(buy_price - stop_loss)
    if risk <= 0:
        return None

    # --- Confidence (optional) --------------------------------------------
    confidence = _float("confidence", "score", "confidence_score", "rating")

    # --- Reasons (optional) -----------------------------------------------
    reasons_raw = item.get("reasons") or item.get("rationale") or item.get("analysis") or []
    if isinstance(reasons_raw, str):
        reasons = [reasons_raw]
    elif isinstance(reasons_raw, list):
        reasons = [str(r) for r in reasons_raw if r]
    else:
        reasons = []

    return IntradayRecommendation(
        symbol=sym,
        name=name,
        direction=direction,
        buy_price=round(buy_price, 2),
        sell_price=round(sell_price, 2),
        stop_loss=round(stop_loss, 2),
        risk_per_share=round(risk, 2),
        confidence=round(confidence, 2) if confidence is not None else None,
        reasons=reasons,
        raw=item,
    )


def fetch_intraday_recommendations(top_n: int = 10) -> List[IntradayRecommendation]:
    """Fetch the lemoon intraday recommendation list and return up to *top_n* rows."""
    payload = _request_with_retry()

    # The API may return {"data": [...], "status": "ok"} or just a raw list.
    # Be flexible about the top-level shape.
    items: List[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        # Try common top-level list keys first
        for candidate_key in ("data", "recommendations", "stocks", "result"):
            candidate = payload.get(candidate_key)
            if isinstance(candidate, list):
                items = candidate
                break
            # Also try: data.response.data.open (3-level nesting)
            if isinstance(candidate, dict):
                inner = candidate.get("response", {}).get("data", {})
                for sub_key in ("open", "closed", "data", "recommendations", "stocks", "result"):
                    sub = inner.get(sub_key)
                    if isinstance(sub, list):
                        items.extend(sub)
        if not items:
            # Maybe the whole dict is itself a single recommendation?
            items = [payload]

    results: List[IntradayRecommendation] = []
    for item in items:
        rec = _parse_recommendation(item)
        if rec:
            results.append(rec)

    # Cap at requested limit
    return results[:top_n]


def recommendations_to_dict(recs: List[IntradayRecommendation]) -> List[dict]:
    """Convert IntradayRecommendation objects to JSON-serialisable dicts."""
    return [
        {
            "symbol": r.symbol,
            "name": r.name,
            "direction": r.direction,
            "buyPrice": r.buy_price,
            "sellPrice": r.sell_price,
            "stopLoss": r.stop_loss,
            "riskPerShare": r.risk_per_share,
            "confidence": r.confidence,
            "reasons": r.reasons,
        }
        for r in recs
    ]


if __name__ == "__main__":
    print("Fetching intraday recommendations from lemonn.co.in ...")
    try:
        recs = fetch_intraday_recommendations(top_n=10)
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        raise SystemExit(1)

    if not recs:
        print("No recommendations returned by the API.")
        raise SystemExit(0)

    print(f"\n--- INTRA DAY MATRIX ({len(recs)} stocks) ---\n")
    for r in recs:
        print(f"  {r.symbol:12s} ({r.name})")
        print(f"     Direction: {r.direction}")
        print(f"     BUY  @ {r.buy_price:.2f}  |  SELL @ {r.sell_price:.2f}  |  SL @ {r.stop_loss:.2f}")
        print(f"     Risk/Share: {r.risk_per_share:.2f}  Confidence: {r.confidence}")
        if r.reasons:
            for reason in r.reasons:
                print(f"       - {reason}")
        print()