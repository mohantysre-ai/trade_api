import { NextResponse } from "next/server";
import { cachedBackendJson, liveCacheHeaders } from "@/lib/server-live-cache";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

export async function GET() {
  try {
    const { data, cacheStatus } = await cachedBackendJson(
      "index-options",
      `${BACKEND_URL}/api/index-options`,
      4_000,
    );
    return NextResponse.json(data, { headers: liveCacheHeaders(cacheStatus) });
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        executionPolicy: "MANUAL_ONLY",
        candidates: [],
        selected: [],
        error: error instanceof Error ? error.message : "Index-options backend unavailable",
      },
      { status: 503, headers: liveCacheHeaders("ERROR") },
    );
  }
}
