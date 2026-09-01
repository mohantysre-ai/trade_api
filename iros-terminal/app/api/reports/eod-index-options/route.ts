import { NextRequest, NextResponse } from "next/server";
import { backendBase } from "../../eod/_proxy";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  try {
    const date = new URL(request.url).searchParams.get("date");
    const qs = date ? `?date=${encodeURIComponent(date)}` : "";
    const res = await fetch(`${backendBase()}/api/reports/eod-index-options${qs}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
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
