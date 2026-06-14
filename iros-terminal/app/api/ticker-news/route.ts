import { NextResponse } from "next/server";

export const runtime = "nodejs";
const AI_NEWS_URL =
  process.env.AI_NEWS_URL ?? "http://127.0.0.1:8001";

const TICKER_COMPANY_MAP: Record<string, string> = {
  RELIANCE: "Reliance Industries Ltd",
  TCS: "Tata Consultancy Services Ltd",
  HDFCBANK: "HDFC Bank Ltd",
  INFY: "Infosys Ltd",
  ICICIBANK: "ICICI Bank Ltd",
  KOTAKBANK: "Kotak Mahindra Bank Ltd",
  SBIN: "State Bank of India",
  BHARTIARTL: "Bharti Airtel Ltd",
  ITC: "ITC Ltd",
  WIPRO: "Wipro Ltd",
  HINDUNILVR: "Hindustan Unilever Ltd",
  LT: "Larsen & Toubro Ltd",
  TITAN: "Titan Company Ltd",
  ASIANPAINT: "Asian Paints Ltd",
  MARUTI: "Maruti Suzuki India Ltd",
  BAJFINANCE: "Bajaj Finance Ltd",
  NTPC: "NTPC Ltd",
  POWERGRID: "Power Grid Corporation of India Ltd",
  AXISBANK: "Axis Bank Ltd",
  SUNPHARMA: "Sun Pharmaceutical Industries Ltd",
};

function generateMockReport(ticker: string, companyName: string) {
  const company = companyName || TICKER_COMPANY_MAP[ticker.toUpperCase()] || ticker;
  return {
    ticker: ticker.toUpperCase(),
    company_name: company,
    articles_scraped: 0,
    articles_after_dedup: 0,
    generated_at: new Date().toISOString(),
    cached: false,
    insider_activity: "Backend not running — start `python backend/ai_news_server.py` to scrape real insider activity data.",
    institutional_activity: "Backend not running — start the AI news server to get FII/DII activity.",
    order_book_block_deals: "Backend not running — start the AI news server to get order book data.",
    future_expansion_capex: "Backend not running — start the AI news server to get expansion/capex news.",
    auditor_changes: "Backend not running — start the AI news server to get auditor change data.",
    dividend_news: "Backend not running — start the AI news server to get dividend/buyback news.",
    new_orders_contracts: "Backend not running — start the AI news server to get new order/contract data.",
    earnings_results: "Backend not running — start the AI news server to get earnings data.",
    management_changes: "Backend not running — start the AI news server to get management change data.",
    regulatory_filings: "Backend not running — start the AI news server to get regulatory filing data.",
    sentiment_overall: "Neutral",
    risk_flags: "Scraper backend offline — start the server to enable live analysis.",
    summary_headline: `${company}: AI news scraper backend is not running.`,
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

    // Try to fetch from backend, fall back to mock if backend is down
    try {
      const backendUrl = new URL(`${AI_NEWS_URL}/api/ticker-news`);
      backendUrl.searchParams.set("ticker", ticker);
      if (company) backendUrl.searchParams.set("company", company);
      if (requestUrl.searchParams.get("max_articles")) backendUrl.searchParams.set("max_articles", requestUrl.searchParams.get("max_articles")!);
      if (requestUrl.searchParams.get("include_raw")) backendUrl.searchParams.set("include_raw", requestUrl.searchParams.get("include_raw")!);
      if (requestUrl.searchParams.get("force_refresh")) backendUrl.searchParams.set("force_refresh", requestUrl.searchParams.get("force_refresh")!);

      const res = await fetch(backendUrl.toString(), {
        cache: "no-store",
        signal: AbortSignal.timeout(90_000),
      });

      if (res.ok) {
        const data = await res.json();
        return NextResponse.json({ success: true, payload: { ...data, cached: data.cached ?? false } });
      }
    } catch {
      // Backend unavailable — fall through to mock
    }

    // Mock fallback when backend is down
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
