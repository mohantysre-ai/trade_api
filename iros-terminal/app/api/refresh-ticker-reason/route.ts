import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL =
  process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  try {
    const requestUrl = new URL(request.url);
    const backendUrl = new URL("/api/refresh-ticker-reason", BACKEND_URL);

    const ticker = requestUrl.searchParams.get("ticker");
    const pool = requestUrl.searchParams.get("pool");
    const prompt = requestUrl.searchParams.get("prompt");

    if (!ticker) {
      return NextResponse.json(
        { success: false, error: "Missing ticker query parameter." },
        { status: 400 }
      );
    }

    backendUrl.searchParams.set("ticker", ticker);
    if (pool) backendUrl.searchParams.set("pool", pool);
    if (prompt) backendUrl.searchParams.set("prompt", prompt);

    let body: unknown = undefined;
    try {
      body = await request.json();
    } catch {
      body = undefined;
    }

    const res = await fetch(backendUrl.toString(), {
      method: "POST",
      cache: "no-store",
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });

    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: {
        "content-type": res.headers.get("content-type") || "application/json",
      },
    });
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
