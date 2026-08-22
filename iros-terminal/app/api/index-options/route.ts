import { NextResponse } from "next/server";
import { cachedBackendJson, liveCacheHeaders } from "@/lib/server-live-cache";

export const runtime = "nodejs";
export const maxDuration = 90;

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

export async function GET(request: Request) {
  const sessionDate = new URL(request.url).searchParams.get("sessionDate");
  const qs = sessionDate ? `?sessionDate=${encodeURIComponent(sessionDate)}` : "";
  const cacheKey = sessionDate ? `index-options-${sessionDate}` : "index-options";
  const timeoutMs = 90_000;
  const staleMs = sessionDate ? 600_000 : 120_000;
  try {
    const { data, cacheStatus } = await cachedBackendJson(
      cacheKey,
      `${BACKEND_URL}/api/index-options${qs}`,
      sessionDate ? 60_000 : 4_000,
      staleMs,
      timeoutMs,
    );
    return NextResponse.json(data, { headers: liveCacheHeaders(cacheStatus) });
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        executionPolicy: "MANUAL_ONLY",
        candidates: [],
        selected: [],
        buySideContracts: [],
        implemented: [],
        error: error instanceof Error ? error.message : "Index-options backend unavailable",
      },
      { status: 503, headers: liveCacheHeaders("ERROR") },
    );
  }
}
