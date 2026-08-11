import { NextResponse } from "next/server";
import { cachedBackendJson, liveCacheHeaders } from "@/lib/server-live-cache";

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

    const { data, cacheStatus } = await cachedBackendJson("live-prices", `${backendUrl}/api/live-prices`, 4_000);
    return NextResponse.json(data, { headers: liveCacheHeaders(cacheStatus) });
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
    }, { status: 503, headers: liveCacheHeaders("ERROR") });
  }
}
