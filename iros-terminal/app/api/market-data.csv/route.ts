import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL = process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";
const CACHE_TTL_MS = Math.max(1000, Number(process.env.MARKET_EDGE_CACHE_MS ?? 5000));
const STALE_TTL_MS = Math.max(CACHE_TTL_MS, Number(process.env.MARKET_EDGE_STALE_MS ?? 60000));
const BACKEND_TIMEOUT_MS = Math.max(1000, Number(process.env.MARKET_READ_BACKEND_TIMEOUT_MS ?? 8000));

type JsonRecord = Record<string, unknown>;
type CacheEntry = { data: unknown; expiresAt: number; staleUntil: number };
type MarketEdgeState = { cache: Map<string, CacheEntry>; inFlight: Map<string, Promise<unknown>> };
const globalState = globalThis as typeof globalThis & { __irosMarketEdgeState?: MarketEdgeState };
const state = globalState.__irosMarketEdgeState ??= { cache: new Map(), inFlight: new Map() };

function slimDashboardPayload(data: unknown): unknown {
  if (!data || typeof data !== "object" || Array.isArray(data)) return data;
  const source = data as JsonRecord;
  const slim: JsonRecord = { ...source };

  // Per-ticker research and AI detail is lazy-loaded from dedicated endpoints.
  delete slim.tickerIntelligenceByTicker;
  delete slim.tickerNewsByTicker;
  delete slim.deskIcByTicker;

  // stockQuotes duplicates rows already present in stocks. The browser rebuilds
  // the lookup map client-side after download, cutting wire size substantially
  // without changing any deterministic trading or quote values.
  delete slim.stockQuotes;

  slim.publicSnapshotMode = "COMPACT_LAZY_DETAILS_CLIENT_QUOTE_MAP";
  return slim;
}

function reply(data: unknown, stateName: string, status = 200) {
  const body = JSON.stringify(data);
  return new NextResponse(body, {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "x-iros-market-cache": stateName,
      "x-iros-public-snapshot": "compact",
      "x-iros-payload-bytes": String(Buffer.byteLength(body)),
      "cache-control": "public, max-age=2, stale-while-revalidate=30, stale-if-error=60",
      "cdn-cache-control": "public, max-age=5, stale-while-revalidate=60, stale-if-error=120",
      "cloudflare-cdn-cache-control": "public, max-age=5, stale-while-revalidate=60, stale-if-error=120",
      "x-content-type-options": "nosniff",
    },
  });
}

async function fetchBackend(url: URL): Promise<unknown> {
  const res = await fetch(url.toString(), { cache: "no-store", signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) });
  if (!res.ok) throw new Error((await res.text()) || `Backend HTTP ${res.status}`);
  return slimDashboardPayload(await res.json());
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const pool = requestUrl.searchParams.get("pool");
  const backendUrl = new URL(`${BACKEND_URL}/api/market-data`);
  if (pool) backendUrl.searchParams.set("pool", pool);
  const key = `pool:${pool ?? "default"}`;
  const now = Date.now();
  const cached = state.cache.get(key);
  if (cached && now < cached.expiresAt) return reply(cached.data, "HIT");

  try {
    let pending = state.inFlight.get(key);
    const coalesced = Boolean(pending);
    if (!pending) {
      pending = fetchBackend(backendUrl);
      state.inFlight.set(key, pending);
    }
    const data = await pending;
    const savedAt = Date.now();
    state.cache.set(key, { data, expiresAt: savedAt + CACHE_TTL_MS, staleUntil: savedAt + STALE_TTL_MS });
    return reply(data, coalesced ? "COALESCED" : "MISS");
  } catch (err) {
    const stale = state.cache.get(key);
    if (stale && Date.now() < stale.staleUntil) return reply(stale.data, "STALE");
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return reply({ success: false, error: message }, "ERROR", 503);
  } finally {
    state.inFlight.delete(key);
  }
}
