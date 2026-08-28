from pathlib import Path

root = Path(__file__).resolve().parents[1]
route = root / 'iros-terminal/app/api/market-data/route.ts'
text = route.read_text(encoding='utf-8')
text = text.replace(
    'const cache = new Map<string, CacheEntry>();\nconst inFlight = new Map<string, Promise<unknown>>();',
    'type MarketReadState = { cache: Map<string, CacheEntry>; inFlight: Map<string, Promise<unknown>> };\nconst globalState = globalThis as typeof globalThis & { __irosMarketReadState?: MarketReadState };\nconst state = globalState.__irosMarketReadState ??= { cache: new Map(), inFlight: new Map() };\nconst cache = state.cache;\nconst inFlight = state.inFlight;'
)
route.write_text(text, encoding='utf-8')

edge_dir = root / 'iros-terminal/app/api/market-data.csv'
edge_dir.mkdir(parents=True, exist_ok=True)
edge = '''import { NextResponse } from "next/server";\n\nexport const runtime = "nodejs";\nconst BACKEND_URL = process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";\nconst CACHE_TTL_MS = Math.max(1000, Number(process.env.MARKET_EDGE_CACHE_MS ?? 5000));\nconst STALE_TTL_MS = Math.max(CACHE_TTL_MS, Number(process.env.MARKET_EDGE_STALE_MS ?? 60000));\nconst BACKEND_TIMEOUT_MS = Math.max(1000, Number(process.env.MARKET_READ_BACKEND_TIMEOUT_MS ?? 8000));\n\ntype CacheEntry = { data: unknown; expiresAt: number; staleUntil: number };\ntype MarketEdgeState = { cache: Map<string, CacheEntry>; inFlight: Map<string, Promise<unknown>> };\nconst globalState = globalThis as typeof globalThis & { __irosMarketEdgeState?: MarketEdgeState };\nconst state = globalState.__irosMarketEdgeState ??= { cache: new Map(), inFlight: new Map() };\n\nfunction reply(data: unknown, stateName: string, status = 200) {\n  return NextResponse.json(data, {\n    status,\n    headers: {\n      "x-iros-market-cache": stateName,\n      "cache-control": "public, max-age=2, stale-while-revalidate=30, stale-if-error=60",\n      "cdn-cache-control": "public, max-age=5, stale-while-revalidate=60, stale-if-error=120",\n      "cloudflare-cdn-cache-control": "public, max-age=5, stale-while-revalidate=60, stale-if-error=120",\n      "x-content-type-options": "nosniff",\n    },\n  });\n}\n\nasync function fetchBackend(url: URL): Promise<unknown> {\n  const res = await fetch(url.toString(), { cache: "no-store", signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) });\n  if (!res.ok) throw new Error((await res.text()) || `Backend HTTP ${res.status}`);\n  return res.json();\n}\n\nexport async function GET(request: Request) {\n  const requestUrl = new URL(request.url);\n  const pool = requestUrl.searchParams.get("pool");\n  const backendUrl = new URL(`${BACKEND_URL}/api/market-data`);\n  if (pool) backendUrl.searchParams.set("pool", pool);\n  const key = `pool:${pool ?? "default"}`;\n  const now = Date.now();\n  const cached = state.cache.get(key);\n  if (cached && now < cached.expiresAt) return reply(cached.data, "HIT");\n\n  try {\n    let pending = state.inFlight.get(key);\n    const coalesced = Boolean(pending);\n    if (!pending) {\n      pending = fetchBackend(backendUrl);\n      state.inFlight.set(key, pending);\n    }\n    const data = await pending;\n    const savedAt = Date.now();\n    state.cache.set(key, { data, expiresAt: savedAt + CACHE_TTL_MS, staleUntil: savedAt + STALE_TTL_MS });\n    return reply(data, coalesced ? "COALESCED" : "MISS");\n  } catch (err) {\n    const stale = state.cache.get(key);\n    if (stale && Date.now() < stale.staleUntil) return reply(stale.data, "STALE");\n    const message = err instanceof Error ? err.message : "Backend unreachable";\n    return reply({ success: false, error: message }, "ERROR", 503);\n  } finally {\n    state.inFlight.delete(key);\n  }\n}\n'''
(edge_dir / 'route.ts').write_text(edge, encoding='utf-8')

market_api = root / 'iros-terminal/lib/market-api.ts'
text = market_api.read_text(encoding='utf-8')
old = '    : `/api/market-data${pool ? `?pool=${encodeURIComponent(pool)}` : ""}`;'
new = '    : `/api/market-data.csv${pool ? `?pool=${encodeURIComponent(pool)}` : ""}`;'
if old not in text:
    raise SystemExit('market-api read URL pattern not found')
text = text.replace(old, new, 1)
text = text.replace('    cache: "no-store",\n    signal: AbortSignal.timeout(25_000),', '    cache: "default",\n    signal: AbortSignal.timeout(12_000),', 1)
market_api.write_text(text, encoding='utf-8')

load = root / 'performance/load_test_1000.py'
text = load.read_text(encoding='utf-8')
text = text.replace('("/api/market-data", 0.30),', '("/api/market-data.csv", 0.30),')
text = text.replace('                "cache-control": "no-cache",\n', '')
load.write_text(text, encoding='utf-8')

compose = root / 'docker-compose.yml'
text = compose.read_text(encoding='utf-8')
needle = '      MARKET_READ_BACKEND_TIMEOUT_MS: "8000"\n'
if needle in text and 'MARKET_EDGE_CACHE_MS' not in text:
    text = text.replace(needle, needle + '      MARKET_EDGE_CACHE_MS: "5000"\n      MARKET_EDGE_STALE_MS: "60000"\n')
compose.write_text(text, encoding='utf-8')
