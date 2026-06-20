import { NextResponse } from "next/server";

export const runtime = "nodejs";
const MAIN_API_URL = process.env.NEXT_PUBLIC_MARKET_API_URL ?? "http://127.0.0.1:8000";

function generateMockReport(ticker: string, companyName: string) {
  const company = companyName || ticker;
  return {
    ticker: ticker.toUpperCase(),
    company_name: company,
    articles_scraped: 0,
    articles_after_dedup: 0,
    generated_at: new Date().toISOString(),
    cached: false,
    insider_activity: "Backend not running — start the backend server to get AI news summaries.",
    institutional_activity: "Backend not running.",
    order_book_block_deals: "Backend not running.",
    future_expansion_capex: "Backend not running.",
    auditor_changes: "Backend not running.",
    dividend_news: "Backend not running.",
    new_orders_contracts: "Backend not running.",
    earnings_results: "Backend not running.",
    management_changes: "Backend not running.",
    regulatory_filings: "Backend not running.",
    sentiment_overall: "Neutral",
    risk_flags: "Scraper backend offline.",
    summary_headline: `${company}: AI news backend is not running.`,
    generated: true,
    raw_articles: [] as Array<{ title: string; source: string; url: string; summary: string; published_at: string; relevance: string }>,
  };
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
    if (requestUrl.searchParams.get("max_articles")) params.set("max_articles", requestUrl.searchParams.get("max_articles")!);
    if (requestUrl.searchParams.get("include_raw")) params.set("include_raw", requestUrl.searchParams.get("include_raw")!);
    if (requestUrl.searchParams.get("force_refresh")) params.set("force_refresh", requestUrl.searchParams.get("force_refresh")!);

    try {
      const backendUrl = new URL("/api/ticker-news", MAIN_API_URL);
      backendUrl.search = params.toString();

      const res = await fetch(backendUrl.toString(), {
        cache: "no-store",
        signal: AbortSignal.timeout(90_000),
      });

      if (res.ok) {
        const data = await res.json();
        const report = data.report || data;
        return NextResponse.json({
          success: true,
          payload: {
            ...report,
            cached: report.cached ?? false,
          },
        });
      }
    } catch {
      // Backend unavailable — fall through to mock
    }

    const mockReport = generateMockReport(ticker, company || "");
    return NextResponse.json({ success: true, payload: mockReport });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json(
      {
        success: false,
        error: `${message}`,
      },
      { status: 500 }
    );
  }
}
