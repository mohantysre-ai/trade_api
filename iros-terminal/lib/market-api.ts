"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type MacroRow = {
  label: string;
  val: string;
  delta: string;
  state: string;
  sparkline?: number[];
};

export type DeskIcSummary = {
  deskDecision?: string;
  conviction?: number | null;
  oneLiner?: string | null;
  source?: string;
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
  promoter_holding_pct?: number;
  passes_quality_filters?: boolean;
  bulk_deal_value_cr?: number;
  bulk_deal_signal?: boolean;
  deskIcSummary?: DeskIcSummary;
};

export type MarketNewsItem = {
  source: string;
  title: string;
  link: string;
  summary: string;
  publishedAt: string;
  sentiment?: "Bullish" | "Bearish" | "Neutral";
  category?: string;
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

/** Dhan ScanX LONG swing pick — attached to market snapshot for Asset Matrix. */
export type DhanSwingPick = {
  symbol: string;
  name?: string;
  direction?: string;
  buyAbove?: number;
  stopLoss?: number;
  target1?: number;
  target2?: number;
  riskPerShare?: number;
  rrT2?: number;
  rsi?: number;
  deliveryPct?: number;
  score?: number;
  reasons?: string[];
  scanLtp?: number;
};

export type DhanSwingPicksPayload = {
  source?: string;
  picks?: DhanSwingPick[];
  updatedAt?: string;
  isMock?: boolean;
  fromPersisted?: boolean;
  scannedCount?: number;
  longPassedCount?: number;
  error?: string;
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
  lookback_days?: number;
  cached?: boolean;
  evidence_status?: "VERIFIED_RECENT" | "NO_RECENT_EVIDENCE" | "SOURCE_UNAVAILABLE" | string;
  news_schema_version?: number;
  sources_checked?: string[];
  source_diagnostics?: Array<{
    source: string;
    status: string;
    fetched: number;
    accepted: number;
    error?: string;
  }>;
  latest_verified_headlines?: Array<{
    title: string;
    source: string;
    url: string;
    published_at: string;
    relevance: string;
  }>;

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
  sentiment_overall: "Bullish" | "Neutral" | "Bearish" | "—" | string;
  risk_flags: string;
  summary_headline: string;
  llmUsed?: boolean;
  llmProvider?: string;
  llmModel?: string;
  llmError?: string;
  digestSource?: string;
  digestMode?: string;

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
  universeSize?: number;
  volumeScreenedCount?: number;
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
  deskIcByTicker?: Record<string, DeskIcSummary & {
    criteria?: unknown[];
    categoryScores?: Record<string, number | null>;
    llmUsed?: boolean;
    conviction?: number;
  }>;
  isSnapshotFallback?: boolean;
  selectionMeta?: SelectionMeta;
  dhanSwingPicks?: DhanSwingPicksPayload;
};

export type FeedStatus = "idle" | "loading" | "live" | "offline";

// Same-origin Next.js proxy → Python feed (see app/api/market-data/route.ts)
// Defaults to the direct Python backend when no build-time proxy URL is configured.
const MARKET_API_URL = process.env.NEXT_PUBLIC_MARKET_API_URL ?? "";

const STALE_AFTER_MS = 300_000;
const MACRO_POLL_OPEN_MS = 60_000;
/** After cash close, still refresh India/global/commodities strip (slower). */
const MACRO_POLL_CLOSED_MS = 180_000;

export function isNseCashSessionNow(d = new Date()): boolean {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kolkata",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(d);
    const weekday = parts.find((p) => p.type === "weekday")?.value || "";
    if (weekday === "Sat" || weekday === "Sun") return false;
    const hour = Number(parts.find((p) => p.type === "hour")?.value || 0);
    const minute = Number(parts.find((p) => p.type === "minute")?.value || 0);
    const mins = hour * 60 + minute;
    return mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30;
  } catch {
    return false;
  }
}

function macroPollMs(d = new Date()): number {
  return isNseCashSessionNow(d) ? MACRO_POLL_OPEN_MS : MACRO_POLL_CLOSED_MS;
}

