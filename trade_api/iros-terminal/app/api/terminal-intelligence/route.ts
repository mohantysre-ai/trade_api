import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL =
  process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";

export async function GET(request: Request) {
  try {
    const backendUrl = new URL(`${BACKEND_URL}/api/terminal-intelligence`);
    const requestUrl = new URL(request.url);
    const ticker = requestUrl.searchParams.get("ticker");
    const pool = requestUrl.searchParams.get("pool");
    const prompt = requestUrl.searchParams.get("prompt");
    if (ticker) {
      backendUrl.searchParams.set("ticker", ticker);
    }
    if (pool) {
      backendUrl.searchParams.set("pool", pool);
    }
    if (prompt) {
      backendUrl.searchParams.set("prompt", prompt);
    }

    const res = await fetch(backendUrl.toString(), {
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
    const message =
      err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json(
      {
        success: false,
        error: `${message}. Start the feed: cd backend && python angel_one_feed.py --serve`,
      },
      { status: 503 }
    );
  }
}
