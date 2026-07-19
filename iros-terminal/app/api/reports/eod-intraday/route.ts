import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * GET /api/reports/eod-intraday?date=2026-07-19
 *
 * Returns post-close reconciliation of the day's intraday scanner picks:
 * T1/T2/SL outcome per pick, realized P&L, remaining capital, and LLM miss-diagnosis.
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date");
    const queryString = date ? `?date=${encodeURIComponent(date)}` : "";

    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

    const res = await fetch(`${backendUrl}/api/reports/eod-intraday${queryString}`, {
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
        error: err instanceof Error ? err.message : "Failed to fetch intraday EOD report",
        trades: [],
        summary: { note: "Backend unavailable" },
      },
      { status: 502 }
    );
  }
}