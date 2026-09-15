import { NextRequest, NextResponse } from "next/server";
import { backendBase } from "../../eod/_proxy";

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
    const res = await fetch(`${backendBase()}/api/reports/eod-index-options${qs}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(60_000),
    });
    const body = await res.json();
    return NextResponse.json(body, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to fetch Index Options EOD report" },
      { status: 502 },
    );
  }
}
