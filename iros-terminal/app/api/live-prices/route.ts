import { NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * GET /api/live-prices
 *
 * Proxies FastAPI fixed-plan price evaluation.
 * Backend may use Angel One snapshot and (when market open) Yahoo Finance —
 * see response.ltpSourceMix / priceSourcesNote / dataStale. Do not assume
 * "no external API calls" or tick-live freshness.
 */
export async function GET() {
  try {
    const backendUrl =
      process.env.MARKET_API_URL ??
      process.env.NEXT_PUBLIC_BACKEND_URL ??
      "http://127.0.0.1:8000";

    const res = await fetch(`${backendUrl}/api/live-prices`, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    });

    if (!res.ok) {
      return NextResponse.json({
        long: [],
        short: [],
        updatedAt: new Date().toISOString(),
        source: "none",
        dataStale: true,
        marketOpen: false,
        sessionClosed: true,
        ltpSourceMix: { live: 0, snapshot: 0, cached: 0, none: 0 },
        priceSourcesNote: "Backend live-prices unavailable",
      });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({
      long: [],
      short: [],
      updatedAt: new Date().toISOString(),
      source: "none",
      dataStale: true,
      marketOpen: false,
      sessionClosed: true,
      error: err instanceof Error ? err.message : "Failed to fetch live prices",
      ltpSourceMix: { live: 0, snapshot: 0, cached: 0, none: 0 },
      priceSourcesNote: "Proxy error — no LTP sources available",
    });
  }
}