export async function fetchRefreshMacros(): Promise<MarketDataResponse> {
  const res = await fetch("/api/refresh-macros", {
    method: "POST",
    cache: "no-store",
    // Keep short — Angel/Yahoo can hang; SNAPSHOT paints from cache first
    signal: AbortSignal.timeout(18_000),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error || body?.detail) detail = body.error || body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const data = await res.json();
  if (!data?.success || !data?.payload) {
    throw new Error(data?.error ?? "Macro refresh returned empty payload");
  }
  return data.payload as MarketDataResponse;
}

export async function fetchMarketData(pool?: string): Promise<MarketDataResponse> {
  const url = MARKET_API_URL
    ? new URL("/api/market-data", MARKET_API_URL)
    : `/api/market-data.csv${pool ? `?pool=${encodeURIComponent(pool)}` : ""}`;

  if (typeof url !== "string") {
    if (pool) {
      url.searchParams.set("pool", pool);
    }
  }

  const res = await fetch(typeof url === "string" ? url : url.toString(), {
    cache: "default",
    signal: AbortSignal.timeout(12_000),
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
    signal: AbortSignal.timeout(15 * 60 * 1_000),
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

export function useMarketData(pool?: string, _pollMs = 30_000) {
  const [data, setData] = useState<MarketDataResponse | null>(null);
  const [status, setStatus] = useState<FeedStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number>(0);
  const lastUpdatedRef = useRef(0);
  const statusRef = useRef<FeedStatus>("idle");

  // Shared invalidate key so consumers can coordinate revalidation
  const [invalidateKey, setInvalidateKey] = useState(0);

  useEffect(() => {
    lastUpdatedRef.current = lastUpdatedAt;
  }, [lastUpdatedAt]);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const refresh = useCallback(async (forceLive: boolean = false) => {
    if (statusRef.current === "loading") {
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
      const ts = Date.now();
      setLastUpdatedAt(ts);
      lastUpdatedRef.current = ts;
    } catch (err) {
      setStatus("offline");
      setError(err instanceof Error ? err.message : "Feed unavailable");
    }
  }, [pool]);

  const refreshOnDemand = useCallback(async () => {
    setStatus("loading");
    try {
      const payload = await fetchRefreshDataOnDemand(pool);
      setData(payload);
      setStatus("live");
      setError(null);
      const ts = Date.now();
      setLastUpdatedAt(ts);
      lastUpdatedRef.current = ts;
      // Bump shared invalidate key so dependent SWR consumers revalidate together
      setInvalidateKey((k) => k + 1);
    } catch (err) {
      setStatus("offline");
      setError(err instanceof Error ? err.message : "Feed unavailable");
      throw err;
    }
  }, [pool]);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        // Always paint from cached snapshot first — live macros can take 60s+ and
        // previously blocked the whole desk on a blank loading state.
        const payload = await fetchMarketData(pool);
        if (cancelled) return;
        setData(payload);
        setStatus("live");
        setError(null);
        const ts = Date.now();
        setLastUpdatedAt(ts);
        lastUpdatedRef.current = ts;

        // SNAPSHOT indexes strip: always attempt a light macro refresh after paint
        // (cash session + after hours). India may be last-close; globals/commodities still move.
        try {
          const live = await fetchRefreshMacros();
          if (cancelled) return;
          setData(live);
          setStatus("live");
          setError(null);
          const liveTs = Date.now();
          setLastUpdatedAt(liveTs);
          lastUpdatedRef.current = liveTs;
        } catch {
          // Keep cached SNAPSHOT; interval poll will retry
        }
      } catch (err) {
        if (cancelled) return;
        setStatus("offline");
        setError(err instanceof Error ? err.message : "Feed unavailable");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pool]);

  useEffect(() => {
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const scheduleNext = () => {
      if (stopped) return;
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(() => {
        void tick();
      }, macroPollMs());
    };

    const tick = async () => {
      if (stopped || inFlight) {
        scheduleNext();
        return;
      }
      inFlight = true;
      try {
        const payload = await fetchRefreshMacros();
        setData(payload);
        setStatus("live");
        setError(null);
        const ts = Date.now();
        setLastUpdatedAt(ts);
        lastUpdatedRef.current = ts;
      } catch {
        // Keep last good SNAPSHOT; if very stale, re-read cached market-data
        const age = Date.now() - lastUpdatedRef.current;
        if (age >= STALE_AFTER_MS) {
          try {
            await refresh(false);
          } catch {
            setStatus("offline");
            setError("Feed unavailable");
          }
        }
      } finally {
        inFlight = false;
        scheduleNext();
      }
    };

    scheduleNext();
    return () => {
      stopped = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [refresh]);

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
   if (options?.maxArticles) {
     const capped = Math.max(1, Math.min(options.maxArticles, 15));
     params.set("max_articles", String(capped));
   }
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

// ---------------------------------------------------------------------------
// Institutional EOD Review (GET/POST /api/eod/*)
// ---------------------------------------------------------------------------

export type EodMarketRegime =
  | "BULL_TRENDING"
  | "BEAR_TRENDING"
  | "HIGH_VOLATILITY_SIDEWAYS"
  | "LOW_VOLATILITY_COMPRESSION"
  | "SECTOR_ROTATION_SELECTIVE"
  | string;

export type EodTradeOutcome =
  | "TARGET_HIT"
  | "STOP_HIT"
  | "NO_ENTRY"
  | "TRAILED_EXIT"
  | "EOD_SQUAREOFF"
  | string;

export type EodProposalStatus =
  | "PENDING_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "INSUFFICIENT_SAMPLES"
  | string;

export type EodTcaBasis = "MODELED" | "OBSERVED" | string;

export type EodTcaNode = {
  basis?: EodTcaBasis | null;
  implementation_shortfall_bps?: number | null;
  delay_cost_bps?: number | null;
  spread_cost_bps?: number | null;
  market_impact_bps?: number | null;
  opportunity_cost_bps?: number | null;
} | null;

export type EodEfficiencyNode = {
  mae_pct?: number | null;
  mfe_pct?: number | null;
  realized_return_ratio?: number | null;
  stop_efficiency_index?: number | null;
} | null;

export type EodAttributionNode = {
  alpha_score?: number | null;
  volume_expansion_contrib?: number | null;
  vwap_alignment_contrib?: number | null;
  momentum_velocity_contrib?: number | null;
  sector_relative_strength_contrib?: number | null;
  open_interest_buildup_contrib?: number | null;
  news_sentiment_contrib?: number | null;
  allocation_effect?: number | null;
  selection_effect?: number | null;
  interaction_effect?: number | null;
} | null;

export type EodCounterfactual = {
  scenario_name: string;
  simulated_outcome?: string | null;
  simulated_pnl_pct?: number | null;
  pnl_delta_vs_actual_pct?: number | null;
  max_drawdown_during_trade_pct?: number | null;
};

export type EodProposalReviewAction = "APPROVE" | "REJECT";

export type EodTimelineCandle = {
  ts?: string | null;
  time?: string | null;
  timestamp?: string | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
};

export type EodTimelineEvent = {
  ts?: string | null;
  time?: string | null;
  timestamp?: string | null;
  type?: string | null;
  event?: string | null;
  price?: number | null;
  label?: string | null;
};

export type EodTradeScorecard = {
  trade_id: string;
  ticker: string;
  direction: "LONG" | "SHORT" | string;
  confidence_score?: number | null;
  confidence_basis?: "FACTOR_SCORE" | string | null;
  entry_price?: number | null;
  exit_price?: number | null;
  stop_loss?: number | null;
  target_price?: number | null;
  signal_entry_price?: number | null;
  outcome?: EodTradeOutcome | null;
  realized_pnl_pct?: number | null;
  realized_pnl_abs?: number | null;
  holding_duration_mins?: number | null;
  sector?: string | null;
  score?: number | null;
  qty?: number | null;
  deployed_capital?: number | null;
  risk_per_share?: number | null;
  tca?: EodTcaNode;
  efficiency?: EodEfficiencyNode;
  attribution?: EodAttributionNode;
  counterfactuals?: EodCounterfactual[];
  success_factors?: string[];
  failure_factors?: string[];
  root_cause?: string | null;
  false_positive?: boolean | null;
  timeline_events?: EodTimelineEvent[];
  factor_breakdown?: Record<string, unknown> | null;
};

export type EodExecutiveSummary = {
  overall_institutional_score?: number | null;
  total_trades?: number | null;
  win_trades?: number | null;
  loss_trades?: number | null;
  no_entry_trades?: number | null;
  win_rate_pct?: number | null;
  average_risk_reward?: number | null;
  net_strategy_return_pct?: number | null;
  capital_efficiency_pct?: number | null;
  expected_calibration_error?: number | null;
  brier_score?: number | null;
  market_regime?: EodMarketRegime | null;
  false_positive_count?: number | null;
};

export type EodStrategyProposal = {
  proposal_id: string;
  parameter_name: string;
  current_value?: string | null;
  proposed_value?: string | null;
  expected_pnl_uplift_pct?: number | null;
  confidence_interval?: string | null;
  supporting_evidence?: Record<string, unknown> | null;
  sample_count?: number | null;
  status: EodProposalStatus;
  audit_trail?: Array<{
    action: EodProposalReviewAction;
    reviewed_at: string;
    reviewer?: string | null;
    note?: string | null;
  }>;
};

export type EodPmCommentary = {
  executive_summary?: string | null;
  attribution_narrative?: string | null;
  execution_and_slippage_review?: string | null;
  actionable_directives?: string[] | null;
  source?: "LLM" | "DETERMINISTIC_FALLBACK" | string | null;
} | null;

export type EodMasterPayload = {
  analysis_date: string;
  generated_at?: string | null;
  status?: "OK" | "NO_PICKS" | "PARTIAL" | string;
  notes?: string[];
  schema_version?: string;
  executive_summary?: EodExecutiveSummary | null;
  scorecards?: EodTradeScorecard[];
  learning_proposals?: EodStrategyProposal[];
  pm_commentary?: EodPmCommentary;
  error?: string;
};

export type EodTimelinePayload = {
  ticker?: string;
  date?: string;
  interval?: string;
  candle_count?: number;
  candles?: EodTimelineCandle[];
  bars?: EodTimelineCandle[];
  ticks?: EodTimelineCandle[];
  events?: EodTimelineEvent[];
  error?: string | null;
};

async function readEodJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error) detail = String(body.error);
      else if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function unwrapList<T>(raw: unknown, keys: string[]): T[] {
  if (Array.isArray(raw)) return raw as T[];
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    for (const key of keys) {
      if (Array.isArray(obj[key])) return obj[key] as T[];
    }
  }
  return [];
}

export async function fetchEodDates(): Promise<string[]> {
  const res = await fetch("/api/eod/dates", { cache: "no-store" });
  const raw = await readEodJson<unknown>(res);
  if (Array.isArray(raw)) {
    return raw.map(String).filter(Boolean);
  }
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    for (const key of ["dates", "available_dates", "days"]) {
      if (Array.isArray(obj[key])) return (obj[key] as unknown[]).map(String).filter(Boolean);
    }
  }
  return [];
}

export type EodMonthDayPnl = {
  date: string;
  intradayPnl: number | null;
  swingPnl: number | null;
  combinedPnl: number | null;
  hasIntraday: boolean;
  hasSwing: boolean;
};

export type EodMonthPnl = {
  month: string;
  label: string;
  scope: "MTD" | "MONTH" | string;
  sessionCount: number;
  intradayPnl: number | null;
  swingPnl: number | null;
  combinedPnl: number | null;
  winDays: number;
  lossDays: number;
  flatDays: number;
  days: EodMonthDayPnl[];
};

export async function fetchEodMonthPnl(month: string): Promise<EodMonthPnl> {
  const res = await fetch(`/api/eod/month-pnl?month=${encodeURIComponent(month)}`, {
    cache: "no-store",
  });
  return readEodJson<EodMonthPnl>(res);
}

export async function fetchEodSummary(date: string): Promise<EodMasterPayload> {
  const res = await fetch(`/api/eod/summary/${encodeURIComponent(date)}`, { cache: "no-store" });
  return readEodJson<EodMasterPayload>(res);
}

export async function fetchEodScorecards(date: string): Promise<EodTradeScorecard[]> {
  const res = await fetch(`/api/eod/scorecards/${encodeURIComponent(date)}`, { cache: "no-store" });
  const raw = await readEodJson<unknown>(res);
  return unwrapList<EodTradeScorecard>(raw, ["scorecards", "items", "data"]);
}

export async function fetchEodProposals(date: string): Promise<EodStrategyProposal[]> {
  const res = await fetch(`/api/eod/proposals/${encodeURIComponent(date)}`, { cache: "no-store" });
  const raw = await readEodJson<unknown>(res);
  return unwrapList<EodStrategyProposal>(raw, [
    "learning_proposals",
    "proposals",
    "items",
    "data",
  ]);
}

export async function fetchEodTimeline(
  date: string,
  ticker: string
): Promise<EodTimelinePayload> {
  const res = await fetch(
    `/api/eod/timeline/${encodeURIComponent(date)}/${encodeURIComponent(ticker)}`,
    { cache: "no-store" }
  );
  return readEodJson<EodTimelinePayload>(res);
}

export async function fetchEodCounterfactuals(
  date: string,
  tradeId: string
): Promise<EodCounterfactual[]> {
  const res = await fetch(
    `/api/eod/counterfactuals/${encodeURIComponent(date)}/${encodeURIComponent(tradeId)}`,
    { cache: "no-store" }
  );
  const raw = await readEodJson<unknown>(res);
  return unwrapList<EodCounterfactual>(raw, ["counterfactuals", "items", "data", "scenarios"]);
}

export async function reviewEodProposal(
  date: string,
  proposalId: string,
  action: EodProposalReviewAction
): Promise<unknown> {
  const res = await fetch(
    `/api/eod/proposals/${encodeURIComponent(date)}/${encodeURIComponent(proposalId)}/review`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }
  );
  return readEodJson<unknown>(res);
}

export async function runEodAnalysis(
  date?: string,
  opts?: { force?: boolean; useLlm?: boolean }
): Promise<unknown> {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (opts?.force) params.set("force", "true");
  if (opts?.useLlm) params.set("use_llm", "true");
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`/api/eod/run${qs}`, {
    method: "POST",
    cache: "no-store",
    signal: AbortSignal.timeout(10 * 60 * 1_000),
  });
  return readEodJson<unknown>(res);
}

