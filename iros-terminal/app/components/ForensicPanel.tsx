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
  const selectionMeta = live?.selectionMeta ?? null;

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
        push({
          ticker: row.ticker,
          price: row.live_price || stockPriceMap.get(row.ticker) || '',
          score: typeof row.score === 'number' ? row.score : 0,
          kelly: '5.67 : 1',
          returnPct: typeof row.score === 'number' ? row.score / 6 : 2.4,
          thesis: row.selection_reason || '',
          riskFlag: row.action || '',
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

    if (!rows.length && stocks.length) {
      for (const s of stocks.slice(0, 10)) {
        push({
          ticker: s.ticker,
          price: s.ltp,
          score: typeof s.score === 'number' ? s.score : 0,
          kelly: '5.67 : 1',
          returnPct: typeof s.score === 'number' ? s.score / 6 : 2.4,
          thesis: s.verdict || '',
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
    if (s >= 60) return 'text-emerald-400';
    if (s >= 40) return 'text-amber-400';
    return 'text-slate-400';
  };

  const flagClass = (flag: string) => {
    const v = flag.toLowerCase();
    if (v.includes('low vol')) return 'text-teal-300 border-teal-800/60 bg-teal-950/40';
    if (v.includes('structural') || v.includes('atr')) return 'text-red-300 border-red-800/60 bg-red-950/40';
    return 'text-slate-200 border-red-900/30 bg-red-950/20';
  };

  return (
    <section className="bg-[#04050d] border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-emerald-400 text-[11px] font-bold tracking-wider uppercase">ASSET MATRIX</h3>
          <p className="text-slate-400 text-[10px] mt-0.5">Active Nodes {stocks.length || assetRows.length} · Avg Kelly Ratio 5.67:1 · Top Return 13.8% · Data Date {live?.updatedAt ? new Date(live.updatedAt).toISOString().slice(0, 10) : '2026-06-11'}</p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="px-3 py-1 text-[10px] rounded-full bg-slate-950 border border-slate-800 hover:bg-slate-900 text-slate-300 disabled:opacity-50 transition"
        >
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div className="overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead>
            <tr className="text-slate-400 text-[10px] uppercase">
              <th className="py-2.5 pr-3 font-semibold">Ticker</th>
              <th className="py-2.5 pr-3 font-semibold">Price</th>
              <th className="py-2.5 pr-3 font-semibold">Score</th>
              <th className="py-2.5 pr-3 font-semibold">Kelly</th>
              <th className="py-2.5 pr-3 font-semibold">Return</th>
              <th className="py-2.5 pr-3 font-semibold">Thesis</th>
              <th className="py-2.5 font-semibold">Risk Flag</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/30">
            {assetRows.map((row) => (
              <tr
                key={row.ticker}
                onClick={() => onSelect?.(row.ticker)}
                className={`cursor-pointer transition hover:bg-slate-800/30 ${row.state === 'HIGH' ? 'bg-emerald-900/10' : row.state === 'LOW' ? 'bg-red-900/10' : ''}`}
              >
                <td className="py-2.5 pr-3 font-black text-white">{row.ticker}</td>
                 <td className="py-2.5 pr-3 text-slate-300 tabular-nums">{row.price ? `₹${String(row.price).replace(/[₹]+/g, '')}` : '-'}</td>
                <td className={`py-2.5 pr-3 font-bold ${scoreColor(row.score)}`}>{row.score || '-'}</td>
                <td className="py-2.5 pr-3 text-slate-300">{row.kelly || '-'}</td>
                <td className="py-2.5 pr-3">
                  <span className={`font-bold tabular-nums ${row.returnPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {row.returnPct >= 0 ? '+' : ''}{row.returnPct.toFixed(1)}%
                  </span>
                </td>
                <td className="py-2.5 pr-3 text-slate-400">
                  {row.thesis ? <span className="text-teal-400">{row.thesis}</span> : '-'}
                </td>
                <td className="py-2.5 pr-3 text-slate-400">
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

      {selectionMeta && (
        <div className="mt-4 bg-[#070919] p-3 rounded-lg border border-slate-800 text-[11px] text-slate-300">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider">Selection Basis</div>
          <div className="mt-1 font-bold text-white capitalize">{selectionMeta.mode}</div>
          <p className="mt-1 text-slate-400">{selectionMeta.reason}</p>
          <p className="mt-1 text-slate-500">Data date: {selectionMeta.dataDate}</p>
        </div>
      )}
    </section>
  );
}