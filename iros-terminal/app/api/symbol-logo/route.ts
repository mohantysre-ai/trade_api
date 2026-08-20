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
type CachedLogo = { svg: string; etag: string; expiresAt: number };
const memoryCache = new Map<string, CachedLogo>();
const pendingLookups = new Map<string, Promise<CachedLogo | null>>();
const MEMORY_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const MEMORY_CACHE_LIMIT = 1_500;

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

function logoResponse(request: Request, cached: CachedLogo) {
  if (request.headers.get("if-none-match") === cached.etag) {
    return new Response(null, {
      status: 304,
      headers: { "Cache-Control": CACHE_CONTROL, ETag: cached.etag },
    });
  }
  return new Response(cached.svg, {
    status: 200,
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": CACHE_CONTROL,
      ETag: cached.etag,
      "X-Content-Type-Options": "nosniff",
      "X-Logo-Provider": "TradingView",
      "X-Logo-Cache": "memory",
    },
  });
}

async function resolveLogo(rawSymbol: string, kind: LogoKind): Promise<CachedLogo | null> {
  const cacheKey = `${kind}:${rawSymbol.toUpperCase()}`;
  const hit = memoryCache.get(cacheKey);
  if (hit && hit.expiresAt > Date.now()) return hit;
  if (hit) memoryCache.delete(cacheKey);

  const active = pendingLookups.get(cacheKey);
  if (active) return active;

  const lookup = (async () => {
    const plan = buildLookupPlan(rawSymbol, kind, process.env.SYMBOL_LOGO_DEFAULT_EXCHANGE || "NSE");
    const searchUrl = new URL(SEARCH_ENDPOINT);
    searchUrl.searchParams.set("text", plan.query);
    searchUrl.searchParams.set("hl", "1");
    searchUrl.searchParams.set("lang", "en");
    searchUrl.searchParams.set("search_type", plan.searchType);
    searchUrl.searchParams.set("domain", "production");
    if (plan.exchange) searchUrl.searchParams.set("exchange", plan.exchange);

    const searchResponse = await providerFetch(searchUrl.toString());
    if (!searchResponse.ok) return null;
    const payload = (await searchResponse.json()) as { symbols?: SearchResult[] };
    const logoId = selectExactLogo(Array.isArray(payload.symbols) ? payload.symbols : [], plan);
    if (!logoId) return null;

    const logoAsset = await providerFetch(`${LOGO_ENDPOINT}/${logoId}.svg`);
    if (!logoAsset.ok) return null;
    const svg = await logoAsset.text();
    if (
      svg.length > 200_000 ||
      !/<svg[\s>]/i.test(svg) ||
      /<script[\s>]|<foreignObject[\s>]|\son\w+\s*=/i.test(svg)
    ) return null;

    const cached = {
      svg,
      etag: `W/"${logoId.replace(/[^a-z0-9_-]/gi, "-")}-${svg.length}"`,
      expiresAt: Date.now() + MEMORY_TTL_MS,
    };
    if (memoryCache.size >= MEMORY_CACHE_LIMIT) {
      const oldest = memoryCache.keys().next().value;
      if (oldest) memoryCache.delete(oldest);
    }
    memoryCache.set(cacheKey, cached);
    return cached;
  })().finally(() => pendingLookups.delete(cacheKey));
  pendingLookups.set(cacheKey, lookup);
  return lookup;
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const rawSymbol = url.searchParams.get("symbol")?.trim() || "";
    const kind: LogoKind = url.searchParams.get("kind") === "index" ? "index" : "stock";
    if (!rawSymbol || rawSymbol.length > 60 || !/^[\w .&/:=+^()-]+$/u.test(rawSymbol)) {
      return unavailable("Valid symbol param required", 400);
    }

    const cached = await resolveLogo(rawSymbol, kind);
    if (!cached) return unavailable(`No verified logo for ${rawSymbol}`);
    return logoResponse(request, cached);
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError" ? "Logo lookup timed out" : "Logo lookup failed";
    return unavailable(message, 502);
  }
}
