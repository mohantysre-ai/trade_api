import { NextResponse } from "next/server";

export const runtime = "nodejs";

// ai_news_server.py is a standalone FastAPI process (default port 8001,
// see AI_NEWS_PORT in that file) -- separate from the main market API on
// port 8000 that NEXT_PUBLIC_MARKET_API_URL points to. Point this at
// wherever you're running `python ai_news_server.py`.
const NEWS_API_URL = process.env.NEXT_PUBLIC_NEWS_API_URL ?? "http://127.0.0.1:8001";

function offlineFallback() {
  return {
    stories: [
      {
        id: "offline-1",
        time: "now",
        source: "IROS",
        sentiment: "neutral",
        impact: "low",
        score: 0,
        headline: "News backend is not reachable",
        snippet:
          "Start ai_news_server.py (python backend/app/services/ai_news_server.py) so NewsWire can pull live Zerodha Pulse headlines. Showing no live stories until it's reachable.",
        url: "",
        tickers: [],
      },
    ],
    count: 1,
    error: true,
    offline: true,
  };
}

export async function GET(request: Request) {
  try {
    const requestUrl = new URL(request.url);
    const limit = requestUrl.searchParams.get("limit") ?? "30";

    try {
      const backendUrl = new URL("/api/pulse-feed", NEWS_API_URL);
      backendUrl.searchParams.set("limit", limit);

      const res = await fetch(backendUrl.toString(), {
        cache: "no-store",
        signal: AbortSignal.timeout(20_000),
      });

      if (res.ok) {
        const data = await res.json();
        return NextResponse.json({ success: true, ...data });
      }
    } catch {
      // Backend unreachable -- fall through to offline fallback below.
    }

    return NextResponse.json({ success: true, ...offlineFallback() });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
