"use client";

import { useCallback, useEffect, useState } from "react";

export type MacroRow = {
  label: string;
  val: string;
  delta: string;
  state: string;
  sparkline?: number[];
};

export type LiveStock = {
  ticker: string;
  name: string;
  capSize: string;
  ltp: string;
  ltpRaw: number;
  delta: string;
  state: string;
  score?: number;
  verdict?: string;
  volume?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
};

export type MarketNewsItem = {
  source: string;
  title: string;
  link: string;
  summary: string;
  publishedAt: string;
};

export type LedgerStock = {
  ticker: string;
  scale?: string;
  live_price?: string;
  day_change_pct?: string;
  delta?: string;
  score?: number;
  action?: string;
  name?: string;
  selection_reason?: string;
  wl_ratio?: string;
  policy_allocation_pct?: string;
};

export type ForensicMetricKey = "beneish_m_score" | "altman_z_score" | "ocf_ebitda_ratio" | "mansfield_relative_strength";

export type ScoringMatrixDetails = Record<ForensicMetricKey, string | number | undefined>;

export type SevenICGatesDetails = {
  q1_fund_buying: string;
  q2_liquidity_delivery: string;
  q3_catalyst_validation: string;
  q4_bear_thesis: string;
  q5_risk_reward: string;
  q6_quantitative_milestone: string;
  q7_governance_gate: string;
};

export type FactorHubDetails = {
  momentum_factor: string;
  quality_factor: string;
  value_factor: string;
  low_vol_factor: string;
  selection_reason?: string;
};

export type SelectionMeta = {
  mode: string;
  reason: string;
  dataDate: string;
};

// ---------------------------------------------------------------------------
// AI Ticker News types
// ---------------------------------------------------------------------------

export type TickerNewsCategory = {
  summary: string;
  articles: Array<{
    title: string;
    source: string;
    url: string;
    publishedAt: string;
  }>;
};

export type AITickerNewsReport = {
  ticker: string;
  company_name: string;
  articles_scraped: number;
  articles_after_dedup: number;
  generated_at: string;
  cached?: boolean;

  // LLM-generated categories
  insider_activity: string;
  institutional_activity: string;
  order_book_block_deals: string;
  future_expansion_capex: string;
  auditor_changes: string;
  dividend_news: string;
  new_orders_contracts: string;
  earnings_results: string;
  management_changes: string;
  regulatory_filings: string;

  // Meta
  sentiment_overall: "Bullish" | "Neutral" | "Bearish";
  risk_flags: string;
  summary_headline: string;

  // Optional raw articles
  raw_articles?: Array<{
    title: string;
    source: string;
    url: string;
    summary: string;
    published_at: string;
    relevance: string;
  }>;

  // Error state
  error?: boolean;
  message?: string;
  error_detail?: string;
};

export type TerminalIntelligence = {
  news_catalysts_card?: string;
  insider_insti_activity_card?: string;
  macro_anchors_card?: string;
  forensic_screen_card?: string;
  why_interested?: string;
  future_revenue_model?: string;
  current_model?: string;
  ledger_stocks?: LedgerStock[];
  active_scoring_matrix?: Record<string, string | number>;
  active_seven_ic_gates?: Record<string, string>;
  active_risk_calc?: Record<string, unknown>;
  active_factor_hub?: Record<string, string>;
};

export type MarketDataResponse = {
  success: boolean;
  source?: string;
  rawSources?: string[];
  updatedAt?: string;
  mockTickers?: string[];
  availablePools?: string[];
  activePool?: string;
  poolDescription?: string;
  stocks?: LiveStock[];
  stockQuotes?: Record<string, LiveStock>;
  macroDataStrip?: {
    morning: MacroRow[];
    evening: MacroRow[];
  };
  globalMacro?: {
    indices: MacroRow[];
    commodities: MacroRow[];
  };
  news?: MarketNewsItem[];
  newsSummary?: string;
  llmError?: string;
  terminalIntelligence?: TerminalIntelligence;
  tickerIntelligenceByTicker?: Record<string, TerminalIntelligence>;
  tickerNewsByTicker?: Record<string, AITickerNewsReport>;
  isSnapshotFallback?: boolean;
  selectionMeta?: SelectionMeta;
};

export type FeedStatus = "idle" | "loading" | "live" | "offline";

// Same-origin Next.js proxy → Python feed (see app/api/market-data/route.ts)
// Defaults to the direct Python backend when no build-time proxy URL is configured.
const MARKET_API_URL = process.env.NEXT_PUBLIC_MARKET_API_URL ?? "";

const STALE_AFTER_MS = 300_000;

export async function fetchMarketData(pool?: string): Promise<MarketDataResponse> {
  const url = MARKET_API_URL
    ? new URL("/api/market-data", MARKET_API_URL)
    : `/api/market-data${pool ? `?pool=${encodeURIComponent(pool)}` : ""}`;

  if (typeof url !== "string") {
    if (pool) {
      url.searchParams.set("pool", pool);
    }
  }

  const res = await fetch(typeof url === "string" ? url : url.toString(), { cache: "no-store" });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error) detail = body.error;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const data: MarketDataResponse = await res.json();
  if (!data.success) {
    throw new Error("Market API returned success=false");
  }
  return data;
}

export async function fetchRefreshDataOnDemand(pool?: string): Promise<MarketDataResponse> {
  const res = await fetch("/api/refresh-data-on-demand", {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ pool, refreshTickerNews: false }),
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error) detail = body.error;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  const data = await res.json();
  if (!data.success) {
    throw new Error(data.error ?? "Refresh API returned success=false");
  }
  if (!data.payload) {
    throw new Error("Refresh API returned an empty payload");
  }
  return data.payload as MarketDataResponse;
}

