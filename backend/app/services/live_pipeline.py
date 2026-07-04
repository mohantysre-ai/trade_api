"""
Live pipeline: Dhan ScanX API -> feed_scanner filter
=====================================================
Wires your actual data source (ow-scanx-analytics.dhan.co) into the
LONG/SHORT filter from feed_scanner.py. Handles pagination (the API
returns `count` rows per page, capped around 500) and merges pages
before scanning.

NOTE: This will NOT run inside this sandbox — ow-scanx-analytics.dhan.co
isn't on the sandbox's allowed domain list (confirmed: 403 Forbidden,
"Host not in allowlist"). This is a sandbox restriction only. Run this
file in your own environment (same place angel_one_feed.py runs) and
it will work — it's a plain http.client POST like the one you shared.
"""

import http.client
import json
import time
from .feed_scanner import scan_feed

HOST = "ow-scanx-analytics.dhan.co"
PATH = "/customscan/fetchdt"

FIELDS = [
    "Isin", "DispSym", "Mcap", "Pe", "DivYeild", "Revenue",
    "Year1RevenueGrowth", "NetProfitMargin", "YoYLastQtrlyProfitGrowth",
    "EBIDTAMargin", "volume", "PricePerchng1year", "PricePerchng3year",
    "PricePerchng5year", "Ind_Pe", "Pb", "Eps",
    "DaySMA50CurrentCandle", "DaySMA200CurrentCandle", "DayRSI14CurrentCandle",
    "ROCE", "Ltp", "Roe", "RtAwayFrom5YearHigh", "RtAwayFrom1MonthHigh",
    "High5yr", "High3Yr", "High1Yr", "High1Wk", "Sym",
    "PricePerchng1mon", "PricePerchng1week", "PricePerchng3mon",
    "YearlyEarningPerShare", "OCFGrowthOnYr", "Year1CAGREPSGrowth",
    "NetChangeInCash", "FreeCashFlow", "PricePerchng2week",
    "DayBbUpper_Sub_BbLower", "DayATR14CurrentCandleMul_2",
    "Min5HighCurrentCandle", "Min15HighCurrentCandle",
    "Min5EMA50CurrentCandle", "Min15EMA50CurrentCandle",
    "Min15SMA100CurrentCandle", "Open", "BcClose", "Rmp", "PledgeBenefit",
    "DeliveryData.DailyTradedQty", "DeliveryData.DailyDeliveredQty",
    "DeliveryData.DailyDeliveredPer",
]


def fetch_page(pgno: int, count: int = 500, min_volume: int = 1_000_000, retries: int = 3):
    body = json.dumps({
        "data": {
            "sort": "Volume",
            "sorder": "desc",
            "count": count,
            "params": [
                {"field": "OgInst", "op": "", "val": "ES"},
                {"field": "Volume", "op": "gte", "val": str(min_volume)},
                {"field": "Seg", "op": "", "val": "E"},
                {"field": "Exch", "op": "", "val": "NSE"},
            ],
            "fields": FIELDS,
            "pgno": pgno,
        }
    })
    headers = {"Content-Type": "application/json"}

    last_err = None
    for attempt in range(retries):
        try:
            conn = http.client.HTTPSConnection(HOST, timeout=10)
            conn.request("POST", PATH, body, headers)
            res = conn.getresponse()
            raw = res.read()
            conn.close()
            if res.status != 200:
                raise RuntimeError(f"HTTP {res.status}: {raw[:200]}")
            return json.loads(raw)
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))  # simple backoff
    raise RuntimeError(f"Failed to fetch page {pgno} after {retries} attempts: {last_err}")


def fetch_all_pages(min_volume: int = 1_000_000, page_size: int = 500, max_pages: int = 10):
    """Pull every page until the API returns fewer rows than page_size
    (i.e. the last page), or max_pages is hit as a safety cap."""
    all_rows = []
    for pgno in range(1, max_pages + 1):
        resp = fetch_page(pgno=pgno, count=page_size, min_volume=min_volume)
        rows = resp.get("data", [])
        if not rows:
            break
        all_rows.extend(rows)
        print(f"  fetched page {pgno}: {len(rows)} rows (running total {len(all_rows)})")
        if len(rows) < page_size:
            break  # last page
    return all_rows


if __name__ == "__main__":
    print("Fetching live scan data from Dhan ScanX...")
    try:
        rows = fetch_all_pages(min_volume=1_000_000)
    except RuntimeError as e:
        print(f"FAILED: {e}")
        print("(Expected in this sandbox — ow-scanx-analytics.dhan.co isn't allowlisted here.")
        print(" Run this script in your own environment where angel_one_feed.py runs.)")
        raise SystemExit(1)

    payload = {"data": rows}
    print(f"\nTotal stocks pulled: {len(rows)}\n")

    for direction in ("LONG", "SHORT"):
        print(f"=== {direction} candidates ===")
        hits = scan_feed(payload, direction=direction, top_n=15)
        if not hits:
            print("  No candidates passed the filter.\n")
            continue
        for r in hits:
            print(f"  {r.symbol:12s} ({r.name})")
            print(f"     Entry {r.entry}  Stop {r.stop_loss}  Target {r.target}  Risk/share {r.risk_per_share}  Score {r.score}")
            for reason in r.reasons:
                print(f"       - {reason}")
        print()
