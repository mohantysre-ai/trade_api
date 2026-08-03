import { NextRequest, NextResponse } from "next/server";
import { backendBase } from "../../eod/_proxy";

export const runtime = "nodejs";

/**
 * GET /api/reports/eod-swing?date=&force=
 * Cached under data/eod/{date}/book_swing.json unless force=true.
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date");
    const force = searchParams.get("force");
    const params = new URLSearchParams();
    if (date) params.set("date", date);
    if (force) params.set("force", force);
    const qs = params.toString() ? `?${params.toString()}` : "";

    const res = await fetch(`${backendBase()}/api/reports/eod-swing${qs}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return NextResponse.json(
        { error: `Backend returned ${res.status}: ${text}` },
        { status: res.status }
      );
    }

    return NextResponse.json(await res.json());
  } catch (err) {
    return NextResponse.json(
      {
        error: err instanceof Error ? err.message : "Failed to fetch swing EOD report",
        picks: [],
      },
      { status: 502 }
    );
  }
}