export function useMarketData(pool?: string, pollMs = 30_000) {
  const [data, setData] = useState<MarketDataResponse | null>(null);
  const [status, setStatus] = useState<FeedStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number>(0);

  // Shared invalidate key so consumers can coordinate revalidation
  const [invalidateKey, setInvalidateKey] = useState(0);

  const refresh = useCallback(async (forceLive: boolean = false) => {
    if (status === "loading") {
      return;
    }
    setStatus((prev) => (prev === "idle" ? "loading" : prev));
    try {
      // Use the on-demand refresh endpoint when forceLive is true,
      // so the frontend doesn't revert to a stale snapshot mid-session.
      const payload = forceLive
        ? await fetchRefreshDataOnDemand(pool)
        : await fetchMarketData(pool);
      setData(payload);
      setStatus("live");
      setError(null);
      setLastUpdatedAt(Date.now());
    } catch (err) {
      setStatus("offline");
      setError(err instanceof Error ? err.message : "Feed unavailable");
    }
  }, [pool, status]);

  const refreshOnDemand = useCallback(async () => {
    setStatus("loading");
    try {
      const payload = await fetchRefreshDataOnDemand(pool);
      setData(payload);
      setStatus("live");
      setError(null);
      setLastUpdatedAt(Date.now());
      // Bump shared invalidate key so dependent SWR consumers revalidate together
      setInvalidateKey((k) => k + 1);
    } catch (err) {
      setStatus("offline");
      setError(err instanceof Error ? err.message : "Feed unavailable");
      throw err;
    }
  }, [pool]);

  useEffect(() => {
    const tick = async () => {
      const age = Date.now() - lastUpdatedAt;
      if (age >= STALE_AFTER_MS) {
        try {
          await refresh(false);
        } catch {
          setStatus("offline");
          setError("Feed unavailable");
        }
      }
    };
    tick();
    const id = setInterval(tick, pollMs);
    return () => clearInterval(id);
  }, [refresh, pollMs, lastUpdatedAt]);

  const isStale = useCallback(() => {
    return Date.now() - lastUpdatedAt >= STALE_AFTER_MS;
  }, [lastUpdatedAt]);

  return { data, status, error, refresh, refreshOnDemand, invalidateKey, isStale };
}

// ---------------------------------------------------------------------------
// AI Ticker News fetcher
// ---------------------------------------------------------------------------

export async function fetchTickerNewsReport(
   ticker: string,
   options?: {
     company?: string;
     maxArticles?: number;
     includeRaw?: boolean;
     forceRefresh?: boolean;
   }
): Promise<AITickerNewsReport> {
   const params = new URLSearchParams();
   params.set("ticker", ticker);
   if (options?.company) params.set("company", options.company);
   if (options?.maxArticles) params.set("max_articles", String(options.maxArticles));
   if (options?.includeRaw) params.set("include_raw", "true");
   if (options?.forceRefresh) params.set("force_refresh", "true");

   const res = await fetch(`/api/ticker-news?${params.toString()}`, {
     cache: "no-store",
     signal: AbortSignal.timeout(130_000),
   });

   if (!res.ok) {
     let detail = `HTTP ${res.status}`;
     try {
       const body = await res.json();
       if (body?.error) detail = body.error;
     } catch {
       /* ignore */
     }
     throw new Error(detail);
   }

   const data = await res.json();
   if (!data.success || !data.payload) {
     throw new Error(data.error ?? "Ticker news API returned unsuccessful response");
   }

   return data.payload as AITickerNewsReport;
}

// ---------------------------------------------------------------------------
// NSE Sparkline fetcher - direct from NSE India API
// ---------------------------------------------------------------------------

export type SparkFlag = '1D' | '1M' | '1Y';

export async function fetchNseSparkline(
   ticker: string,
   flag: SparkFlag
): Promise<number[]> {
   const identifier = `${ticker.toUpperCase().trim()}EQN`;
   const nseUrl = `https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi?functionName=getSymbolgraphData&&identifier=${encodeURIComponent(identifier)}&flag=${encodeURIComponent(flag)}`;

   const res = await fetch(nseUrl, {
     headers: {
       "User-Agent":
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
       Accept: "application/json,text/plain,*/*",
       "Accept-Language": "en-US,en;q=0.5",
       Referer: "https://www.nseindia.com/",
     },
     cache: "no-store",
   });

   if (!res.ok) {
     throw new Error(`NSE HTTP ${res.status}`);
   }

   const raw = await res.json();

   const graphData: Array<Record<string, unknown>> =
     raw?.data?.grapthData ?? raw?.data?.graphData ?? raw?.data ?? raw?.grapthData ?? raw?.graphData ?? [];

   const sparkline: number[] = [];
   for (const point of graphData) {
     if (Array.isArray(point) && point.length >= 2 && typeof point[1] === 'number') {
       sparkline.push(point[1]);
     } else if (point && typeof point === "object") {
       const val = (point as Record<string, unknown>).value ?? (point as Record<string, unknown>).close ?? (point as Record<string, unknown>).lastPrice ?? (point as Record<string, unknown>).ltp ?? (point as Record<string, unknown>).price;
       if (typeof val === "number") {
         sparkline.push(val);
       } else if (typeof val === "string") {
         const parsed = parseFloat(val.replace(/,/g, ""));
         if (!isNaN(parsed)) sparkline.push(parsed);
       }
     } else if (typeof point === "number") {
       sparkline.push(point);
     }
   }

   return sparkline;
}
