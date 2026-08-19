import { NextResponse } from "next/server";
import {
  buildLookupPlan,
  selectExactLogo,
  type LogoKind,
  type SearchResult,
} from "@/lib/symbol-logo";

export const runtime = "nodejs";

const SEARCH_ENDPOINT = "https://symbol-search.tradingview.com/symbol_search/v3/";
const LOGO_ENDPOINT = "https://s3-symbol-logo.tradingview.com";
const CACHE_CONTROL = "public, max-age=86400, s-maxage=604800, stale-while-revalidate=2592000";
const NEGATIVE_CACHE_CONTROL = "public, max-age=900, s-maxage=3600";
const PROVIDER_HEADERS = {
  "User-Agent": "Mozilla/5.0 (compatible; AlphixTerminal/1.0)",
  Origin: "https://www.tradingview.com",
  Referer: "https://www.tradingview.com/",
};

async function providerFetch(url: string): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  try {
    return await fetch(url, {
      headers: PROVIDER_HEADERS,
      signal: controller.signal,
      next: { revalidate: 604800 },
    });
  } finally {
    clearTimeout(timeout);
  }
}

function unavailable(message: string, status = 404) {
  return NextResponse.json(
    { error: message },
    { status, headers: { "Cache-Control": NEGATIVE_CACHE_CONTROL } },
  );
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const rawSymbol = url.searchParams.get("symbol")?.trim() || "";
    const kind: LogoKind = url.searchParams.get("kind") === "index" ? "index" : "stock";
    if (!rawSymbol || rawSymbol.length > 60 || !/^[\w .&/:=+^()-]+$/u.test(rawSymbol)) {
      return unavailable("Valid symbol param required", 400);
    }

    const plan = buildLookupPlan(rawSymbol, kind, process.env.SYMBOL_LOGO_DEFAULT_EXCHANGE || "NSE");
    const searchUrl = new URL(SEARCH_ENDPOINT);
    searchUrl.searchParams.set("text", plan.query);
    searchUrl.searchParams.set("hl", "1");
    searchUrl.searchParams.set("lang", "en");
    searchUrl.searchParams.set("search_type", plan.searchType);
    searchUrl.searchParams.set("domain", "production");
    if (plan.exchange) searchUrl.searchParams.set("exchange", plan.exchange);

    const searchResponse = await providerFetch(searchUrl.toString());
    if (!searchResponse.ok) return unavailable("Logo lookup unavailable", 502);
    const payload = (await searchResponse.json()) as { symbols?: SearchResult[] };
    const logoId = selectExactLogo(Array.isArray(payload.symbols) ? payload.symbols : [], plan);
    if (!logoId) return unavailable(`No verified logo for ${rawSymbol}`);

    const logoResponse = await providerFetch(`${LOGO_ENDPOINT}/${logoId}.svg`);
    if (!logoResponse.ok) return unavailable("Logo asset unavailable", 502);
    const svg = await logoResponse.text();
    if (
      svg.length > 200_000 ||
      !/<svg[\s>]/i.test(svg) ||
      /<script[\s>]|<foreignObject[\s>]|\son\w+\s*=/i.test(svg)
    ) {
      return unavailable("Logo asset rejected", 502);
    }

    return new Response(svg, {
      status: 200,
      headers: {
        "Content-Type": "image/svg+xml; charset=utf-8",
        "Cache-Control": CACHE_CONTROL,
        "X-Content-Type-Options": "nosniff",
        "X-Logo-Provider": "TradingView",
      },
    });
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError" ? "Logo lookup timed out" : "Logo lookup failed";
    return unavailable(message, 502);
  }
}
