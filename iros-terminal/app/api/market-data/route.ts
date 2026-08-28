import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL = process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";
const CACHE_TTL_MS = Math.max(250, Number(process.env.MARKET_READ_CACHE_MS ?? 2000));
const STALE_TTL_MS = Math.max(CACHE_TTL_MS, Number(process.env.MARKET_READ_STALE_MS ?? 30000));
const BACKEND_TIMEOUT_MS = Math.max(1000, Number(process.env.MARKET_READ_BACKEND_TIMEOUT_MS ?? 8000));

type CacheEntry = { data: unknown; expiresAt: number; staleUntil: number };
type MarketReadState = { cache: Map<string, CacheEntry>; inFlight: Map<string, Promise<unknown>> };
const globalState = globalThis as typeof globalThis & { __irosMarketReadState?: MarketReadState };
const state = globalState.__irosMarketReadState ??= { cache: new Map(), inFlight: new Map() };
const cache = state.cache;
const inFlight = state.inFlight;

function reply(data: unknown, state: string, status = 200) {
  return NextResponse.json(data, {
    status,
    headers: {
      "x-iros-market-cache": state,
      "cache-control": "private, no-store, max-age=0",
    },
  });
}

async function fetchBackend(url: URL): Promise<unknown> {
  const res = await fetch(url.toString(), {
    cache: "no-store",
    signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Backend HTTP ${res.status}`);
  }
  return res.json();
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const pool = requestUrl.searchParams.get("pool");
  const prompt = requestUrl.searchParams.get("prompt");
  const backendUrl = new URL(`${BACKEND_URL}/api/market-data`);
  if (pool) backendUrl.searchParams.set("pool", pool);
  if (prompt) backendUrl.searchParams.set("prompt", prompt);

  // Custom prompts are not shared between users. Normal dashboard reads are.
  const key = prompt ? `private:${crypto.randomUUID()}` : `pool:${pool ?? "default"}`;
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && now < cached.expiresAt) return reply(cached.data, "HIT");

  try {
    let pending = inFlight.get(key);
    const coalesced = Boolean(pending);
    if (!pending) {
      pending = fetchBackend(backendUrl);
      inFlight.set(key, pending);
    }
    const data = await pending;
    cache.set(key, {
      data,
      expiresAt: Date.now() + CACHE_TTL_MS,
      staleUntil: Date.now() + STALE_TTL_MS,
    });
    return reply(data, coalesced ? "COALESCED" : "MISS");
  } catch (err) {
    const stale = cache.get(key);
    if (stale && Date.now() < stale.staleUntil) return reply(stale.data, "STALE");
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return reply({ success: false, error: message }, "ERROR", 503);
  } finally {
    inFlight.delete(key);
  }
}
