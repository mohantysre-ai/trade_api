import { NextResponse } from "next/server";
import { cachedBackendJson, liveCacheHeaders } from "@/lib/server-live-cache";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

/** GET /api/intraday-session — locked top-five-total basket + MTM (proxies FastAPI). */
export async function GET() {
  try {
    const { data, cacheStatus } = await cachedBackendJson("intraday-session", `${BACKEND_URL}/api/intraday-session`, 4_000);
    return NextResponse.json(data, { headers: liveCacheHeaders(cacheStatus) });
  } catch (err) {
    return NextResponse.json(
      {
        success: false,
        error: err instanceof Error ? err.message : "Backend unreachable",
        locked: false,
        long: [],
        short: [],
      },
      { status: 503, headers: liveCacheHeaders("ERROR") }
    );
  }
}
