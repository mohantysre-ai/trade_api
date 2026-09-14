import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

/** GET /api/intraday/market-state - operational WS/feed diagnostic. */
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/intraday/market-state`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(
        {
          success: false,
          error:
            (data as { detail?: string; error?: string })?.detail ||
            (data as { error?: string })?.error ||
            `Backend HTTP ${res.status}`,
          block: "",
        },
        { status: 502 },
      );
    }
    return NextResponse.json({ success: true, ...data });
  } catch (err) {
    return NextResponse.json(
      {
        success: false,
        error: err instanceof Error ? err.message : "Backend unreachable",
        block: "",
      },
      { status: 503 },
    );
  }
}
