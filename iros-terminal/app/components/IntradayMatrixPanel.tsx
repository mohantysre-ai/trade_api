'use client';

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import type { SparkFlag } from '@/lib/market-api';
import { fetchNseSparkline } from '@/lib/market-api';

/* ── Smooth sparkline SVG with Catmull-Rom spline ─────────────────────── */
let intraSparkIdCounter = 0;
const SPARK_FLAGS: SparkFlag[] = ['1D', '1M', '1Y'];

/**
 * Convert Catmull-Rom spline points to smooth cubic bezier path.
 * Produces organic, flowing curves instead of jagged line segments.
 */
function catmullRomToBezier(points: readonly (readonly [number, number])[]): string {
  if (points.length < 2) return '';
  if (points.length === 2) {
    return `M ${points[0][0].toFixed(2)},${points[0][1].toFixed(2)} L ${points[1][0].toFixed(2)},${points[1][1].toFixed(2)}`;
  }
  const tension = 0.5;
  let d = `M ${points[0][0].toFixed(2)},${points[0][1].toFixed(2)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6 * tension * 2;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6 * tension * 2;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6 * tension * 2;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6 * tension * 2;
    d += ` C ${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

function StockSparklineSVG({ data, direction }: { data: number[]; direction?: string }) {
  const [id] = useState(() => `intra-spk-${++intraSparkIdCounter}`);
  const [glowId] = useState(() => `intra-glow-${++intraSparkIdCounter}`);
  if (!data || data.length < 2) return null;

  const first = data[0];
  const last = data[data.length - 1];
  const positive = last >= first;
  // For SHORT picks, invert the color logic: green when price is falling (good for shorts)
  const isShort = direction === 'SHORT';
  const color = isShort
    ? (last <= first ? '#10b981' : '#ef4444')
    : (positive ? '#10b981' : '#ef4444');

  const W = 120;
  const H = 40;
  const pad = 3;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad * 2);
    const y = pad + (1 - (v - min) / range) * (H - pad * 2);
    return [x, y] as const;
  });

  // Smooth curve via Catmull-Rom spline
  const pathD = catmullRomToBezier(points);
  const areaD = `${pathD} L ${points[points.length - 1][0].toFixed(2)},${H} L ${points[0][0].toFixed(2)},${H} Z`;
  const lastPt = points[points.length - 1];

  // Grid lines for reference
  const gridLines = [0.25, 0.5, 0.75].map((f) => pad + f * (H - pad * 2));

  return (
    <svg
      className="w-full h-10"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ filter: `drop-shadow(0 1px 2px ${color}20)` }}
    >
      <defs>
        {/* Rich multi-stop gradient for area fill */}
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="50%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
        {/* Glow filter for the stroke */}
        <filter id={glowId} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Subtle grid lines */}
      {gridLines.map((gy, i) => (
        <line
          key={`grid-${i}`}
          x1={pad}
          y1={gy}
          x2={W - pad}
          y2={gy}
          stroke="rgba(148,163,184,0.12)"
          strokeWidth="0.3"
          strokeDasharray="2,3"
        />
      ))}

      {/* Area fill with gradient */}
      <path d={areaD} fill={`url(#${id})`} />

      {/* Smooth line with glow */}
      <path
        d={pathD}
        stroke={color}
        strokeWidth="1.2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${glowId})`}
        className="sparkline-draw"
        style={{
          strokeDasharray: 300,
          strokeDashoffset: 0,
        }}
      />

      {/* Pulsing dot at the latest price point */}
      <circle cx={lastPt[0]} cy={lastPt[1]} r="2.5" fill={color} stroke="white" strokeWidth="1.2">
        <animate attributeName="r" values="2.5;3.5;2.5" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="1;0.7;1" dur="2s" repeatCount="indefinite" />
      </circle>

      {/* Outer pulse ring */}
      <circle cx={lastPt[0]} cy={lastPt[1]} r="2.5" fill="none" stroke={color} strokeWidth="0.8" opacity="0.5">
        <animate attributeName="r" values="2.5;6;2.5" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.5;0;0.5" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

function useStockSparklines(tickers: string[], flag: SparkFlag): Record<string, Record<SparkFlag, number[]>> {
  const [sparklines, setSparklines] = useState<Record<string, Record<SparkFlag, number[]>>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const missing = tickers.filter((t) => t && !fetchedRef.current.has(`${t}:${flag}`));
    if (missing.length === 0) return;

    let cancelled = false;

    const fetchAll = async () => {
      const results = await Promise.allSettled(
        missing.map(async (ticker) => {
          let sparkline: number[] = [];

          try {
            const res = await fetch(`/api/stock-sparkline?ticker=${encodeURIComponent(ticker)}&flag=${flag}`, { cache: 'no-store' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            sparkline = (data.sparkline as number[]) ?? [];
          } catch {
            try {
              sparkline = await fetchNseSparkline(ticker, flag);
            } catch {
              sparkline = [];
            }
          }

          return { ticker, sparkline };
        })
      );

      if (cancelled) return;

      const updates: Record<string, Record<SparkFlag, number[]>> = {};
      for (const result of results) {
        if (result.status === 'fulfilled' && result.value.sparkline.length >= 2) {
          if (!updates[result.value.ticker]) updates[result.value.ticker] = {} as Record<SparkFlag, number[]>;
          updates[result.value.ticker][flag] = result.value.sparkline;
          fetchedRef.current.add(`${result.value.ticker}:${flag}`);
        }
      }

      if (Object.keys(updates).length > 0) {
        console.debug('[IntradayMatrix spark] setSparklines tickers=', Object.keys(updates));
        setSparklines((prev) => {
          const next = { ...prev };
          for (const [tkr, flagData] of Object.entries(updates)) {
            next[tkr] = { ...(next[tkr] ?? {} as Record<SparkFlag, number[]>), ...flagData };
          }
          return next;
        });
      }
    };

    void fetchAll();

    return () => {
      cancelled = true;
    };
  }, [tickers, flag]);

  return sparklines;
}

