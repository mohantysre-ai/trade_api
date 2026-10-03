import { NextRequest, NextResponse } from "next/server";
import { backendBase } from "../../eod/_proxy";
import { cachedBackendJson, liveCacheHeaders } from "../../../../lib/server-live-cache";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function GET(request: NextRequest) {
  try {
    const searchParams = new URL(request.url).searchParams;
    const params = new URLSearchParams();
    const date = searchParams.get("date");
    const force = searchParams.get("force");
    if (date) params.set("date", date);
    if (force) params.set("force", force);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const url = `${backendBase()}/api/reports/eod-index-options${qs}`;

    if (!force) {
      const { data, cacheStatus } = await cachedBackendJson(
        `eod-index-options-${date || "latest"}`,
        url,
        2_000,
        60_000,
        60_000,
      );
      return NextResponse.json(data, { headers: liveCacheHeaders(cacheStatus) });
    }

    const res = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(60_000),
    });
    const body = await res.json();
    return NextResponse.json(body, { status: res.status, headers: liveCacheHeaders("MISS") });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to fetch Index Options EOD report" },
      { status: 502 },
    );
  }
}
