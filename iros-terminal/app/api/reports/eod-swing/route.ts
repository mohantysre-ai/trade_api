import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * GET /api/reports/eod-swing?date=2026-07-19
 *
 * Returns day-bucketed (1/7/15/30) P&L report for the Asset Matrix
 * swing/long-term picks in the fixed trade plan.
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date");
    const queryString = date ? `?date=${encodeURIComponent(date)}` : "";

    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

    const res = await fetch(`${backendUrl}/api/reports/eod-swing${queryString}`, {
      cache: "no-store",
      headers: {
        "Accept": "application/json",
      },
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return NextResponse.json(
        { error: `Backend returned ${res.status}: ${text}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      {
        error: err instanceof Error ? err.message : "Failed to fetch swing EOD report",
        picks: [],
        summary: { note: "Backend unavailable" },
      },
      { status: 502 }
    );
  }
}