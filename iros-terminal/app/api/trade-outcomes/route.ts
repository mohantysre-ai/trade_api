import { NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * GET /api/trade-outcomes
 *
 * Returns persisted scanner picks with their live target/SL hit status.
 * Picks are stored in trade_api_snapshot.json and refreshed on each call.
 */
export async function GET() {
  try {
    // Import backend service — in Next.js this runs on the server side
    // We proxy to the backend API that has access to market_feeds
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    
    const res = await fetch(`${backendUrl}/api/trade-outcomes`, {
      cache: "no-store",
      headers: {
        "Accept": "application/json",
      },
    });

    if (!res.ok) {
      // Fallback: return empty structure
      return NextResponse.json({
        long: [],
        short: [],
        updatedAt: new Date().toISOString(),
      });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    // Graceful fallback
    return NextResponse.json({
      long: [],
      short: [],
      updatedAt: new Date().toISOString(),
      error: err instanceof Error ? err.message : "Failed to fetch trade outcomes",
    });
  }
}