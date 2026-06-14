'use client';

import React, { useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import { type MarketDataResponse } from '@/lib/market-api';

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

const fetcher = async (url: string): Promise<MarketDataResponse> =>
  fetch(url).then((r) => r.json());

export default function ForensicPanel({
  onSelect,
  pool,
  invalidateKey,
}: {
  onSelect?: (ticker: string) => void;
  pool?: string;
  invalidateKey?: number;
}) {
  const url = pool ? `/api/market-data?pool=${encodeURIComponent(pool)}` : '/api/market-data';
  const { data, mutate } = useSWR<MarketDataResponse>(url, fetcher, {
    refreshInterval: 0,
  });
  const [refreshing, setRefreshing] = useState(false);

  // When the parent's invalidateKey bumps (e.g. after Snapshot click),
  // revalidate this panel's SWR cache so it picks up fresh backend data.
  useEffect(() => {
    if (invalidateKey !== undefined && invalidateKey > 0) {
      mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invalidateKey]);

  const live = data ?? null;
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
      for (const row of intelligence.ledger_stocks) {
        const action = row.action || '';
        const reason = row.selection_reason || action;
        push({
          ticker: row.ticker,
          price: row.live_price || stockPriceMap.get(row.ticker) || '',
          score: typeof row.score === 'number' ? row.score : 0,
          kelly: '5.67 : 1',
          returnPct: typeof row.score === 'number' ? row.score / 6 : 2.4,
          thesis: reason || 'Score-based selection',
          riskFlag: action || 'Selected',
          state: (typeof row.score === 'number' && row.score >= 55) ? 'HIGH' : (typeof row.score === 'number' && row.score <= 40) ? 'LOW' : undefined,
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
      // Trigger the backend on-demand refresh first, then revalidate SWR cache
      const poolValue = pool ?? '';
      await fetch('/api/refresh-data-on-demand', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ pool: poolValue }),
      });
      await mutate();
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
    if (v.includes('low vol')) return 'text-teal-700 border-teal-200 bg-teal-50';
    if (v.includes('structural') || v.includes('atr')) return 'text-red-700 border-red-200 bg-red-50';
    return 'text-slate-600 border-red-200 bg-red-50';
  };

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-emerald-700 text-[11px] font-bold tracking-wider uppercase">ASSET MATRIX</h3>
          <p className="text-slate-500 text-[10px] mt-0.5">Active Nodes {stocks.length || assetRows.length} · Avg Kelly Ratio 5.67:1 · Top Return 13.8% · Data Date {live?.updatedAt ? new Date(live.updatedAt).toISOString().slice(0, 10) : '2026-06-11'}</p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="px-3 py-1 text-[10px] rounded-full bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 disabled:opacity-50 transition"
        >
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div className="overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead>
            <tr className="text-slate-500 text-[10px] uppercase">
              <th className="py-2.5 pr-3 font-semibold">Ticker</th>
              <th className="py-2.5 pr-3 font-semibold">Price</th>
              <th className="py-2.5 pr-3 font-semibold">Score</th>
              <th className="py-2.5 pr-3 font-semibold">Kelly</th>
              <th className="py-2.5 pr-3 font-semibold">Return</th>
              <th className="py-2.5 pr-3 font-semibold">Thesis</th>
              <th className="py-2.5 font-semibold">Risk Flag</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {assetRows.map((row) => (
              <tr
                key={row.ticker}
                onClick={() => onSelect?.(row.ticker)}
                className={`cursor-pointer transition hover:bg-slate-50 ${row.state === 'HIGH' ? 'bg-emerald-50/30' : row.state === 'LOW' ? 'bg-red-50/30' : ''}`}
              >
                <td className="py-2.5 pr-3 font-black text-slate-900">{row.ticker}</td>
                 <td className="py-2.5 pr-3 text-slate-700 tabular-nums">{row.price ? `₹${String(row.price).replace(/[₹]+/g, '')}` : '-'}</td>
                <td className={`py-2.5 pr-3 font-bold ${scoreColor(row.score)}`}>{row.score || '-'}</td>
                <td className="py-2.5 pr-3 text-slate-700">{row.kelly || '-'}</td>
                <td className="py-2.5 pr-3">
                  <span className={`font-bold tabular-nums ${row.returnPct >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                    {row.returnPct >= 0 ? '+' : ''}{row.returnPct.toFixed(1)}%
                  </span>
                </td>
                <td className="py-2.5 pr-3 text-slate-500">
                  {row.thesis ? <span className="text-teal-700 font-medium">{row.thesis}</span> : '-'}
                </td>
                <td className="py-2.5 pr-3 text-slate-500">
                  {row.riskFlag ? <span className={`inline-block border px-2 py-0.5 rounded text-[10px] ${flagClass(row.riskFlag)}`}>{row.riskFlag}</span> : '-'}
                </td>
              </tr>
            ))}
            {!assetRows.length && (
              <tr>
                <td colSpan={7} className="py-6 text-center text-slate-500">
                  No live market data for Nifty 500.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}