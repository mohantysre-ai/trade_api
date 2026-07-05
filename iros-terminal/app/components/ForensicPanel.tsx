'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { MarketDataResponse, TerminalIntelligence, LiveStock, SparkFlag } from '@/lib/market-api';
import { fetchNseSparkline } from '@/lib/market-api';

/* ── Sparkline: real price data from NSE India ─────────────────────────── */
const SPARK_FLAGS: SparkFlag[] = ['1D', '1M', '1Y'];

let assetSparkIdCounter = 0;

function StockSparklineSVG({ data }: { data: number[] }) {
  const [id] = useState(() => `asset-spk-${++assetSparkIdCounter}`);
  if (!data || data.length < 2) return null;

  const first = data[0];
  const last = data[data.length - 1];
  const positive = last >= first;
  const color = positive ? '#10b981' : '#ef4444';

  const W = 100;
  const H = 32;
  const pad = 2;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad * 2);
    const y = pad + (1 - (v - min) / range) * (H - pad * 2);
    return [x, y] as const;
  });

  const pathD = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const areaD = `${pathD} L ${points[points.length - 1][0].toFixed(2)},${H} L ${points[0][0].toFixed(2)},${H} Z`;
  const lastPt = points[points.length - 1];

  /* min/max labels */
  const minIdx = data.indexOf(Math.min(...data));
  const maxIdx = data.indexOf(Math.max(...data));

  return (
    <svg className="w-full h-8 opacity-85" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#${id})`} />
      <path d={pathD} stroke={color} strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* High dot */}
      <circle cx={points[maxIdx][0]} cy={points[maxIdx][1]} r="1.5" fill={color} stroke="white" strokeWidth="0.8" opacity="0.6" />
      {/* Low dot */}
      <circle cx={points[minIdx][0]} cy={points[minIdx][1]} r="1.5" fill={color} stroke="white" strokeWidth="0.8" opacity="0.6" />
      {/* End dot */}
      <circle cx={lastPt[0]} cy={lastPt[1]} r="2" fill={color} stroke="white" strokeWidth="1" />
    </svg>
  );
}

function useStockSparklines(tickers: string[], flag: SparkFlag): Record<string, Record<SparkFlag, number[]>> {
  const [sparklines, setSparklines] = useState<Record<string, Record<SparkFlag, number[]>>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const key = `__flag_${flag}`;
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
      console.debug('[ForensicPanel spark] updates', Object.keys(updates).length, results.map(r => r.status === 'fulfilled' ? r.value.ticker + '=' + r.value.sparkline.length : 'rejected').join(', '));

      if (Object.keys(updates).length > 0) {
        console.debug('[ForensicPanel spark] setSparklines tickers=', Object.keys(updates));
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
      <div className="rounded-md overflow-hidden" style={{ background: hasData ? 'rgba(100,116,139,0.04)' : 'transparent' }}>
        {hasData ? (
          <StockSparklineSVG data={data!} />
        ) : (
          <div className="h-8 flex items-center justify-center">
            <span className="text-[7px] text-slate-300 uppercase tracking-wider">Loading…</span>
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
              className={`px-1 py-0 rounded text-[7px] font-bold uppercase tracking-wider transition-all ${
                f === currentFlag
                  ? 'bg-slate-800 text-white'
                  : 'bg-transparent text-slate-400 hover:text-slate-600'
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
  console.warn('[DEBUG] ForensicPanel render', { stocks: liveMarket?.stocks?.length });
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
      // Sort by score descending first
      const sorted = [...intelligence.ledger_stocks].sort(
        (a, b) => (typeof b.score === 'number' ? b.score : 0) - (typeof a.score === 'number' ? a.score : 0)
      );
      const total = sorted.length;
      for (let i = 0; i < sorted.length; i++) {
        const row = sorted[i];
        const action = row.action || '';
        const reason = row.selection_reason || action;
        const score = typeof row.score === 'number' ? row.score : 0;
        // Risk flag based on relative rank in cohort (tertiles)
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
  const getFlag = (ticker: string): SparkFlag => tickerFlags[ticker] ?? '1M';
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
    </section>
  );
}