function SparklineFlagSlider({ ticker, sparklines, onFlagChange, currentFlag, direction }: {
  ticker: string;
  sparklines: Record<SparkFlag, number[]>;
  onFlagChange: (flag: SparkFlag) => void;
  currentFlag: SparkFlag;
  direction?: string;
}) {
  const data = sparklines?.[currentFlag];
  const hasData = data && data.length >= 2;

  let changeLabel = '';
  let changeColor = 'text-slate-400';
  if (hasData) {
    const first = data![0];
    const last = data![data!.length - 1];
    const pct = ((last - first) / first) * 100;
    changeLabel = `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
    // For SHORT picks, a falling price (negative pct) is favorable
    const isShort = direction === 'SHORT';
    if (isShort) {
      changeColor = pct <= 0 ? 'text-emerald-600' : 'text-red-500';
    } else {
      changeColor = pct >= 0 ? 'text-emerald-600' : 'text-red-500';
    }
  }

  return (
    <div className="mb-1.5 relative z-10">
      <div
        className="rounded-lg overflow-hidden transition-all"
        style={{
          background: hasData
            ? 'linear-gradient(135deg, rgba(100,116,139,0.03) 0%, rgba(100,116,139,0.06) 100%)'
            : 'transparent',
        }}
      >
        {hasData ? (
          <StockSparklineSVG data={data!} direction={direction} />
        ) : (
          <div className="h-10 flex items-center justify-center">
            <div className="flex items-center gap-1">
              <div className="w-1 h-1 rounded-full bg-slate-300 animate-pulse" />
              <div className="w-1 h-1 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: '0.2s' }} />
              <div className="w-1 h-1 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: '0.4s' }} />
            </div>
          </div>
        )}
      </div>
      <div className="flex items-center justify-between mt-0.5">
        <div className="flex items-center gap-0.5">
          {SPARK_FLAGS.map((f) => (
            <button
              key={f}
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); onFlagChange(f); }}
              className={`px-1.5 py-0.5 rounded-md text-[7px] font-bold uppercase tracking-wider transition-all ${
                f === currentFlag
                  ? 'bg-slate-800 text-white shadow-sm'
                  : 'bg-transparent text-slate-400 hover:text-slate-600 hover:bg-slate-100'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        {hasData && (
          <span className={`text-[7px] font-bold tabular-nums ${changeColor}`}>{changeLabel}</span>
        )}
      </div>
    </div>
  );
}

/* ── lemonn types ─────────────────────────────────────────────────────── */
type LemonnRecommendation = {
  symbol: string;
  name: string;
  direction: string;
  buyPrice: number;
  sellPrice: number;
  stopLoss: number;
  riskPerShare: number;
  confidence: number | null;
  reasons: string[];
};

type LemonnResponse = {
  success: boolean;
  recommendations: LemonnRecommendation[];
  count: number;
  source: string;
  isMock?: boolean;
};

/* ── Dhan scanner types ────────────────────────────────────────────────── */
type DhanRecommendation = {
  symbol: string;
  name: string;
  direction: string;
  buyAbove: number;
  stopLoss: number;
  target1: number;
  target2: number;
  riskPerShare: number;
  rrT2: number;
  entryPrice: number;
  rsi?: number;
  deliveryPct?: number;
  score?: number;
  reasons?: string[];
};

type CapitalAllocation = {
    symbol: string;
    buyAbove: number;
    approxQty: number;
    deployedCapital: number;
    riskAmount: number;
};

/* ── Trade Outcome types ─────────────────────────────────────────────────── */
type TradeOutcome = {
    label: string;  // "TARGET 1 HIT", "TARGET 2 HIT", "STOP LOSS HIT", "PENDING"
    detail: string;
    hitLevel: "t1" | "t2" | "sl" | null;
    ltp: number;
    pctChange: number;
    resolvedAt: string | null;
};

type OutcomePick = {
    symbol: string;
    name: string;
    direction: string;
    entryPrice: number;
    stopLoss: number;
    target1: number;
    target2: number;
    currentPrice: number | null;
    outcome: TradeOutcome | null;
    sessionTs: number;
    updatedAt: string;
};

type DhanScannerResponse = {
  success: boolean;
  source: string;
  recommendations: DhanRecommendation[];
  shortRecommendations?: DhanRecommendation[];
  tradePlan: DhanRecommendation[];
  shortTradePlan?: DhanRecommendation[];
  capitalAllocation: CapitalAllocation[];
  shortCapitalAllocation?: CapitalAllocation[];
  totalCapital: number;
  totalRisk: number;
  shortTotalRisk?: number;
  scannedCount: number;
  passedCount: number;
  longPassedCount?: number;
  shortPassedCount?: number;
  error: string | null;
  isMock?: boolean;
};

/* ── API fetchers ──────────────────────────────────────────────────────── */

async function fetchLemonn(): Promise<LemonnResponse> {
  const res = await fetch('/api/intraday-matrix', { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data: LemonnResponse = await res.json();
  if (!data.success) throw new Error('API returned success=false');
  return data;
}

async function fetchDhanScanner(): Promise<DhanScannerResponse> {
  const res = await fetch('/api/dhan-scanner-matrix', { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data: DhanScannerResponse = await res.json();
  if (!data.success) throw new Error('API returned success=false');
  return data;
}

/* ── Trade Outcomes ─────────────────────────────────────────────────── */
type TradeOutcomesResponse = {
  long: OutcomePick[];
  short: OutcomePick[];
  updatedAt: string | null;
  error?: string;
  marketOpen?: boolean;
  sessionClosed?: boolean;
};

async function fetchTradeOutcomes(): Promise<TradeOutcomesResponse> {
  const res = await fetch('/api/trade-outcomes', { cache: 'no-store' });
  if (!res.ok) {
    return { long: [], short: [], updatedAt: null };
  }
  const data: TradeOutcomesResponse = await res.json();
  return data;
}

/* ── Live Prices (monitor-mode) ─────────────────────────────────────── */
type AlertRecord = {
  key: string;
  symbol: string;
  direction: 'LONG' | 'SHORT';
  hitLevel: 't1' | 't2' | 'sl';
  label: string;
  ltp: number;
  planDate: string;
  firedAt: string;
};

type LivePricesResponse = {
  long: Array<OutcomePick & { ltp?: number; ltpSource?: string; priceUpdatedAt?: string }>;
  short: Array<OutcomePick & { ltp?: number; ltpSource?: string; priceUpdatedAt?: string }>;
  updatedAt: string | null;
  snapshotUpdatedAt?: string;
  source: string;
  newAlerts?: AlertRecord[];
  error?: string;
  marketOpen?: boolean;
  sessionClosed?: boolean;
};

async function fetchLivePrices(): Promise<LivePricesResponse> {
  const res = await fetch('/api/live-prices', { cache: 'no-store' });
  if (!res.ok) {
    return { long: [], short: [], updatedAt: null, source: 'none' };
  }
  const data: LivePricesResponse = await res.json();
  return data;
}

/* ── Outcome Badge ───────────────────────────────────────────────────── */
function OutcomeBadge({ outcome }: { outcome: TradeOutcome | null }) {
  if (!outcome) {
    return <span className="text-[8px] text-slate-400">—</span>;
  }
  
  const baseClasses = "inline-flex items-center px-1.5 py-0.5 rounded-full text-[8px] font-bold uppercase tracking-wider";
  const hitLevel = outcome.hitLevel;

  if (outcome.label === "NOT TRIGGERED") {
    return (
      <span className={`${baseClasses} bg-slate-200 text-slate-500 border border-slate-400`}>
        <span className="w-1 h-1 rounded-full bg-slate-500 mr-1" />
        NOT TRIGGERED
      </span>
    );
  }

  if (hitLevel === "t2") {
    return (
      <span className={`${baseClasses} bg-emerald-100 text-emerald-700 border border-emerald-300 animate-pulse`}>
        <span className="w-1 h-1 rounded-full bg-emerald-500 mr-1" />
        TARGET 2 HIT
      </span>
    );
  }
  if (hitLevel === "t1") {
    return (
      <span className={`${baseClasses} bg-blue-100 text-blue-700 border border-blue-300`}>
        <span className="w-1 h-1 rounded-full bg-blue-500 mr-1" />
        TARGET 1 HIT
      </span>
    );
  }
  if (hitLevel === "sl") {
    return (
      <span className={`${baseClasses} bg-red-100 text-red-700 border border-red-300`}>
        <span className="w-1 h-1 rounded-full bg-red-500 mr-1" />
        STOP LOSS HIT
      </span>
    );
  }
  // PENDING
  return (
    <span className={`${baseClasses} bg-slate-100 text-slate-600 border border-slate-300`}>
      <span className="w-1 h-1 rounded-full bg-slate-400 mr-1 animate-pulse" />
      PENDING
    </span>
  );
}

function DirectionBadge({ dir }: { dir: string }) {
  const isBuy = dir === 'BUY';
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[8px] font-black uppercase tracking-wider ${
      isBuy ? 'bg-emerald-100 text-emerald-700 border border-emerald-300'
            : 'bg-red-100 text-red-700 border border-red-300'}`}>
      <span className={`w-1 h-1 rounded-full ${isBuy ? 'bg-emerald-500' : 'bg-red-500'} animate-pulse`} />
      {dir}
    </span>
  );
}

/* ── Loading spinner ───────────────────────────────────────────────────── */
function LoadingSpinner({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-slate-400">
      <div className="w-10 h-10 rounded-full border-2 border-violet-300 border-t-violet-600 animate-spin mb-3" />
      <span className="text-[10px] uppercase tracking-wider font-bold">{label}</span>
    </div>
  );
}

/* ── MAIN COMPONENT ────────────────────────────────────────────────────── */

export default function IntradayMatrixPanel() {
  /* lemonn state */
  const [lemonnData, setLemonnData] = useState<LemonnResponse | null>(null);
  const [lemonnLoading, setLemonnLoading] = useState(true);
  const [lemonnError, setLemonnError] = useState<string | null>(null);

  /* dhan state */
  const [dhanData, setDhanData] = useState<DhanScannerResponse | null>(null);
  const [dhanLoading, setDhanLoading] = useState(true);
  const [dhanError, setDhanError] = useState<string | null>(null);

  /* trade outcomes state */
  const [outcomesData, setOutcomesData] = useState<TradeOutcomesResponse | null>(null);
  const [outcomesLoading, setOutcomesLoading] = useState(true);
  const [outcomesTime, setOutcomesTime] = useState('');

  /* live prices (monitor mode) state */
  const [livePricesData, setLivePricesData] = useState<LivePricesResponse | null>(null);
  const [monitorMode, setMonitorMode] = useState(false);
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [alertBanner, setAlertBanner] = useState<AlertRecord | null>(null);
  const [marketOpen, setMarketOpen] = useState(true);
  const [sessionClosed, setSessionClosed] = useState(false);
  const sessionClosedRef = useRef(false);
  const prevOutcomeRef = useRef<Record<string, string | null>>({});

  /* last fetch times */
  const [lemonnTime, setLemonnTime] = useState('');
  const [dhanTime, setDhanTime] = useState('');

  const loadLemonn = useCallback(async () => {
    try {
      const data = await fetchLemonn();
      setLemonnData(data);
      setLemonnTime(new Date().toLocaleTimeString('en-IN', { hour12: false }));
      setLemonnError(null);
    } catch (err) {
      setLemonnError(err instanceof Error ? err.message : 'Feed unavailable');
    } finally {
      setLemonnLoading(false);
    }
  }, []);

    const loadDhan = useCallback(async () => {
    try {
      const data = await fetchDhanScanner();
      setDhanData(data);
      setDhanTime(new Date().toLocaleTimeString('en-IN', { hour12: false }));
      setDhanError(null);
    } catch (err) {
      setDhanError(err instanceof Error ? err.message : 'Feed unavailable');
    } finally {
      setDhanLoading(false);
    }
  }, []);

  const loadOutcomes = useCallback(async () => {
    try {
      const data = await fetchTradeOutcomes();
      setOutcomesData(data);
      setOutcomesTime(new Date().toLocaleTimeString('en-IN', { hour12: false }));
    } catch {
      // Outcomes may be empty on first load, that's OK
    } finally {
      setOutcomesLoading(false);
    }
  }, []);

  /* Live prices (monitor mode) */
  const loadLivePrices = useCallback(async () => {
    try {
      const data = await fetchLivePrices();
      if (data.source === 'none' || ((data.long?.length ?? 0) === 0 && (data.short?.length ?? 0) === 0)) {
        // No fixed plan — fall back to normal mode
        setMonitorMode(false);
        return;
      }
      setMonitorMode(true);
      setLivePricesData(data);

      // Track market session state (used to halt polling after close)
      const closed = Boolean(data.sessionClosed);
      const open = data.marketOpen !== false;
      setMarketOpen(open);
      setSessionClosed(closed);
      sessionClosedRef.current = closed;
      // Detect new alerts (transition from PENDING → t1/t2/sl)
      const newAlerts = data.newAlerts ?? [];
      if (newAlerts.length > 0) {
        setAlerts((prev) => [...newAlerts, ...prev].slice(0, 20));
        // Show a banner for the most recent
        setAlertBanner(newAlerts[newAlerts.length - 1]);
        // Auto-dismiss after 8 seconds
        window.setTimeout(() => setAlertBanner(null), 8000);
      }

      // Track outcome transitions for future polling cycles
      const all = [...(data.long ?? []), ...(data.short ?? [])];
      for (const p of all) {
        const key = `${p.symbol}:${p.direction}`;
        const level = p.outcome?.hitLevel ?? null;
        prevOutcomeRef.current[key] = level;
      }
    } catch {
      // Keep previous state on failure
    }
  }, []);

  const dismissAlert = useCallback((idx: number) => {
    setAlerts((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      await Promise.all([loadLemonn(), loadDhan(), loadOutcomes()]);
      // Attempt to enter monitor mode (uses fixed plan if available)
      await loadLivePrices();
    };
    void init();

    // Standard 2-min refresh for scanner/lemonn feeds
    const slowId = window.setInterval(() => {
      if (!cancelled) {
        loadLemonn();
        loadDhan();
        loadOutcomes();
      }
    }, 120_000);

    // Fast monitor-mode poll (only reads local snapshot, no external calls).
    // Halt once the session has closed so we stop recalculating on stale prices.
    const fastId = window.setInterval(() => {
      if (!cancelled && !sessionClosedRef.current) {
        loadLivePrices();
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(slowId);
      window.clearInterval(fastId);
    };
  }, [loadLemonn, loadDhan, loadOutcomes, loadLivePrices]);

  /* Collect all tickers for sparkline fetching — includes BOTH long and
     short picks so sparklines render on sell-side cards too */
  const allTickers = useMemo(() => {
    const tickers: string[] = [];
    if (lemonnData?.recommendations) {
      for (const r of lemonnData.recommendations) tickers.push(r.symbol);
    }
    if (dhanData?.recommendations) {
      for (const r of dhanData.recommendations) tickers.push(r.symbol);
    }
    if (dhanData?.shortRecommendations) {
      for (const r of dhanData.shortRecommendations) tickers.push(r.symbol);
    }
    return tickers;
  }, [lemonnData, dhanData]);

  /* Per-ticker flag state (default 1M) */
  const [tickerFlags, setTickerFlags] = useState<Record<string, SparkFlag>>({});
  const getFlag = (ticker: string): SparkFlag => tickerFlags[ticker] ?? '1D';
  const setFlag = (ticker: string, flag: SparkFlag) => setTickerFlags((prev) => ({ ...prev, [ticker]: flag }));

  /* Fetch sparkline data for all tickers x all flags */
  const stockSparklines1D = useStockSparklines(allTickers, '1D');
  const stockSparklines1M = useStockSparklines(allTickers, '1M');
  const stockSparklines1Y = useStockSparklines(allTickers, '1Y');

  /* Outcome lookup helper */
  const getOutcomeForSymbol = useCallback((symbol: string, direction: 'LONG' | 'SHORT' = 'LONG'): TradeOutcome | null => {
    const key = symbol.toUpperCase();
    const picks = direction === 'SHORT' 
      ? outcomesData?.short ?? [] 
      : outcomesData?.long ?? [];
    const pick = picks.find(p => p.symbol.toUpperCase() === key);
    return pick?.outcome ?? null;
  }, [outcomesData]);

  const allSparklines = useMemo(() => {
    const merged: Record<string, Record<SparkFlag, number[]>> = {};
    for (const t of allTickers) {
      merged[t] = {
        '1D': stockSparklines1D[t]?.['1D'] ?? [],
        '1M': stockSparklines1M[t]?.['1M'] ?? [],
        '1Y': stockSparklines1Y[t]?.['1Y'] ?? [],
      };
    }
    return merged;
  }, [allTickers, stockSparklines1D, stockSparklines1M, stockSparklines1Y]);

  /* ── RENDER ───────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-4">
      {/* ── ALERT BANNER ─────────────────────────────────────────────────── */}
      {alertBanner && (
        <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl shadow-2xl border-2 animate-pulse ${
          alertBanner.hitLevel === 'sl'
            ? 'bg-red-600 border-red-800 text-white'
            : 'bg-emerald-600 border-emerald-800 text-white'
        }`}>
          <div className="flex items-center gap-3">
            <span className="text-[14px] font-black uppercase tracking-wider">
              {alertBanner.symbol} — {alertBanner.label}
            </span>
            <span className="text-[10px] opacity-90">LTP ₹{alertBanner.ltp.toFixed(2)}</span>
            <button onClick={() => setAlertBanner(null)} className="ml-2 text-white/80 hover:text-white text-[14px] font-bold">×</button>
          </div>
        </div>
      )}

      {/* ── MONITOR MODE INDICATOR ──────────────────────────────────────── */}
      {monitorMode && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900 text-white text-[9px] font-semibold uppercase tracking-wider">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          MONITOR MODE — Fixed plan active · Live prices every 2s · No external API calls
          {livePricesData?.snapshotUpdatedAt && (
            <span className="text-slate-400 ml-1">
              (snapshot @{new Date(livePricesData.snapshotUpdatedAt).toLocaleTimeString('en-IN', { hour12: false })})
            </span>
          )}
        </div>
      )}

      {/* ── RECENT ALERTS ───────────────────────────────────────────────── */}
      {alerts.length > 0 && (
        <div className="flex flex-col gap-1">
          {alerts.map((a, idx) => (
            <div key={`alert-${idx}`} className={`flex items-center justify-between px-3 py-1.5 rounded-lg border text-[10px] ${
              a.hitLevel === 'sl' ? 'bg-red-50 border-red-200 text-red-700' : 'bg-emerald-50 border-emerald-200 text-emerald-700'
            }`}>
              <span className="font-bold uppercase tracking-wider">
                {a.symbol} ({a.direction}) — {a.label}
              </span>
              <span className="text-slate-500">
                {new Date(a.firedAt).toLocaleTimeString('en-IN', { hour12: false })}
              </span>
              <button onClick={() => dismissAlert(idx)} className="text-slate-400 hover:text-slate-600">×</button>
            </div>
          ))}
        </div>
      )}

      {/* ═══════════════════ UPPER PANEL — LEMOON ═══════════════════ */}
      <div className="bg-gradient-to-br from-white via-purple-50/10 to-white border border-slate-300 rounded-xl p-4 shadow-lg overflow-auto">
        {/* Header */}
        <div className="relative mb-3">
          <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-violet-500 via-purple-500 to-fuchsia-500 rounded-t-xl" />
          <div className="flex items-center justify-between pt-1">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-violet-600 to-purple-700 flex items-center justify-center shadow-lg">
                <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                </svg>
              </div>
              <div>
                <h3 className="text-[11px] font-black text-slate-900 uppercase tracking-wider">LEMOON CO.IN — 10 INTRADAY PICKS</h3>
                <p className="text-[7px] text-slate-500">
                  {lemonnData?.source ?? 'lemonn.co.in'}
                  {lemonnData?.isMock && <span className="ml-1 text-amber-500 font-bold">(mock fallback)</span>}
                  {lemonnTime && <span className="ml-1 text-slate-400">@{lemonnTime}</span>}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="px-1.5 py-0.5 rounded-lg bg-gradient-to-r from-violet-100 to-purple-50 border border-violet-200">
                <span className="text-[8px] text-violet-700 font-semibold">{lemonnData?.count ?? 0} picks</span>
              </div>
              <button onClick={loadLemonn} className="px-2 py-0.5 rounded-lg bg-slate-100 border border-slate-200 text-[8px] text-slate-600 font-semibold uppercase tracking-wider hover:bg-slate-200 transition-colors">
                Refresh
              </button>
            </div>
          </div>
        </div>

        {lemonnError && (
          <div className="mb-3 p-2 rounded-lg bg-red-50 border border-red-200 text-[9px] text-red-600">{lemonnError}</div>
        )}

        {lemonnLoading && <LoadingSpinner label="Fetching lemonn.co.in..." />}

        {!lemonnLoading && lemonnData?.recommendations && lemonnData.recommendations.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
            {lemonnData.recommendations.map((rec, idx) => {
              const isBuy = rec.direction === 'BUY';
              return (
                <a key={`lm-${rec.symbol}-${idx}`}
                  href={`https://lemonn.co.in/stocks/${encodeURIComponent(rec.symbol.toLowerCase())}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-2.5 shadow-sm hover:shadow-md transition-all group cursor-pointer block"
                  style={{ borderLeft: isBuy ? '3px solid #10b981' : '3px solid #ef4444' }}>
                  <div className="absolute -top-4 -right-4 w-12 h-12 rounded-full opacity-15 blur-2xl"
                    style={{ backgroundColor: isBuy ? '#10b981' : '#ef4444' }} />
                  <div className="flex items-center justify-between mb-1.5 relative z-10">
                    <span className="text-[12px] font-black text-slate-900 font-mono">{rec.symbol}</span>
                    <DirectionBadge dir={rec.direction} />
                  </div>
                  <p className="text-[8px] text-slate-500 mb-1 truncate relative z-10">{rec.name}</p>
                  <SparklineFlagSlider
                    ticker={rec.symbol}
                    sparklines={allSparklines[rec.symbol] ?? ({} as Record<SparkFlag, number[]>)}
                    currentFlag={getFlag(rec.symbol)}
                    onFlagChange={(f) => setFlag(rec.symbol, f)}
                  />
                  <div className="space-y-1 text-[8px] relative z-10">
                    <div className="flex justify-between"><span className="text-slate-400">Buy</span><span className="font-bold text-emerald-600">₹{rec.buyPrice.toFixed(2)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Sell</span><span className="font-bold text-blue-600">₹{rec.sellPrice.toFixed(2)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Stop Loss</span><span className="font-bold text-red-500">₹{rec.stopLoss.toFixed(2)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Risk/Sh</span><span className="font-bold text-slate-700">₹{rec.riskPerShare.toFixed(2)}</span></div>
                  </div>
                </a>
              );
            })}
          </div>
        )}

        {!lemonnLoading && !lemonnError && (!lemonnData?.recommendations || lemonnData.recommendations.length === 0) && (
          <div className="flex flex-col items-center justify-center py-8 text-slate-400">
            <span className="text-[10px] uppercase tracking-wider font-semibold">No lemonn signals today</span>
          </div>
        )}
      </div>

      {/* ═══════════════════ LOWER PANEL — DHAN ScanX + Trade Plan ══════════ */}
      <div className="bg-gradient-to-br from-white via-teal-50/10 to-white border border-slate-300 rounded-xl p-4 shadow-lg overflow-auto">
        {/* Header */}
        <div className="relative mb-3">
          <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 rounded-t-xl" />
          <div className="flex items-center justify-between pt-1">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-emerald-600 to-teal-700 flex items-center justify-center shadow-lg">
                <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7M4 7h16M4 7l2-3h12l2 3" />
                </svg>
              </div>
              <div>
                <h3 className="text-[11px] font-black text-slate-900 uppercase tracking-wider">
                  DHAN ScanX → FEED SCANNER — TOP 10 + TRADE PLAN
                </h3>
                <p className="text-[7px] text-slate-500">
                  {dhanData?.source ?? 'dhan-scanx'}
                  {dhanData?.isMock && <span className="ml-1 text-amber-500 font-bold">(mock fallback — Dhan API unreachable)</span>}
                  &nbsp;·&nbsp;Scanned {dhanData?.scannedCount ?? 0} stocks
                  &nbsp;·&nbsp;<span className="text-emerald-600 font-semibold">LONG {dhanData?.longPassedCount ?? 0}</span>
                  &nbsp;/&nbsp;<span className="text-rose-600 font-semibold">SHORT {dhanData?.shortPassedCount ?? 0}</span>
                  {dhanTime && <span className="ml-1 text-slate-400">@{dhanTime}</span>}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="px-1.5 py-0.5 rounded-lg bg-gradient-to-r from-emerald-100 to-teal-50 border border-emerald-200">
                <span className="text-[8px] text-emerald-700 font-semibold">{dhanData?.recommendations?.length ?? 0} stocks</span>
              </div>
              <button onClick={loadDhan} className="px-2 py-0.5 rounded-lg bg-slate-100 border border-slate-200 text-[8px] text-slate-600 font-semibold uppercase tracking-wider hover:bg-slate-200 transition-colors">
                Refresh
              </button>
            </div>
          </div>
        </div>

        {dhanError && (
          <div className="mb-3 p-2 rounded-lg bg-red-50 border border-red-200 text-[9px] text-red-600">{dhanError}</div>
        )}

        {dhanLoading && <LoadingSpinner label="Fetching Dhan ScanX & feed_scanner..." />}

        {!dhanLoading && dhanData && ((dhanData.recommendations?.length ?? 0) > 0 || (dhanData.shortRecommendations?.length ?? 0) > 0) && (
          <>
            {/* ── TOP 10 SCANNER PICKS ─────────────────────────────────── */}
            <div className="mb-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">
                  TOP {dhanData.recommendations.length} SCANNER PICKS
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
                {dhanData.recommendations.map((rec, idx) => {
                  const isBuy = rec.direction === 'LONG';
                  return (
                    <a key={`dh-${rec.symbol}-${idx}`}
                      href={`https://lemonn.co.in/stocks/${encodeURIComponent(rec.symbol.toLowerCase())}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-2.5 shadow-sm hover:shadow-md transition-all group cursor-pointer block"
                      style={{ borderLeft: isBuy ? '3px solid #10b981' : '3px solid #ef4444' }}>
                      <div className="absolute -top-4 -right-4 w-12 h-12 rounded-full opacity-15 blur-2xl"
                        style={{ backgroundColor: isBuy ? '#10b981' : '#ef4444' }} />
                      <div className="flex items-center justify-between mb-1.5 relative z-10">
                        <span className="text-[12px] font-black text-slate-900 font-mono">{rec.symbol}</span>
                        {rec.score != null && (
                          <span className="text-[8px] font-bold text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                            {rec.score.toFixed(0)}
                          </span>
                        )}
                      </div>
                      <p className="text-[8px] text-slate-500 mb-1 truncate relative z-10">{rec.name}</p>
                      <SparklineFlagSlider
                        ticker={rec.symbol}
                        sparklines={allSparklines[rec.symbol] ?? ({} as Record<SparkFlag, number[]>)}
                        currentFlag={getFlag(rec.symbol)}
                        onFlagChange={(f) => setFlag(rec.symbol, f)}
                        direction="LONG"
                      />
                      <div className="space-y-1 text-[8px] relative z-10">
                        <div className="flex justify-between"><span className="text-slate-400">Buy Above</span><span className="font-bold text-emerald-600">{rec.buyAbove?.toFixed(2) ?? '—'}</span></div>
                        <div className="flex justify-between"><span className="text-slate-400">T1 / T2</span><span className="font-bold text-blue-600">{rec.target1?.toFixed(2) ?? '—'} / {rec.target2?.toFixed(2) ?? '—'}</span></div>
                        <div className="flex justify-between"><span className="text-slate-400">Stop Loss</span><span className="font-bold text-red-500">{rec.stopLoss?.toFixed(2) ?? '—'}</span></div>
                        <div className="flex justify-between"><span className="text-slate-400">Risk/Sh</span><span className="font-bold text-slate-700">₹{rec.riskPerShare?.toFixed(2) ?? '—'}</span></div>
                        <div className="flex justify-between"><span className="text-slate-400">R:R (T2)</span><span className="font-bold text-slate-700">~{rec.rrT2?.toFixed(1) ?? '—'}</span></div>
                      </div>
                    </a>
                  );
                })}
              </div>
            </div>

            {/* ── TOP SHORT / SELL PICKS ───────────────────────────────── */}
            {dhanData?.shortRecommendations && dhanData.shortRecommendations.length > 0 && (
              <div className="mb-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                  <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">
                    TOP {dhanData.shortRecommendations.length} SHORT / SELL PICKS
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
                  {dhanData.shortRecommendations.map((rec, idx) => {
                    const isBuy = rec.direction === 'LONG';
                    return (
                      <a key={`dh-s-${rec.symbol}-${idx}`}
                        href={`https://lemonn.co.in/stocks/${encodeURIComponent(rec.symbol.toLowerCase())}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-2.5 shadow-sm hover:shadow-md transition-all group cursor-pointer block"
                        style={{ borderLeft: isBuy ? '3px solid #10b981' : '3px solid #ef4444' }}>
                        <div className="absolute -top-4 -right-4 w-12 h-12 rounded-full opacity-15 blur-2xl"
                          style={{ backgroundColor: isBuy ? '#10b981' : '#ef4444' }} />
                        <div className="flex items-center justify-between mb-1.5 relative z-10">
                          <span className="text-[12px] font-black text-slate-900 font-mono">{rec.symbol}</span>
                          {rec.score != null && (
                            <span className="text-[8px] font-bold text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                              {rec.score.toFixed(0)}
                            </span>
                          )}
                        </div>
                        <p className="text-[8px] text-slate-500 mb-1 truncate relative z-10">{rec.name}</p>
                        <SparklineFlagSlider
                          ticker={rec.symbol}
                          sparklines={allSparklines[rec.symbol] ?? ({} as Record<SparkFlag, number[]>)}
                          currentFlag={getFlag(rec.symbol)}
                          onFlagChange={(f) => setFlag(rec.symbol, f)}
                          direction="SHORT"
                        />
                        <div className="space-y-1 text-[8px] relative z-10">
                          <div className="flex justify-between"><span className="text-slate-400">Sell Below</span><span className="font-bold text-rose-600">{rec.buyAbove?.toFixed(2) ?? '—'}</span></div>
                          <div className="flex justify-between"><span className="text-slate-400">T1 / T2</span><span className="font-bold text-blue-600">{rec.target1?.toFixed(2) ?? '—'} / {rec.target2?.toFixed(2) ?? '—'}</span></div>
                          <div className="flex justify-between"><span className="text-slate-400">Stop Loss</span><span className="font-bold text-red-500">{rec.stopLoss?.toFixed(2) ?? '—'}</span></div>
                          <div className="flex justify-between"><span className="text-slate-400">Risk/Sh</span><span className="font-bold text-slate-700">₹{rec.riskPerShare?.toFixed(2) ?? '—'}</span></div>
                          <div className="flex justify-between"><span className="text-slate-400">R:R (T2)</span><span className="font-bold text-slate-700">~{rec.rrT2?.toFixed(1) ?? '—'}</span></div>
                        </div>
                      </a>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── TRADE PLAN — from persistent picks (stable across the day) ── */}
            {(() => {
              // Monitor mode uses livePricesData (fresh every 2s, no external calls)
              const planLong = monitorMode && livePricesData ? (livePricesData.long || []) : (outcomesData?.long || []);
              const planShort = monitorMode && livePricesData ? (livePricesData.short || []) : (outcomesData?.short || []);
              const planTime = monitorMode && livePricesData?.updatedAt
                ? new Date(livePricesData.updatedAt).toLocaleTimeString('en-IN', { hour12: false })
                : outcomesTime;
              const showPlan = (planLong.length > 0 || planShort.length > 0);

              if (!showPlan) return null;

              return (
                <>
                  {sessionClosed && (
                    <div className="mb-3 flex items-center gap-2 rounded-md bg-slate-100 border border-slate-300 px-3 py-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                      <span className="text-[11px] uppercase tracking-wider text-slate-600 font-bold">
                        Market Closed — Session Finalized
                      </span>
                      <span className="text-[9px] text-slate-500 ml-1">
                        Unfilled picks marked NOT TRIGGERED. Monitoring halted.
                      </span>
                    </div>
                  )}
                  <div className="mb-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${monitorMode ? (sessionClosed ? 'bg-slate-500' : 'bg-emerald-500') : 'bg-amber-500'}`} />
                      <span className="text-[12px] uppercase tracking-wider text-slate-500 font-bold">
                        TRADE PLAN — ₹5,00,000 DEPLOYMENT {monitorMode && '(LIVE MONITOR)'}
                      </span>
                      <span className="text-[9px] text-slate-400 ml-2">(updated @{planTime || '—'})</span>
                    </div>

                    {/* Trade plan table — LONG */}
                    <div className="overflow-x-auto">
                      <table className="w-full text-[12px] border-collapse">
                        <thead>
                          <tr className="bg-slate-100 text-slate-600">
                            <th className="p-1.5 text-left font-bold uppercase tracking-wider">Stock</th>
                            <th className="p-1.5 text-right font-bold uppercase tracking-wider">LTP</th>
                            <th className="p-1.5 text-right font-bold uppercase tracking-wider">Buy Above</th>
                            <th className="p-1.5 text-right font-bold uppercase tracking-wider">Stop Loss</th>
                            <th className="p-1.5 text-right font-bold uppercase tracking-wider">Target 1</th>
                            <th className="p-1.5 text-right font-bold uppercase tracking-wider">Target 2</th>
                            <th className="p-1.5 text-right font-bold uppercase tracking-wider">Risk/Sh</th>
                            <th className="p-1.5 text-right font-bold uppercase tracking-wider">R:R T2</th>
                            <th className="p-1.5 text-center font-bold uppercase tracking-wider">Outcome</th>
                          </tr>
                        </thead>
                        <tbody>
                          {planLong.slice(0, 5).map((tp, idx) => (
                            <tr key={`lp-long-${tp.symbol}-${idx}`} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer">
                              <td className="p-1.5 font-bold text-slate-900">
                                <a href={`https://lemonn.co.in/stocks/${encodeURIComponent(tp.symbol.toLowerCase())}`} target="_blank" rel="noopener noreferrer" className="hover:text-indigo-600 transition-colors">{tp.symbol}</a>
                              </td>
                              <td className="p-1.5 text-right font-mono text-slate-900 font-bold">{tp.ltp != null ? tp.ltp.toFixed(2) : '—'}</td>
                              <td className="p-1.5 text-right font-mono text-emerald-600 font-bold">{tp.entryPrice?.toFixed(2) ?? '—'}</td>
                              <td className="p-1.5 text-right font-mono text-red-500 font-bold">{tp.stopLoss?.toFixed(2) ?? '—'}</td>
                              <td className="p-1.5 text-right font-mono text-blue-600">{tp.target1?.toFixed(2) ?? '—'}</td>
                              <td className="p-1.5 text-right font-mono text-blue-600 font-bold">{tp.target2?.toFixed(2) ?? '—'}</td>
                              <td className="p-1.5 text-right font-mono text-slate-600">₹{tp.riskPerShare?.toFixed(2) ?? '—'}</td>
                              <td className="p-1.5 text-right font-mono text-slate-700 font-bold">~{tp.rrT2?.toFixed(1) ?? '—'}</td>
                              <td className="p-1.5 text-center">
                                <OutcomeBadge outcome={tp.outcome} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* ── SHORT TRADE PLAN — from persistent picks (stable across the day) ── */}
                  {planShort.length > 0 && (
                    <div className="mb-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span className={`w-1.5 h-1.5 rounded-full ${monitorMode ? 'bg-emerald-500' : 'bg-rose-500'} animate-pulse`} />
                        <span className="text-[12px] uppercase tracking-wider text-slate-500 font-bold">
                          SHORT TRADE PLAN — SELL BOOK (₹5,00,000 DEPLOYMENT) {monitorMode && '(LIVE MONITOR)'}
                        </span>
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-[12px] border-collapse">
                          <thead>
                            <tr className="bg-rose-50 text-slate-600">
                              <th className="p-1.5 text-left font-bold uppercase tracking-wider">Stock</th>
                              <th className="p-1.5 text-right font-bold uppercase tracking-wider">LTP</th>
                              <th className="p-1.5 text-right font-bold uppercase tracking-wider">Sell At</th>
                              <th className="p-1.5 text-right font-bold uppercase tracking-wider">Stop Loss</th>
                              <th className="p-1.5 text-right font-bold uppercase tracking-wider">Target 1</th>
                              <th className="p-1.5 text-right font-bold uppercase tracking-wider">Target 2</th>
                              <th className="p-1.5 text-right font-bold uppercase tracking-wider">Risk/Sh</th>
                              <th className="p-1.5 text-right font-bold uppercase tracking-wider">R:R T2</th>
                              <th className="p-1.5 text-center font-bold uppercase tracking-wider">Outcome</th>
                            </tr>
                          </thead>
                          <tbody>
                            {planShort.slice(0, 5).map((tp, idx) => (
                              <tr key={`lp-short-${tp.symbol}-${idx}`} className="border-b border-slate-100 hover:bg-rose-50 cursor-pointer">
                                <td className="p-1.5 font-bold text-slate-900">
                                  <a href={`https://lemonn.co.in/stocks/${encodeURIComponent(tp.symbol.toLowerCase())}`} target="_blank" rel="noopener noreferrer" className="hover:text-indigo-600 transition-colors">{tp.symbol}</a>
                                </td>
                                <td className="p-1.5 text-right font-mono text-slate-900 font-bold">{tp.ltp != null ? tp.ltp.toFixed(2) : '—'}</td>
                                <td className="p-1.5 text-right font-mono text-rose-600 font-bold">{tp.entryPrice?.toFixed(2) ?? '—'}</td>
                                <td className="p-1.5 text-right font-mono text-red-500 font-bold">{tp.stopLoss?.toFixed(2) ?? '—'}</td>
                                <td className="p-1.5 text-right font-mono text-blue-600">{tp.target1?.toFixed(2) ?? '—'}</td>
                                <td className="p-1.5 text-right font-mono text-blue-600 font-bold">{tp.target2?.toFixed(2) ?? '—'}</td>
                                <td className="p-1.5 text-right font-mono text-slate-600">₹{tp.riskPerShare?.toFixed(2) ?? '—'}</td>
                                <td className="p-1.5 text-right font-mono text-slate-700 font-bold">~{tp.rrT2?.toFixed(1) ?? '—'}</td>
                                <td className="p-1.5 text-center">
                                  <OutcomeBadge outcome={tp.outcome} />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              );
            })()}

            {/* ── SHORT CAPITAL ALLOCATION TABLE ────────────────────────── */}
            {dhanData?.shortCapitalAllocation && dhanData.shortCapitalAllocation.length > 0 && (
              <div className="mb-3">
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                  <span className="text-[12px] uppercase tracking-wider text-slate-500 font-bold">
                    SHORT CAPITAL ALLOCATION (~₹1,00,000 per stock)
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-[12px] border-collapse">
                    <thead>
                      <tr className="bg-rose-50 text-slate-600">
                        <th className="p-1.5 text-left font-bold uppercase tracking-wider">Stock</th>
                        <th className="p-1.5 text-right font-bold uppercase tracking-wider">Sell Price</th>
                        <th className="p-1.5 text-right font-bold uppercase tracking-wider">Approx Qty</th>
                        <th className="p-1.5 text-right font-bold uppercase tracking-wider">Deployed Capital</th>
                        <th className="p-1.5 text-right font-bold uppercase tracking-wider">Risk (SL hit)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dhanData.shortCapitalAllocation.map((ca, idx) => (
                        <tr key={`sca-${ca.symbol}-${idx}`} className="border-b border-slate-100 hover:bg-rose-50 cursor-pointer">
                          <td className="p-1.5 font-bold text-slate-900">
                            <a href={`https://lemonn.co.in/stocks/${encodeURIComponent(ca.symbol.toLowerCase())}`} target="_blank" rel="noopener noreferrer" className="hover:text-indigo-600 transition-colors">{ca.symbol}</a>
                          </td>
                          <td className="p-1.5 text-right font-mono text-slate-600">₹{ca.buyAbove?.toFixed(2) ?? '—'}</td>
                          <td className="p-1.5 text-right font-mono text-slate-700 font-bold">{ca.approxQty?.toLocaleString('en-IN') ?? '—'}</td>
                          <td className="p-1.5 text-right font-mono text-rose-600 font-bold">₹{ca.deployedCapital?.toLocaleString('en-IN', { minimumFractionDigits: 2 }) ?? '—'}</td>
                          <td className="p-1.5 text-right font-mono text-red-500">₹{ca.riskAmount?.toLocaleString('en-IN', { minimumFractionDigits: 2 }) ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="bg-rose-100 font-bold text-slate-900">
                        <td className="p-1.5 uppercase tracking-wider text-[12px]">TOTAL</td>
                        <td className="p-1.5"></td>
                        <td className="p-1.5"></td>
                        <td className="p-1.5 text-right font-mono text-rose-700 text-[12px]">
                          ≈ ₹{dhanData.shortCapitalAllocation.reduce((s, c) => s + (c.deployedCapital ?? 0), 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </td>
                        <td className="p-1.5 text-right font-mono text-red-600 text-[12px]">
                          ≈ ₹{dhanData.shortCapitalAllocation.reduce((s, c) => s + (c.riskAmount ?? 0), 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            )}
          </>
        )}

        {!dhanLoading && !dhanError && (!dhanData?.recommendations || dhanData.recommendations.length === 0) && (!dhanData?.shortRecommendations || dhanData.shortRecommendations.length === 0) && (
          <div className="flex flex-col items-center justify-center py-8 text-slate-400">
            <span className="text-[10px] uppercase tracking-wider font-semibold">No scanner signals today</span>
            <span className="text-[8px] mt-1">Dhan ScanX API may be unreachable — check logs</span>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="text-center text-[7px] text-slate-400 pt-1">
        {monitorMode
          ? 'FIXED PLAN ACTIVE · Monitor mode · Live prices every 2s · No external API calls'
          : 'lemonn.co.in · Dhan ScanX + feed_scanner · Data refreshes every 2 minutes'}
      </div>

      <style>{`
        .line-clamp-2 {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        @keyframes sparkline-draw {
          from { stroke-dashoffset: 300; }
          to { stroke-dashoffset: 0; }
        }
        .sparkline-draw {
          animation: sparkline-draw 1.2s ease-out forwards;
        }
        @keyframes sparkline-fade-in {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}