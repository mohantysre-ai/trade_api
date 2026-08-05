import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

/** GET /api/swing-session — locked Asset Matrix swing book (+ live=1 price MTM). */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const live = searchParams.get("live") === "1" || searchParams.get("live") === "true";
    const qs = live ? "?live=1" : "";
    const res = await fetch(`${BACKEND_URL}/api/swing-session${qs}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { success: false, error: detail || `Backend HTTP ${res.status}`, locked: false, long: [], short: [] },
        { status: 502 },
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
      { status: 503 },
    );
  }
}
