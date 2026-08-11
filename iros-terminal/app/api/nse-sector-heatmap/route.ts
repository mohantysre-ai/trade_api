import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const NSE_URL = 'https://www.nseindia.com/api/heatmap-index?type=Sectoral%20Indices';
const BACKEND_URL = process.env.MARKET_API_URL ?? 'http://127.0.0.1:8000';
const FRESH_MS = 60_000;
let cache: { at: number; rows: SectorRow[] } | null = null;

type SectorRow = { name: string; changePct: number; last?: number };

function numeric(value: unknown): number | undefined {
  const n = typeof value === 'string' ? Number(value.replace(/,/g, '').replace('%', '')) : Number(value);
  return Number.isFinite(n) ? n : undefined;
}

function normalize(payload: unknown): SectorRow[] {
  const root = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const candidates = [root.data, root.sectors, root.value, root.indices, root.sectoralIndices, payload];
  const rows = candidates.find(Array.isArray) as unknown[] | undefined;
  if (!rows) return [];
  return rows.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const row = item as Record<string, unknown>;
    const name = String(row.indexName ?? row.name ?? row.symbol ?? row.index ?? '').trim();
    const changePct = numeric(row.pChange ?? row.percentChange ?? row.changePercent ?? row.perChange);
    if (!name || changePct === undefined) return [];
    return [{ name, changePct, last: numeric(row.last ?? row.lastPrice ?? row.currentValue) }];
  });
}

export async function GET() {
  const now = Date.now();
  if (cache && now - cache.at < FRESH_MS) {
    return NextResponse.json({ success: true, data: cache.rows, fetchedAt: new Date(cache.at).toISOString(), cached: true, stale: false });
  }
  try {
    // Prefer the market API so every frontend instance and user shares the
    // same NSE fetch/cache used by intraday ranking. Direct NSE is a fallback.
    let response = await fetch(`${BACKEND_URL}/api/sector-heatmap`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(7_500),
    });
    let rows = response.ok ? normalize(await response.json()) : [];
    if (!rows.length) {
      response = await fetch(NSE_URL, {
        cache: 'no-store',
        signal: AbortSignal.timeout(7_500),
        headers: {
          accept: 'application/json,text/plain,*/*',
          'accept-language': 'en-IN,en;q=0.9',
          referer: 'https://www.nseindia.com/market-data/live-market-indices',
          'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
        },
      });
      if (!response.ok) throw new Error(`NSE HTTP ${response.status}`);
      rows = normalize(await response.json());
    }
    if (!rows.length) throw new Error('NSE returned no sector rows');
    cache = { at: now, rows };
    return NextResponse.json({ success: true, data: rows, fetchedAt: new Date(now).toISOString(), cached: false, stale: false });
  } catch (error) {
    if (cache) return NextResponse.json({ success: true, data: cache.rows, fetchedAt: new Date(cache.at).toISOString(), cached: true, stale: true });
    return NextResponse.json({ success: false, data: [], error: error instanceof Error ? error.message : 'Sector data unavailable' }, { status: 503 });
  }
}
