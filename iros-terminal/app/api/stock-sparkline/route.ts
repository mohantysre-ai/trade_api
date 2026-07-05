import { NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * GET /api/stock-sparkline?ticker=INFY&flag=1M
 *
 * Fetches chart data from NSE India for a given stock ticker.
 * flag: 1D (intraday), 1M (1 month), 1Y (1 year). Defaults to 1M.
 * Returns { sparkline: number[], ticker: string, flag: string, graphData: unknown[] }.
 */

/* ── NSE session helper ─────────────────────────────────────────────────── */
let nseCookies = "";
let nseCookieExpiry = 0;

async function getNseCookies(): Promise<string> {
  if (nseCookies && Date.now() < nseCookieExpiry) return nseCookies;

  const res = await fetch("https://www.nseindia.com/", {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.5",
    },
    redirect: "follow",
    cache: "no-store",
  });

  const setCookies = res.headers.getSetCookie?.() ?? [];
  nseCookies = setCookies.map((c) => c.split(";")[0]).join("; ");
  nseCookieExpiry = Date.now() + 5 * 60 * 1000; // refresh every 5 min
  return nseCookies;
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const ticker = url.searchParams.get("ticker");
    const flag = url.searchParams.get("flag") || "1M";

    if (!ticker) {
      return NextResponse.json({ error: "ticker param required", sparkline: [] }, { status: 400 });
    }

    const identifier = `${ticker.toUpperCase().trim()}EQN`;
    const cookies = await getNseCookies();

    const nseUrl = `https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi?functionName=getSymbolgraphData&&identifier=${encodeURIComponent(identifier)}&flag=${encodeURIComponent(flag)}`;

    const res = await fetch(nseUrl, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Accept: "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.5",
        Referer: "https://www.nseindia.com/",
        Cookie: cookies,
      },
      cache: "no-store",
    });

    if (!res.ok) {
      return NextResponse.json({ error: `NSE HTTP ${res.status}`, sparkline: [] }, { status: 200 });
    }

    const raw = await res.json();

    /* NSE response can come in different shapes depending on flag:
     * - data.grapthData: [{value, timestamp}, ...]  (typical for 1M/1Y)
     * - data: [{...price points}]                   (1D intraday)
     * We normalise to a flat number[] of close/last prices. */
    const graphData: Array<Record<string, unknown>> =
      raw?.data?.grapthData ?? raw?.data?.graphData ?? raw?.data ?? raw?.grapthData ?? raw?.graphData ?? [];

    const sparkline: number[] = [];
    for (const point of graphData) {
      if (Array.isArray(point) && point.length >= 2 && typeof point[1] === 'number') {
        sparkline.push(point[1]);
      } else if (point && typeof point === "object") {
        const val = (point as Record<string, unknown>).value ?? (point as Record<string, unknown>).close ?? (point as Record<string, unknown>).lastPrice ?? (point as Record<string, unknown>).ltp ?? (point as Record<string, unknown>).price;
        if (typeof val === "number") {
          sparkline.push(val);
        } else if (typeof val === "string") {
          const parsed = parseFloat(val.replace(/,/g, ""));
          if (!isNaN(parsed)) sparkline.push(parsed);
        }
      } else if (typeof point === "number") {
        sparkline.push(point);
      }
    }

    if (sparkline.length < 2) {
      return NextResponse.json({ error: "No chart data available", sparkline: [], graphData }, { status: 200 });
    }

    return NextResponse.json({ sparkline, ticker: identifier.replace('EQN', ''), flag, graphData });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message, sparkline: [] }, { status: 200 });
  }
}
