import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

/** POST /api/swing-session/lock — lock Asset Matrix BUY set (optional force rotate). */
export async function POST(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const force = searchParams.get("force") === "1" || searchParams.get("force") === "true";
    const res = await fetch(`${BACKEND_URL}/api/swing-session/lock?force=${force ? "true" : "false"}`, {
      method: "POST",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: body?.detail || body?.error || `Backend HTTP ${res.status}` },
        { status: res.status >= 400 ? res.status : 502 },
      );
    }
    return NextResponse.json(body);
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "Backend unreachable" },
      { status: 503 },
    );
  }
}
