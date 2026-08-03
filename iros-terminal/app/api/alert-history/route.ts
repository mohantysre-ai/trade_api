import { NextResponse } from "next/server";
import { backendBase } from "../eod/_proxy";

export const runtime = "nodejs";

/**
 * GET /api/alert-history
 *
 * Returns fired alert history for today (optionally filtered by date).
 * Proxies to the FastAPI backend.
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const since = searchParams.get("since");
    const base = backendBase();

    const url = since
      ? `${base}/api/alert-history?since=${encodeURIComponent(since)}`
      : `${base}/api/alert-history`;

    const res = await fetch(url, {
      cache: "no-store",
      headers: {
        "Accept": "application/json",
      },
    });

    if (!res.ok) {
      return NextResponse.json({ alerts: [], total: 0, today: new Date().toISOString().slice(0, 10) });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({
      alerts: [],
      total: 0,
      today: new Date().toISOString().slice(0, 10),
      error: err instanceof Error ? err.message : "Failed to fetch alert history",
    });
  }
}
