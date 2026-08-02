import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MARKET_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

/** POST /api/intraday-session/commit — lock 5+5 server-side (manual execution only). */
export async function POST(request: Request) {
  try {
    const url = new URL(request.url);
    let force = url.searchParams.get("force") === "true";
    try {
      const body = (await request.json()) as { force?: boolean };
      if (body?.force === true) force = true;
    } catch {
      /* no JSON body */
    }
    const res = await fetch(
      `${BACKEND_URL}/api/intraday-session/commit?force=${force ? "true" : "false"}`,
      {
        method: "POST",
        cache: "no-store",
        headers: { Accept: "application/json" },
      }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(
        {
          success: false,
          error: (data as { detail?: string; error?: string })?.detail
            || (data as { error?: string })?.error
            || `Backend HTTP ${res.status}`,
        },
        { status: res.status === 409 ? 409 : 502 }
      );
    }
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      {
        success: false,
        error: err instanceof Error ? err.message : "Backend unreachable",
      },
      { status: 503 }
    );
  }
}
