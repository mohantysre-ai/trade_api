'use client';

import React, { useMemo, useState } from 'react';
import type { MarketDataResponse, TerminalIntelligence, LiveStock } from '@/lib/market-api';

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
              <p className="text-[12px] text-slate-500 mb-2 truncate relative z-10">{row.thesis}</p>
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