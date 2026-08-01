import { NextResponse } from 'next/server';
import type { TechnicalBias, TrendlyneCardSummary } from '@/lib/intelligence-summary';

export const runtime = 'nodejs';

const MAX_BATCH = 8;
const CACHE_TTL_MS = 30 * 60 * 1000;
const FETCH_HEADERS = {
  Accept: 'text/html,application/json,text/plain,*/*',
  Referer: 'https://trendlyne.com/',
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
};

const summaryCache = new Map<string, { data: TrendlyneCardSummary; expires: number }>();

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

function parseAttributeJson(html: string, attribute: string): unknown {
  const pattern = new RegExp(`${attribute}\\s*=\\s*"([^"]+)"`, 'i');
  const match = html.match(pattern);
  if (!match?.[1]) return null;
  try {
    return JSON.parse(decodeHtmlEntities(match[1]));
  } catch {
    return null;
  }
}

function parseChecklistSummary(html: string): Pick<
  TrendlyneCardSummary,
  'checklistPassed' | 'checklistTotal' | 'checklistPassPct' | 'checklistInsight'
> {
  const totalCount = parseAttributeJson(html, 'data-total-count') as
    | { Yes?: number; No?: number; total?: number; checklistP?: number; insightShort?: string }
    | null;

  if (!totalCount || typeof totalCount.total !== 'number') {
    return {};
  }

  return {
    checklistPassed: typeof totalCount.Yes === 'number' ? totalCount.Yes : undefined,
    checklistTotal: totalCount.total,
    checklistPassPct: typeof totalCount.checklistP === 'number' ? totalCount.checklistP : undefined,
    checklistInsight: totalCount.insightShort,
  };
}

function parseSwotCounts(html: string): Pick<
  TrendlyneCardSummary,
  'swotStrengths' | 'swotWeaknesses' | 'swotOpportunities' | 'swotThreats' | 'swotNet'
> {
  const quadrants: Array<{ key: keyof TrendlyneCardSummary; label: string }> = [
    { key: 'swotStrengths', label: 'Strengths' },
    { key: 'swotWeaknesses', label: 'Weakness' },
    { key: 'swotOpportunities', label: 'Opportunity' },
    { key: 'swotThreats', label: 'Threats' },
  ];

  const counts: Partial<Record<keyof TrendlyneCardSummary, number>> = {};
  for (const { key, label } of quadrants) {
    const section = html.match(new RegExp(`<ul[^>]*data-value="${label}"[^>]*>([\\s\\S]*?)</ul>`, 'i'));
    counts[key] = section ? (section[1].match(/<li>/gi) ?? []).length : 0;
  }

  const s = counts.swotStrengths ?? 0;
  const w = counts.swotWeaknesses ?? 0;
  const o = counts.swotOpportunities ?? 0;
  const t = counts.swotThreats ?? 0;

  if (s + w + o + t === 0) {
    return {};
  }

  return {
    swotStrengths: s,
    swotWeaknesses: w,
    swotOpportunities: o,
    swotThreats: t,
    swotNet: s + o - w - t,
  };
}

function deriveTechnicalBias(body: Record<string, unknown> | undefined): {
  technicalBias?: TechnicalBias;
  technicalMomentumScore?: number;
  maBullish?: number;
  maTotal?: number;
  oscillatorBullish?: number;
  oscillatorTotal?: number;
} {
  const parameters = (body?.parameters ?? {}) as Record<string, unknown>;
  const momentum = parameters.momentum as { value?: number; insight?: { shorttext?: string }; color?: string } | undefined;
  const maSignal = parameters.ma_signal as { bullish?: number; bearish?: number; sma_total?: number } | undefined;
  const oscillatorSignal = parameters.oscillator_signal as { bullish?: number; bearish?: number } | undefined;

  const momentumScore = typeof momentum?.value === 'number' ? momentum.value : undefined;
  const maBullish = typeof maSignal?.bullish === 'number' ? maSignal.bullish : undefined;
  const maBearish = typeof maSignal?.bearish === 'number' ? maSignal.bearish : undefined;
  const maTotal =
    typeof maSignal?.sma_total === 'number'
      ? maSignal.sma_total
      : maBullish != null && maBearish != null
        ? maBullish + maBearish
        : undefined;

  const oscillatorBullish =
    typeof oscillatorSignal?.bullish === 'number' ? oscillatorSignal.bullish : undefined;
  const oscillatorBearish =
    typeof oscillatorSignal?.bearish === 'number' ? oscillatorSignal.bearish : undefined;
  const oscillatorTotal =
    oscillatorBullish != null && oscillatorBearish != null ? oscillatorBullish + oscillatorBearish : undefined;

  let technicalBias: TechnicalBias | undefined;
  if (momentumScore != null) {
    if (momentumScore >= 70) technicalBias = 'bullish';
    else if (momentumScore <= 35) technicalBias = 'bearish';
    else technicalBias = 'neutral';
  } else if (maBullish != null && maTotal) {
    const maRatio = maBullish / maTotal;
    if (maRatio >= 0.65) technicalBias = 'bullish';
    else if (maRatio <= 0.35) technicalBias = 'bearish';
    else technicalBias = 'neutral';
  } else if (oscillatorBullish != null && oscillatorTotal) {
    const oscRatio = oscillatorBullish / oscillatorTotal;
    if (oscRatio >= 0.6) technicalBias = 'bullish';
    else if (oscRatio <= 0.4) technicalBias = 'bearish';
    else technicalBias = 'neutral';
  }

  const momentumColor = String(momentum?.color ?? '').toLowerCase();
  if (technicalBias === 'neutral' && momentumColor === 'positive') technicalBias = 'bullish';
  if (technicalBias === 'neutral' && momentumColor === 'negative') technicalBias = 'bearish';

  return {
    technicalBias,
    technicalMomentumScore: momentumScore,
    maBullish,
    maTotal,
    oscillatorBullish,
    oscillatorTotal,
  };
}

