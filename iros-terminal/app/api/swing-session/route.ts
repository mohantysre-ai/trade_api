import { NextResponse } from "next/server";
import { cachedBackendJson, liveCacheHeaders } from "@/lib/server-live-cache";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

/** GET /api/swing-session — locked Asset Matrix swing book (+ live=1 price MTM). */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const live = searchParams.get("live") === "1" || searchParams.get("live") === "true";
    const qs = live ? "?live=1" : "";
    const key = live ? "swing-session-live" : "swing-session";
    const { data, cacheStatus } = await cachedBackendJson(key, `${BACKEND_URL}/api/swing-session${qs}`, live ? 4_000 : 20_000);
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
      { status: 503, headers: liveCacheHeaders("ERROR") },
    );
  }
}
