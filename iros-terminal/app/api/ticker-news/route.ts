import { NextResponse } from "next/server";

export const runtime = "nodejs";

/** Prefer server-side MARKET_API_URL (Docker: http://market-api:8000). Empty NEXT_PUBLIC_ must not win. */
const MAIN_API_URL =
  process.env["MARKET_API_URL"] ||
  process.env["NEXT_PUBLIC_MARKET_API_URL"] ||
  "http://127.0.0.1:8000";

const TICKER_NEWS_MAX_ARTICLES = 15;

function clampMaxArticles(raw: string | null): string {
  const parsed = Number.parseInt(raw || "8", 10);
  if (!Number.isFinite(parsed)) return "8";
  return String(Math.max(1, Math.min(parsed, TICKER_NEWS_MAX_ARTICLES)));
}

export async function GET(request: Request) {
  try {
    const requestUrl = new URL(request.url);
    const ticker = requestUrl.searchParams.get("ticker");
    const company = requestUrl.searchParams.get("company");

    if (!ticker) {
      return NextResponse.json(
        { success: false, error: "Missing required parameter: ticker" },
        { status: 400 }
      );
    }

    const params = new URLSearchParams();
    params.set("ticker", ticker);
    if (company) params.set("company", company);
    params.set("max_articles", clampMaxArticles(requestUrl.searchParams.get("max_articles")));
    if (requestUrl.searchParams.get("include_raw")) {
      params.set("include_raw", requestUrl.searchParams.get("include_raw")!);
    }
    if (requestUrl.searchParams.get("force_refresh")) {
      params.set("force_refresh", requestUrl.searchParams.get("force_refresh")!);
    }

    const backendUrl = new URL("/api/ticker-news", MAIN_API_URL);
    backendUrl.search = params.toString();

    const res = await fetch(backendUrl.toString(), {
      cache: "no-store",
      signal: AbortSignal.timeout(90_000),
    });

    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      return NextResponse.json(
        { success: false, error: detail || `ticker-news HTTP ${res.status}` },
        { status: 502 }
      );
    }

    const data = await res.json();
    const report = data.report || data;
    return NextResponse.json({
      success: true,
      payload: {
        ...report,
        cached: report.cached ?? false,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const timedOut = /timeout|aborted|AbortError/i.test(message);
    return NextResponse.json(
      {
        success: false,
        error: timedOut
          ? "Ticker news timed out — retry shortly"
          : `market-api unreachable at ${MAIN_API_URL}: ${message}`,
      },
      { status: timedOut ? 504 : 503 }
    );
  }
}
