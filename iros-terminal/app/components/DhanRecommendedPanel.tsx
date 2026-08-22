'use client';

import React, { useMemo } from 'react';
import type { DhanSwingPick, DhanSwingPicksPayload, LiveStock, MarketDataResponse } from '@/lib/market-api';
import { dhanRrValue } from '@/lib/intelligence-summary';

type Props = {
  liveMarket?: MarketDataResponse | null;
  onSelect?: (ticker: string) => void;
};

function fmtPx(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return n.toFixed(2);
}

function fmtRr(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `~${n.toFixed(1)}`;
}

function liveLtp(pick: DhanSwingPick, quotes?: Record<string, LiveStock>, stocks?: LiveStock[]): number | null {
  const sym = (pick.symbol || '').toUpperCase();
  if (!sym) return null;
  const fromQuote = quotes?.[sym]?.ltpRaw;
  if (typeof fromQuote === 'number' && fromQuote > 0) return fromQuote;
  const fromStock = stocks?.find((s) => s.ticker?.toUpperCase() === sym)?.ltpRaw;
  if (typeof fromStock === 'number' && fromStock > 0) return fromStock;
  if (typeof pick.scanLtp === 'number' && pick.scanLtp > 0) return pick.scanLtp;
  return null;
}

export default function DhanRecommendedPanel({ liveMarket, onSelect }: Props) {
  const payload = liveMarket?.dhanSwingPicks as DhanSwingPicksPayload | undefined;
  const picks = useMemo(() => {
    const raw = payload?.picks ?? [];
    return raw.filter((p) => p?.symbol);
  }, [payload?.picks]);

  const updatedLabel = payload?.updatedAt
    ? new Date(payload.updatedAt).toLocaleString('en-IN', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : null;

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm relative overflow-hidden">
      <div
        className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-emerald-500 via-teal-400 to-transparent pointer-events-none"
        aria-hidden
      />

      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
        <div className="min-w-0 flex items-start gap-2.5">
          <div className="w-7 h-7 rounded-xl dhan-icon flex items-center justify-center shadow-md shrink-0 mt-0.5">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7M4 7h16M4 7l2-3h12l2 3" />
            </svg>
          </div>
          <div className="min-w-0">
            <h3 className="desk-panel-title text-emerald-700">SHORT-TERM ANALYST PICKS</h3>
            <p className="text-slate-500 text-[12px] mt-0.5">
              Short-horizon swing candidates
              {typeof payload?.scannedCount === 'number' && payload.scannedCount > 0 && (
                <> · Scanned {payload.scannedCount}</>
              )}
              {picks.length > 0 && <> · {picks.length} picks</>}
              {updatedLabel && <> · {updatedLabel}</>}
              {payload?.isMock && <span className="text-amber-600 font-semibold"> · mock</span>}
            </p>
          </div>
        </div>
        <div className="px-2 py-0.5 rounded-lg bg-emerald-50 border border-emerald-200 shrink-0 self-start">
          <span className="text-[10px] text-emerald-700 font-semibold uppercase tracking-wider">
            LONG {picks.length}
          </span>
        </div>
      </div>

      {payload?.error && (
        <div className="mb-3 p-2 rounded-lg bg-red-50 border border-red-200 text-[11px] text-red-600">
          {payload.error}
        </div>
      )}

      {picks.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-3 py-6 text-center">
          <p className="text-[11px] text-slate-500 font-medium">No short-term analyst picks in the current snapshot</p>
          <p className="text-[10px] text-slate-400 mt-1">
            {payload ? 'Waiting for short-term picks to refresh' : 'Short-term picks are unavailable in the current feed'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
          {picks.map((pick, idx) => {
            const rr = dhanRrValue(pick);
            const ltp = liveLtp(pick, liveMarket?.stockQuotes, liveMarket?.stocks);
            const reason = pick.reasons?.[0];
            return (
              <button
                key={`dhan-rec-${pick.symbol}-${idx}`}
                type="button"
                onClick={() => onSelect?.(pick.symbol)}
                className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-2.5 shadow-sm hover:shadow-md transition-all text-left group"
                style={{ borderLeft: '3px solid #10b981' }}
              >
                <div className="absolute -top-4 -right-4 w-12 h-12 rounded-full opacity-15 blur-2xl bg-emerald-500 pointer-events-none" />
                <div className="flex items-center justify-between mb-1 relative z-10 gap-1">
                  <span className="desk-metric-value font-mono text-[13px]">{pick.symbol}</span>
                  {pick.score != null && Number.isFinite(pick.score) && (
                    <span className="text-[8px] font-bold text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded shrink-0">
                      {pick.score.toFixed(0)}
                    </span>
                  )}
                </div>
                {pick.name && (
                  <p className="text-[8px] text-slate-500 mb-1.5 truncate relative z-10">{pick.name}</p>
                )}
                <div className="space-y-1 text-[8px] relative z-10">
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">LTP</span>
                    <span className="font-bold text-slate-700">{ltp != null ? fmtPx(ltp) : '—'}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">Buy Above</span>
                    <span className="font-bold text-emerald-600">{fmtPx(pick.buyAbove)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">T1 / T2</span>
                    <span className="font-bold text-blue-600">
                      {fmtPx(pick.target1)} / {fmtPx(pick.target2)}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">Stop Loss</span>
                    <span className="font-bold text-red-500">{fmtPx(pick.stopLoss)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">R:R (T2)</span>
                    <span className="font-bold text-slate-700">{fmtRr(rr)}</span>
                  </div>
                </div>
                {reason && (
                  <p className="mt-1.5 text-[7px] text-slate-400 line-clamp-2 relative z-10 leading-snug">
                    {reason}
                  </p>
                )}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
