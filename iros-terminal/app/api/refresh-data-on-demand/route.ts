import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL = process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const requestUrl = new URL(request.url);
    const pool = requestUrl.searchParams.get("pool") || body?.pool;
    const prompt = requestUrl.searchParams.get("prompt") || body?.prompt;
    const backendUrl = new URL("/api/refresh-data-on-demand", BACKEND_URL);

    const poolValue = typeof pool === "string" ? pool : undefined;
    const promptValue = typeof prompt === "string" ? prompt : undefined;

    if (poolValue) backendUrl.searchParams.set("pool", poolValue);
    if (promptValue) backendUrl.searchParams.set("prompt", promptValue);

    const res = await fetch(backendUrl.toString(), {
      method: "POST",
      cache: "no-store",
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { success: false, error: detail || `Backend HTTP ${res.status}` },
        { status: 502 }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json(
      {
        success: false,
        error: `${message}. Start the feed: cd backend && python angel_one_feed.py --serve`,
      },
      { status: 503 }
    );
  }
}
