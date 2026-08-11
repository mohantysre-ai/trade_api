import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

/** GET /api/intraday-session — locked top-five-total basket + MTM (proxies FastAPI). */
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/intraday-session`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { success: false, error: detail || `Backend HTTP ${res.status}`, locked: false, long: [], short: [] },
        { status: 502 }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    return NextResponse.json(
      {
        success: false,
        error: err instanceof Error ? err.message : "Backend unreachable",
        locked: false,
        long: [],
        short: [],
      },
      { status: 503 }
    );
  }
}