export type EodLlmStatus = {
  date: string;
  has_artifacts: boolean;
  pm_source?: string | null;
  llm_done: boolean;
  llm_available: boolean;
};

export async function fetchEodLlmStatus(date: string): Promise<EodLlmStatus> {
  const res = await fetch(`/api/eod/llm-status/${encodeURIComponent(date)}`, {
    cache: "no-store",
  });
  if (res.ok) {
    return readEodJson<EodLlmStatus>(res);
  }
  // Fallback when backend hasn't loaded llm-status yet — derive from summary cache
  try {
    const summary = await fetchEodSummary(date);
    const source = summary?.pm_commentary?.source ?? null;
    const llmDone = String(source || "").toUpperCase() === "LLM";
    return {
      date,
      has_artifacts: true,
      pm_source: source,
      llm_done: llmDone,
      llm_available: !llmDone,
    };
  } catch {
    return {
      date,
      has_artifacts: false,
      pm_source: null,
      llm_done: false,
      llm_available: false,
    };
  }
}

/** Once-per-day PM LLM. Safe to call again — returns cache if already done. */
export async function runEodPmLlmOnce(date?: string): Promise<{
  success?: boolean;
  skipped?: boolean;
  reason?: string;
  llm_used?: boolean;
  llm_done?: boolean;
  pm_source?: string | null;
  date?: string;
  detail?: string;
  commentary?: EodPmCommentary | null;
}> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  const res = await fetch(`/api/eod/pm-llm${qs}`, {
    method: "POST",
    cache: "no-store",
    signal: AbortSignal.timeout(10 * 60 * 1_000),
  });
  if (res.status === 404) {
    // Older backend without /pm-llm — use run?use_llm=true (still respects day cache)
    const fallback = (await runEodAnalysis(date, { useLlm: true, force: true })) as {
      skipped?: boolean;
      reason?: string;
      llm_used?: boolean;
      payload?: { pm_commentary?: { source?: string } };
    };
    const source = fallback?.payload?.pm_commentary?.source ?? null;
    return {
      success: true,
      skipped: Boolean(fallback?.skipped),
      reason: fallback?.reason || "run_use_llm_fallback",
      llm_used: Boolean(fallback?.llm_used),
      llm_done: String(source || "").toUpperCase() === "LLM",
      pm_source: source,
      date,
    };
  }
  return readEodJson(res);
}