async function fetchTechnicalSummary(ticker: string): Promise<ReturnType<typeof deriveTechnicalBias>> {
  const widgetRes = await fetch(
    `https://trendlyne.com/web-widget/technical-widget/Poppins/${encodeURIComponent(ticker)}`,
    { cache: 'no-store', headers: FETCH_HEADERS },
  );
  if (!widgetRes.ok) return {};

  const widgetHtml = await widgetRes.text();
  const apiUrlMatch = widgetHtml.match(/data-technical-data-api-url\s*=\s*"([^"]+)"/i);
  const apiUrl = apiUrlMatch?.[1] ? decodeHtmlEntities(apiUrlMatch[1]) : null;
  if (!apiUrl) return {};

  const techRes = await fetch(apiUrl, { cache: 'no-store', headers: FETCH_HEADERS });
  if (!techRes.ok) return {};

  const payload = await techRes.json();
  const body = payload?.body as Record<string, unknown> | undefined;
  return deriveTechnicalBias(body);
}

async function fetchTrendlyneSummary(ticker: string): Promise<TrendlyneCardSummary> {
  const normalized = ticker.trim().toUpperCase();
  const cached = summaryCache.get(normalized);
  if (cached && cached.expires > Date.now()) {
    return cached.data;
  }

  const result: TrendlyneCardSummary = { ticker: normalized, fetchedAt: new Date().toISOString() };

  try {
    const [checklistRes, swotRes, technical] = await Promise.all([
      fetch(
        `https://trendlyne.com/web-widget/checklist-widget/Poppins/${encodeURIComponent(normalized)}`,
        { cache: 'no-store', headers: FETCH_HEADERS },
      ),
      fetch(
        `https://trendlyne.com/web-widget/swot-widget/Poppins/${encodeURIComponent(normalized)}`,
        { cache: 'no-store', headers: FETCH_HEADERS },
      ),
      fetchTechnicalSummary(normalized),
    ]);

    if (checklistRes.ok) {
      const checklistHtml = await checklistRes.text();
      Object.assign(result, parseChecklistSummary(checklistHtml));
    }

    if (swotRes.ok) {
      const swotHtml = await swotRes.text();
      Object.assign(result, parseSwotCounts(swotHtml));
    }

    Object.assign(result, technical);
  } catch (err) {
    result.error = err instanceof Error ? err.message : 'Trendlyne fetch failed';
  }

  summaryCache.set(normalized, { data: result, expires: Date.now() + CACHE_TTL_MS });
  return result;
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const singleTicker = requestUrl.searchParams.get('ticker')?.trim().toUpperCase();
  const batchRaw = requestUrl.searchParams.get('tickers');

  const tickers = singleTicker
    ? [singleTicker]
    : (batchRaw ?? '')
        .split(',')
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean)
        .slice(0, MAX_BATCH);

  if (!tickers.length) {
    return NextResponse.json(
      { error: 'Provide ticker=SYMBOL or tickers=SYM1,SYM2 (max 8).' },
      { status: 400 },
    );
  }

  const summaries: Record<string, TrendlyneCardSummary> = {};
  await Promise.all(
    tickers.map(async (ticker) => {
      summaries[ticker] = await fetchTrendlyneSummary(ticker);
    }),
  );

  if (singleTicker) {
    return NextResponse.json(summaries[singleTicker]);
  }

  return NextResponse.json({ summaries, count: tickers.length, maxBatch: MAX_BATCH });
}
