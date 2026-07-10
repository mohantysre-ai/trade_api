'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { MarketDataResponse, TerminalIntelligence, LiveStock, SparkFlag } from '@/lib/market-api';
import { fetchNseSparkline } from '@/lib/market-api';

/* ── Smooth sparkline SVG with Catmull-Rom spline ─────────────────────── */
const SPARK_FLAGS: SparkFlag[] = ['1D', '1M', '1Y'];

let assetSparkIdCounter = 0;

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

function StockSparklineSVG({ data }: { data: number[] }) {
  const [id] = useState(() => `asset-spk-${++assetSparkIdCounter}`);
  const [glowId] = useState(() => `asset-glow-${++assetSparkIdCounter}`);
  if (!data || data.length < 2) return null;

  const first = data[0];
  const last = data[data.length - 1];
  const positive = last >= first;
  const color = positive ? '#10b981' : '#ef4444';

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

  /* min/max labels */
  const minIdx = data.indexOf(Math.min(...data));
  const maxIdx = data.indexOf(Math.max(...data));

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

      {/* High dot */}
      <circle cx={points[maxIdx][0]} cy={points[maxIdx][1]} r="1.5" fill={color} stroke="white" strokeWidth="0.8" opacity="0.6" />
      {/* Low dot */}
      <circle cx={points[minIdx][0]} cy={points[minIdx][1]} r="1.5" fill={color} stroke="white" strokeWidth="0.8" opacity="0.6" />

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

function SparklineFlagSlider({ ticker, sparklines, onFlagChange, currentFlag }: {
  ticker: string;
  sparklines: Record<SparkFlag, number[]>;
  onFlagChange: (flag: SparkFlag) => void;
  currentFlag: SparkFlag;
}) {
  const data = sparklines?.[currentFlag];
  const hasData = data && data.length >= 2;

  /* Calculate change for badge */
  let changeLabel = '';
  let changeColor = 'text-slate-400';
  if (hasData) {
    const first = data![0];
    const last = data![data!.length - 1];
    const pct = ((last - first) / first) * 100;
    changeLabel = `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
    changeColor = pct >= 0 ? 'text-emerald-600' : 'text-red-500';
  }

  return (
    <div className="mb-1.5 relative z-10">
      {/* Chart area */}
      <div
        className="rounded-lg overflow-hidden transition-all"
        style={{
          background: hasData
            ? 'linear-gradient(135deg, rgba(100,116,139,0.03) 0%, rgba(100,116,139,0.06) 100%)'
            : 'transparent',
        }}
      >
        {hasData ? (
          <StockSparklineSVG data={data!} />
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
      {/* Flag slider + change badge */}
      <div className="flex items-center justify-between mt-0.5">
        <div className="flex items-center gap-0.5">
          {SPARK_FLAGS.map((f) => (
            <button
              key={f}
              onClick={(e) => { e.stopPropagation(); onFlagChange(f); }}
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

type AssetRow = {
  ticker: string;
  price: string;
  score: number;
  kelly: string;
  returnPct: number;
  thesis: string;
  riskFlag: string;
  state?: string;
};

export default function ForensicPanel({
  onSelect,
  liveMarket,
  refreshOnDemand,
}: {
  onSelect?: (ticker: string) => void;
  liveMarket?: MarketDataResponse | null;
  refreshOnDemand?: () => Promise<void>;
}) {
  const [refreshing, setRefreshing] = useState(false);

  const live = liveMarket ?? null;
  const stocks = live?.stocks ?? [];
  const intelligence = live?.terminalIntelligence ?? null;

  const stockPriceMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const stock of stocks) {
      map.set(stock.ticker, stock.ltp);
    }
    return map;
  }, [stocks]);

  const assetRows: AssetRow[] = useMemo(() => {
    const rows: AssetRow[] = [];
    const seen = new Set<string>();
    const push = (row: AssetRow) => {
      if (!seen.has(row.ticker)) {
        seen.add(row.ticker);
        rows.push(row);
      }
    };

    if (intelligence?.ledger_stocks?.length) {
      const sorted = [...intelligence.ledger_stocks].sort(
        (a, b) => (typeof b.score === 'number' ? b.score : 0) - (typeof a.score === 'number' ? a.score : 0)
      );
      const total = sorted.length;
      for (let i = 0; i < sorted.length; i++) {
        const row = sorted[i];
        const action = row.action || '';
        const reason = row.selection_reason || action;
        const score = typeof row.score === 'number' ? row.score : 0;
        const tertile = total > 0 ? Math.floor((i / total) * 3) : 0;
        let riskFlag: string;
        if (tertile === 0) riskFlag = 'LOW_RISK';
        else if (tertile === 1) riskFlag = 'MODERATE_RISK';
        else riskFlag = 'HIGH_RISK';
        push({
          ticker: row.ticker,
          price: row.live_price || stockPriceMap.get(row.ticker) || '',
          score: score,
          kelly: '5.67 : 1',
          returnPct: score / 6,
          thesis: reason || 'Score-based selection',
          riskFlag: riskFlag,
          state: score >= 55 ? 'HIGH' : score <= 40 ? 'LOW' : undefined,
        });
      }
    }

    if (intelligence?.active_factor_hub) {
      const hub = intelligence.active_factor_hub;
      if (hub.thesis) {
        push({ ticker: 'Ledger Thesis', price: '', score: 0, kelly: '', returnPct: 0, thesis: hub.thesis, riskFlag: '' });
      }
      if (hub.risk_flag) {
        push({ ticker: 'Ledger Risk', price: '', score: 0, kelly: '', returnPct: 0, thesis: '', riskFlag: hub.risk_flag, state: 'HIGH' });
      }
    }

    if (rows.length < stocks.length) {
      for (const s of stocks.slice(rows.length, 20)) {
        push({
          ticker: s.ticker,
          price: s.ltp,
          score: typeof s.score === 'number' ? s.score : 0,
          kelly: '5.67 : 1',
          returnPct: typeof s.score === 'number' ? s.score / 6 : 2.4,
          thesis: s.verdict || (s.state === 'POSITIVE' ? 'Upward momentum' : 'Volatility play'),
          riskFlag: s.state === 'POSITIVE' ? 'Low Vol' : 'ATR',
          state: s.state === 'POSITIVE' ? 'LOW' : 'HIGH',
        });
      }
    }

    return rows;
  }, [intelligence, stocks]);

  const topReturn = useMemo(() => {
    const vals = assetRows.map((r) => r.returnPct).filter((v): v is number => typeof v === 'number');
    if (!vals.length) return {};
    return { value: Math.max(...vals) };
  }, [assetRows]);

  /* Per-ticker flag state (default 1M) */
  const [tickerFlags, setTickerFlags] = useState<Record<string, SparkFlag>>({});
  const getFlag = (ticker: string): SparkFlag => tickerFlags[ticker] ?? '1D';
  const setFlag = (ticker: string, flag: SparkFlag) => setTickerFlags((prev) => ({ ...prev, [ticker]: flag }));

  /* Collect unique flags in use for fetching */
  const activeFlags = useMemo(() => {
    const flags = new Set<SparkFlag>();
    for (const r of assetRows) flags.add(getFlag(r.ticker));
    return [...flags];
  }, [assetRows, tickerFlags]);

  /* Fetch sparkline data for all tickers x all active flags */
  const tickerList = useMemo(() => assetRows.map((r) => r.ticker), [assetRows]);
  const stockSparklines1M = useStockSparklines(tickerList, '1M');
  const stockSparklines1D = useStockSparklines(tickerList, '1D');
  const stockSparklines1Y = useStockSparklines(tickerList, '1Y');

  /* Merge into one lookup: ticker -> flag -> number[] */
  const allSparklines = useMemo(() => {
    const merged: Record<string, Record<SparkFlag, number[]>> = {};
    for (const t of tickerList) {
      merged[t] = {
        '1D': stockSparklines1D[t]?.['1D'] ?? [],
        '1M': stockSparklines1M[t]?.['1M'] ?? [],
        '1Y': stockSparklines1Y[t]?.['1Y'] ?? [],
      };
    }
    return merged;
  }, [tickerList, stockSparklines1D, stockSparklines1M, stockSparklines1Y]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      if (refreshOnDemand) {
        await refreshOnDemand();
      }
    } finally {
      setRefreshing(false);
    }
  };

  const scoreColor = (s: number) => {
    if (s >= 60) return 'text-emerald-600';
    if (s >= 40) return 'text-amber-600';
    return 'text-slate-500';
  };

  const flagClass = (flag: string) => {
    const v = flag.toLowerCase();
    if (v.includes('extreme')) return 'text-white border-red-700 bg-red-600 animate-pulse font-black';
    if (v.includes('low_risk') || v.includes('low vol') || v === 'low') return 'text-teal-700 border-teal-200 bg-teal-50';
    if (v.includes('moderate_risk') || v.includes('moderate')) return 'text-amber-700 border-amber-200 bg-amber-50';
    if (v.includes('high_risk') || v.includes('structural') || v.includes('atr')) return 'text-red-700 border-red-200 bg-red-50';
    if (v.includes('selected') || v === 'buy') return 'text-slate-400 border-slate-200 bg-slate-50';
    return 'text-slate-600 border-red-200 bg-red-50';
  };

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-emerald-700 text-[12px] font-bold tracking-wider uppercase">ASSET MATRIX</h3>
          <p className="text-slate-500 text-[12px] mt-0.5">Active Nodes {stocks.length || assetRows.length} · Avg Kelly Ratio 5.67:1 · Top Return 13.8 · Data Date {live?.updatedAt ? new Date(live.updatedAt).toISOString().slice(0, 10) : '2026-06-11'}</p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="px-3 py-1 text-[12px] rounded-full bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 disabled:opacity-50 transition"
        >
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
        {assetRows.map((row) => {
          const priceVal = row.price ? `₹${String(row.price).replace(/[₹]+/g, '')}` : '-';
          const returnVal = row.returnPct >= 0 ? `+${row.returnPct.toFixed(1)}` : row.returnPct.toFixed(1);
          const isPositive = row.returnPct >= 0;
          return (
            <div
              key={row.ticker}
              onClick={() => onSelect?.(row.ticker)}
              className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-2.5 shadow-sm hover:shadow-md transition-all group cursor-pointer"
              style={{ borderLeft: isPositive ? '3px solid #10b981' : '3px solid #ef4444' }}
            >
              <div className="absolute -top-4 -right-4 w-12 h-12 rounded-full opacity-15 blur-2xl"
                style={{ backgroundColor: isPositive ? '#10b981' : '#ef4444' }} />
              <div className="flex items-center justify-between mb-1.5 relative z-10">
                <span className="text-[12px] font-black text-slate-900 font-mono">{row.ticker}</span>
                {row.riskFlag && (
                  <span className={`inline-block border px-1.5 py-0.5 rounded text-[12px] whitespace-nowrap font-black uppercase ${flagClass(row.riskFlag)}`}>
                    {row.riskFlag}
                  </span>
                )}
              </div>
              <p className="text-[12px] text-slate-500 mb-1 truncate relative z-10">{row.thesis}</p>
              <SparklineFlagSlider
                ticker={row.ticker}
                sparklines={allSparklines[row.ticker] ?? ({} as Record<SparkFlag, number[]>)}
                currentFlag={getFlag(row.ticker)}
                onFlagChange={(f) => setFlag(row.ticker, f)}
              />
              <div className="space-y-1 text-[12px] relative z-10">
                <div className="flex justify-between"><span className="text-slate-400">Price</span><span className="font-bold text-slate-700">{priceVal}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Score</span><span className={`font-bold ${scoreColor(row.score)}`}>{row.score || '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Kelly</span><span className="font-bold text-slate-700">{row.kelly || '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Return</span><span className={`font-bold ${isPositive ? 'text-emerald-600' : 'text-red-500'}`}>{returnVal}</span></div>
              </div>
            </div>
          );
        })}
        {!assetRows.length && (
          <div className="col-span-full py-6 text-center text-slate-500">
            No live market data for Nifty 500.
          </div>
        )}
      </div>

      <style>{`
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
    </section>
  );
}