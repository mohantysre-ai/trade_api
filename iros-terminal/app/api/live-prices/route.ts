import { NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * GET /api/live-prices
 *
 * Returns live prices + evaluated outcomes for today's fixed-plan symbols only.
 * Proxies to the FastAPI backend, which reads from last_market_snapshot.json
 * (no external API calls). Designed for monitor-mode polling.
 */
export async function GET() {
  try {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

    const res = await fetch(`${backendUrl}/api/live-prices`, {
      cache: "no-store",
      headers: {
        "Accept": "application/json",
      },
    });

    if (!res.ok) {
      return NextResponse.json({
        long: [],
        short: [],
        updatedAt: new Date().toISOString(),
        source: "none",
      });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({
      long: [],
      short: [],
      updatedAt: new Date().toISOString(),
      source: "none",
      error: err instanceof Error ? err.message : "Failed to fetch live prices",
    });
  }
}
