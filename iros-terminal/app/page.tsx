'use client';

import React, { useEffect, useMemo, useState } from 'react';
import {
  useMarketData,
  type LiveStock,
  type MacroRow,
  type LedgerStock,
  type TerminalIntelligence,
} from '@/lib/market-api';
import ForensicPanel from './components/ForensicPanel';
import RightDrawer from './components/RightDrawer';

type DrawerContent = {
  stock?: LiveStock | LedgerStock | null;
  analysis?: (TerminalIntelligence & {
    isSnapshotFallback?: boolean;
    error?: string;
  }) | null;
};

type TabKey = 'marketSnapshot' | 'assetMatrix';

const INDIA_MARKET_LABELS = new Set(['NIFTY 100', 'SENSEX', 'NIFTY BANK', 'NIFTY IT', 'NIFTY PHARMA', 'NIFTY MIDCAP', 'NIFTY SMALLCAP']);
const GLOBAL_ONLY_LABELS = new Set(['BRENT CRUDE', 'BRENT CRUDE OIL']);

function normalizeMarketLabel(label: string) {
  return label.toUpperCase().replace(/\s+/g, ' ');
}

function marketStateBorder(state: string) {
  if (state === 'POSITIVE') return 'border-l-emerald-500';
  if (state === 'NEGATIVE') return 'border-l-red-500';
  return 'border-l-slate-300';
}

function marketStateClass(state: string) {
  if (state === 'POSITIVE') return 'text-emerald-600';
  if (state === 'NEGATIVE') return 'text-red-500';
  return 'text-slate-500';
}

/* -------------------------------------------------------------------------- */
/*  Helper: parse delta string like "+2.73%" or "-3.12%"                     */
/* -------------------------------------------------------------------------- */
function parseDeltaPct(delta: string | undefined): number {
  if (!delta) return 0;
  const cleaned = delta.replace('%', '').replace(',', '');
  return parseFloat(cleaned) || 0;
}

/* -------------------------------------------------------------------------- */
/*  NIFTY TOP 5 GAINERS & LOSERS (live from stockQuotes)                     */
/* -------------------------------------------------------------------------- */
function GainersLosersHeatmap({ stockQuotes }: { stockQuotes?: Record<string, LiveStock> }) {
  const sorted = useMemo(() => {
    if (!stockQuotes) return { gainers: [] as LiveStock[], losers: [] as LiveStock[] };
    const entries = Object.values(stockQuotes).filter(s => s.delta);
    const withPct = entries.map(s => ({ ...s, pct: parseDeltaPct(s.delta) }));
    withPct.sort((a, b) => b.pct - a.pct);
    return {
      gainers: withPct.filter(s => s.pct >= 0).slice(0, 5),
      losers: withPct.filter(s => s.pct < 0).slice(-5).reverse(),
    };
  }, [stockQuotes]);

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">NIFTY TOP 5 GAINERS & LOSERS</span>
        <span className="text-[8px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">{sorted.gainers.length + sorted.losers.length} stocks</span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {/* Gainers */}
        <div>
          <div className="text-[9px] uppercase tracking-wider text-emerald-600 font-bold mb-2 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            TOP GAINERS
          </div>
          <div className="space-y-1.5">
            {sorted.gainers.length === 0 && (
              <div className="text-[10px] text-slate-400 px-3 py-2">No data</div>
            )}
            {sorted.gainers.map((s) => {
              const pct = parseDeltaPct(s.delta);
              return (
                <div
                  key={s.ticker}
                  className="flex items-center justify-between px-3 py-2 rounded-lg transition-all hover:scale-[1.02] cursor-default"
                  style={{ backgroundColor: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.2)' }}
                >
                  <div>
                    <span className="text-[11px] font-bold text-slate-800">{s.ticker}</span>
                    <span className="text-[10px] text-slate-500 ml-2">{s.ltp}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-[11px] font-bold text-emerald-600">+{pct.toFixed(2)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        {/* Losers */}
        <div>
          <div className="text-[9px] uppercase tracking-wider text-red-500 font-bold mb-2 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            TOP LOSERS
          </div>
          <div className="space-y-1.5">
            {sorted.losers.length === 0 && (
              <div className="text-[10px] text-slate-400 px-3 py-2">No data</div>
            )}
            {sorted.losers.map((s) => {
              const pct = parseDeltaPct(s.delta);
              return (
                <div
                  key={s.ticker}
                  className="flex items-center justify-between px-3 py-2 rounded-lg transition-all hover:scale-[1.02] cursor-default"
                  style={{ backgroundColor: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.2)' }}
                >
                  <div>
                    <span className="text-[11px] font-bold text-slate-800">{s.ticker}</span>
                    <span className="text-[10px] text-slate-500 ml-2">{s.ltp}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-[11px] font-bold text-red-500">{pct.toFixed(2)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  NIFTY 100 HEAT MAP (live from stockQuotes)                                */
/* -------------------------------------------------------------------------- */
function getHeatColor(pct: number): { bg: string; text: string; border: string } {
  const abs = Math.min(Math.abs(pct) / 4, 1);
  if (pct > 0) {
    const r = Math.round(220 - abs * 160);
    const g = Math.round(245 - abs * 65);
    const b = Math.round(220 - abs * 140);
    return {
      bg: `rgba(${r}, ${g}, ${b}, 0.85)`,
      text: `rgb(${Math.round(10 + abs * 25)}, ${Math.round(80 + abs * 20)}, ${Math.round(10 + abs * 25)})`,
      border: `rgba(16, 185, 129, ${0.2 + abs * 0.4})`,
    };
  } else {
    const absVal = Math.abs(pct) / 4;
    const r = Math.round(245 - absVal * 25);
    const g = Math.round(220 - absVal * 170);
    const b = Math.round(220 - absVal * 170);
    return {
      bg: `rgba(${r}, ${g}, ${b}, 0.85)`,
      text: `rgb(${Math.round(80 + absVal * 30)}, ${Math.round(10 + absVal * 25)}, ${Math.round(10 + absVal * 25)})`,
      border: `rgba(239, 68, 68, ${0.2 + absVal * 0.4})`,
    };
  }
}

function Nifty100HeatMap({ stockQuotes }: { stockQuotes?: Record<string, LiveStock> }) {
  const stocks = useMemo(() => {
    if (!stockQuotes) return [];
    return Object.values(stockQuotes)
      .filter(s => s.delta)
      .map(s => ({ ticker: s.ticker, changePct: parseDeltaPct(s.delta) }));
  }, [stockQuotes]);

  const gainers = useMemo(() => stocks.filter(s => s.changePct >= 0).length, [stocks]);
  const losers = useMemo(() => stocks.filter(s => s.changePct < 0).length, [stocks]);

  if (stocks.length === 0) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 shadow-sm">
        <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold mb-3">NIFTY 100 HEAT MAP</div>
        <div className="text-[10px] text-slate-400">Waiting for live data...</div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">NIFTY 100 HEAT MAP</span>
          <span className="text-[9px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">{stocks.length} stocks</span>
        </div>
        <div className="flex items-center gap-3 text-[8px] uppercase tracking-wider text-slate-400">
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded bg-emerald-800" /> Gainers <span className="text-emerald-700 font-bold">{gainers}</span></span>
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded bg-red-800" /> Losers <span className="text-red-700 font-bold">{losers}</span></span>
        </div>
      </div>
      <div className="grid grid-cols-5 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-1.5">
        {stocks.map((stock) => {
          const colors = getHeatColor(stock.changePct);
          return (
            <div
              key={stock.ticker}
              className="flex flex-col items-center justify-center rounded-md py-2 px-1 transition-all hover:scale-110 hover:shadow-md cursor-default"
              style={{
                backgroundColor: colors.bg,
                border: `1px solid ${colors.border}`,
              }}
              title={`${stock.ticker}: ${stock.changePct > 0 ? '+' : ''}${stock.changePct.toFixed(2)}%`}
            >
              <span className="text-[8px] font-bold leading-tight" style={{ color: colors.text }}>
                {stock.ticker}
              </span>
              <span className="text-[7px] font-semibold mt-0.5" style={{ color: colors.text }}>
                {stock.changePct > 0 ? '+' : ''}{stock.changePct.toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Existing components (unchanged where possible)                             */
/* -------------------------------------------------------------------------- */

function GlobalIndicesGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 text-slate-400 text-[10px] shadow-sm">
        Waiting for global macro data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">GLOBAL INDICES</span>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {items.map((item) => {
          const isPositive = item.state === 'POSITIVE';
          return (
            <div
              key={`${item.label}-${item.val}-${item.state}`}
              className="relative overflow-hidden bg-slate-50 border border-slate-200 rounded-lg p-3 transition-all hover:border-slate-300 hover:shadow-sm"
            >
              <SparklineSVG positive={isPositive} />
              <span className="text-[10px] text-slate-500 block uppercase tracking-wider font-semibold">{item.label}</span>
              <span className="text-lg font-bold text-slate-900 block mt-1 font-mono">{item.val}</span>
              <span className={`text-[12px] font-semibold block mt-0.5 ${marketStateClass(item.state)}`}>
                {isPositive ? '↑' : '↓'} {item.delta}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CommoditiesFxGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 text-slate-400 text-[10px] shadow-sm">
        Waiting for commodities & FX data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-amber-400" />
          <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">COMMODITIES & FX</span>
        </div>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
        {items.map((item) => {
          let displayLabel = item.label;
          if (displayLabel === 'BRENT CRUDE OIL') displayLabel = 'BRENT CRUDE';
          const isPositive = item.state === 'POSITIVE';
          const intensity = isPositive ? 0.2 : 0.15;
          return (
            <div
              key={`${item.label}-${item.val}-${item.state}`}
              className="rounded-lg p-3 flex flex-col items-center justify-center cursor-pointer transition-all hover:scale-105"
              style={{
                background: isPositive
                  ? `rgba(16, 185, 129, ${intensity})`
                  : `rgba(239, 68, 68, ${intensity})`,
                border: `1px solid ${
                  isPositive ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.25)'
                }`,
              }}
            >
              <span className="text-[11px] font-bold text-slate-800">{displayLabel}</span>
              <span className="text-[10px] text-slate-500 mt-1 font-mono font-semibold">{item.val}</span>
              <span className={`text-[11px] font-semibold ${marketStateClass(item.state)}`}>
                {item.delta}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function IndiaMarketsGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-4 text-slate-400 text-[10px] shadow-sm">
        Waiting for Indian market data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg shadow-sm">
      <div className="flex items-center justify-between p-4 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-blue-500" />
          <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">INDIA MARKETS — TOP MOVERS</span>
        </div>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="divide-y divide-slate-100">
        {items.map((item) => {
          let displayLabel = item.label;
          if (displayLabel === 'USD / INR Spot') displayLabel = 'USD / INR';
          const isPositive = item.state === 'POSITIVE';
          return (
            <div
              key={`${item.label}-${item.val}-${item.state}`}
              className="flex items-center justify-between px-4 py-3 transition-colors hover:bg-slate-50"
            >
              <span className="text-[11px] font-semibold text-slate-800">{displayLabel}</span>
              <div className="flex items-center gap-4">
                <span className="text-[13px] font-mono font-bold text-slate-900">{item.val}</span>
                <span className={`text-[11px] font-semibold min-w-[60px] text-right ${marketStateClass(item.state)}`}>
                  {isPositive ? '↑' : '↓'} {item.delta}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StockDetailPanel({ stock }: { stock?: LiveStock | LedgerStock | null }) {
  if (!stock) {
    return (
      <div className="bg-white border border-emerald-300 border-[0.5px] rounded-lg p-4 text-slate-500 min-h-[120px] flex items-center justify-center text-[10px] shadow-sm">
        Select an asset to view quote detail.
      </div>
    );
  }

  const name = 'name' in stock ? stock.name : stock.ticker;
  const price = 'ltp' in stock ? stock.ltp : (stock as LedgerStock).live_price;
  const normalizedPrice = price ? `₹${String(price).replace(/[₹]+/g, '')}` : '';
  const open = 'open' in stock ? stock.open : undefined;
  const high = 'high' in stock ? stock.high : undefined;
  const low = 'low' in stock ? stock.low : undefined;
  const volume = 'volume' in stock ? stock.volume : undefined;
  const deltaValue = 'delta' in stock ? (stock as LiveStock).delta : (stock as LedgerStock).delta;

  return (
    <div className="bg-white border border-emerald-300 border-[0.5px] rounded-lg p-4 shadow-sm">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-slate-500 text-[10px] uppercase tracking-wider">{name}</div>
          <div className="flex items-baseline gap-3 mt-1">
              <span className="text-3xl font-black text-slate-900">{normalizedPrice}</span>
            {deltaValue && (
              <span
                className={`text-xs font-bold ${
                  deltaValue.includes('+') ? 'text-emerald-500' : 'text-red-500'
                }`}
              >
                {deltaValue}
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3 text-[10px]">
        <div className="bg-slate-50 border border-slate-100 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">Open</div>
          <div className="font-bold text-slate-900 mt-0.5">{open ?? 'N/A'}</div>
        </div>
        <div className="bg-slate-50 border border-slate-100 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">High</div>
          <div className="font-bold text-slate-900 mt-0.5">{high ?? 'N/A'}</div>
        </div>
        <div className="bg-slate-50 border border-slate-100 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">Low</div>
          <div className="font-bold text-slate-900 mt-0.5">{low ?? 'N/A'}</div>
        </div>
        <div className="bg-slate-50 border border-slate-100 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">Volume</div>
          <div className="font-bold text-slate-900 mt-0.5">{volume != null ? new Intl.NumberFormat().format(volume) : 'N/A'}</div>
        </div>
      </div>
    </div>
  );
}

function NewsFeedPanel({ items, now }: { items?: Array<{ title: string; source: string; link: string; summary: string; publishedAt: string }>; now: number }) {
  if (!items?.length) return null;

  const timeAgo = (dateStr: string) => {
    const diff = now - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ago`;
  };

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg shadow-sm">
      <div className="flex items-center justify-between p-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
          <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">LIVE NEWS FEED</span>
        </div>
        <span className="text-[9px] text-slate-400">{items.length} stories</span>
      </div>
      <div className="divide-y divide-slate-100 max-h-[400px] overflow-y-auto">
        {items.map((item, i) => (
          <div key={i} className="p-3 hover:bg-slate-50 transition">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <a
                  href={item.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] font-medium text-slate-800 hover:text-teal-700 leading-tight block"
                >
                  {item.title}
                </a>
                <p className="text-[10px] text-slate-500 mt-0.5 leading-relaxed line-clamp-2">{item.summary}</p>
              </div>
              <div className="flex-shrink-0 text-right">
                <span className="text-[9px] text-slate-400 block">{timeAgo(item.publishedAt)}</span>
                <span className="text-[8px] text-slate-400 block mt-0.5 max-w-[100px] truncate">{item.source.split(' ').slice(0, 3).join(' ')}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LiveIntelligencePanel() {
  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-3 shadow-sm" />
  );
}

function formatSnakeKey(key: string) {
  return key
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function RiskCalcFactorHub({ riskCalc, factorHub }: { riskCalc?: Record<string, unknown>; factorHub?: Record<string, string> }) {
  const hasRisk = !!riskCalc && Object.keys(riskCalc).length > 0;
  const hasFactor = !!factorHub && Object.keys(factorHub).length > 0;

  if (!hasRisk && !hasFactor) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] p-4 rounded-lg shadow-sm">
        <p className="text-[10px] text-slate-500">Risk calc / factor data not available.</p>
      </div>
    );
  }

  const riskFlagEntry = riskCalc ? Object.entries(riskCalc).find(([k]) => k.toLowerCase() === 'risk_flag' || k.toLowerCase() === 'risk_flag_value') : undefined;
  const regularRiskEntries = riskCalc ? Object.entries(riskCalc).filter(([k]) => k.toLowerCase() !== 'risk_flag' && k.toLowerCase() !== 'risk_flag_value') : [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      {hasRisk && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
          <div className="bg-slate-100 px-4 py-2.5 border-b border-slate-200">
            <h4 className="text-[11px] font-bold text-slate-700 uppercase tracking-wider">Risk Calc</h4>
            <p className="text-[9px] text-slate-500 mt-0.5">Quantified risk metrics from live analysis.</p>
          </div>
          <div className="p-3 space-y-0">
            {riskFlagEntry && (
              <div className="flex items-center justify-between gap-3 py-2 border-b border-red-100 bg-red-50/40 -mx-3 px-3 mb-0">
                <span className="text-[10px] text-red-700 uppercase tracking-wider font-bold leading-tight">Risk Flag</span>
                <span className="text-[12px] text-red-700 font-black uppercase tracking-wider animate-pulse">{String(riskFlagEntry[1])}</span>
              </div>
            )}
            {regularRiskEntries.map(([label, value], idx, arr) => (
              <div key={label} className={`flex items-center justify-between gap-3 py-2 ${idx < arr.length - 1 ? 'border-b border-slate-100' : ''}`}>
                <span className="text-[10px] text-slate-500 uppercase tracking-wider leading-tight">{formatSnakeKey(label)}</span>
                <span className="text-[11px] text-slate-900 font-bold text-right leading-tight">{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasFactor && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
          <div className="bg-emerald-50 px-4 py-2.5 border-b border-emerald-100">
            <h4 className="text-[11px] font-bold text-emerald-700 uppercase tracking-wider">Factor Hub</h4>
            <p className="text-[9px] text-slate-500 mt-0.5">Active factor exposures and signals.</p>
          </div>
          <div className="p-3 space-y-0">
            {Object.entries(factorHub).map(([label, value], idx, arr) => (
              <div key={label} className={`py-2 ${idx < arr.length - 1 ? 'border-b border-emerald-50' : ''}`}>
                <div className="text-[9px] text-emerald-700 uppercase tracking-wider mb-0.5">{formatSnakeKey(label)}</div>
                <div className="text-[11px] text-slate-700 leading-relaxed">{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StructuredReasoningOutput({ intelligence }: { intelligence?: TerminalIntelligence }) {
  const hasData = !!intelligence;

  return (
    <div className="bg-slate-50 border border-slate-300 border-[0.5px] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Structured Reasoning Output</h3>
          <p className="text-[10px] text-slate-500 mt-0.5">Gemini / Pydantic mapped payload from the live ingestion stream.</p>
        </div>
        <div className="text-[10px] text-slate-500">{hasData ? 'Available' : 'Unavailable'}</div>
      </div>

      {hasData ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[10px] text-slate-700">
            <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">News Catalysts</div>
              <p className="text-[11px] text-slate-700 leading-relaxed">{intelligence.news_catalysts_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Macro Anchors</div>
              <p className="text-[11px] text-slate-700 leading-relaxed">{intelligence.macro_anchors_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Insider / Insti Activity</div>
              <p className="text-[11px] text-slate-700 leading-relaxed">{intelligence.insider_insti_activity_card ?? 'Not produced.'}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 text-[10px] text-slate-700 mt-3">
            <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Structural Thesis</div>
              <p className="text-[10px] text-slate-600 leading-relaxed">
                <span className="text-slate-700">Why Interested: </span>
                {intelligence.why_interested ?? 'Not produced.'}
              </p>
              <p className="text-[10px] text-slate-600 mt-1 leading-relaxed">
                <span className="text-slate-700">Forward Revenue: </span>
                {intelligence.future_revenue_model ?? 'Not produced.'}
              </p>
            </div>
            <div className="bg-white border border-emerald-200 border-[0.5px] rounded-xl overflow-hidden">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-2">Risk Calc / Factor Hub</div>
              <RiskCalcFactorHub
                riskCalc={
                  (intelligence.active_risk_calc as Record<string, unknown> | undefined) ?? undefined
                }
                factorHub={
                  (intelligence.active_factor_hub as Record<string, string> | undefined) ?? undefined
                }
              />
            </div>
          </div>
        </>
      ) : (
        <div className="text-slate-500 text-[10px]">
          Terminal intelligence is not currently generated. Start the backend with Gemini/OpenAI keys for structured JSON mapping.
        </div>
      )}
    </div>
  );
}

/* Sparkline helper used by GlobalIndicesGrid */
function SparklineSVG({ positive }: { positive: boolean }) {
  const color = positive ? '#10b981' : '#ef4444';
  const points = positive
    ? '5,48 15,44 25,42 35,38 45,36 55,32 65,30 75,26 85,24 95,20'
    : '5,15 15,20 25,25 35,30 45,35 55,40 65,42 75,45 85,48 95,50';
  return (
    <svg className="absolute top-0 right-0 w-14 h-14 opacity-15" viewBox="0 0 100 60">
      <polyline points={points} stroke={color} strokeWidth="1.5" fill="none" />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/*  MAIN COMPONENT                                                            */
/* -------------------------------------------------------------------------- */

export default function IrosMasterAdvancedTerminal() {
  const [terminalMode] = useState<'morning' | 'evening'>('morning');
  const [selectedPool, setSelectedPool] = useState<string>('Nifty 500');
  const [selectedTicker, setSelectedTicker] = useState<string>('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerContent, setDrawerContent] = useState<DrawerContent | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('marketSnapshot');
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  const { data: liveMarket, status: feedStatus, refreshOnDemand } = useMarketData(selectedPool);
  const stocks = liveMarket?.stocks ?? [];
  const selectedTickerForView = useMemo(() => selectedTicker || stocks[0]?.ticker || '', [selectedTicker, stocks]);

  const currentMacros = useMemo(() => {
    const macros = liveMarket?.macroDataStrip?.[terminalMode] ?? [];
    const globalIndices = liveMarket?.globalMacro?.indices ?? [];
    const seen = new Set(macros.map((item) => normalizeMarketLabel(item.label)));
    const indiaFromGlobal = globalIndices.filter((item) => INDIA_MARKET_LABELS.has(normalizeMarketLabel(item.label)));
    const merged = [
      ...macros.filter((item) => !GLOBAL_ONLY_LABELS.has(normalizeMarketLabel(item.label))),
      ...indiaFromGlobal.filter((item) => !seen.has(normalizeMarketLabel(item.label))),
    ];
    return merged;
  }, [terminalMode, liveMarket]);

  const globalIndices = useMemo(() => {
    const g = liveMarket?.globalMacro;
    if (!g) return [];
    return (g.indices ?? []).filter((item) => !INDIA_MARKET_LABELS.has(normalizeMarketLabel(item.label)));
  }, [liveMarket]);

  const commodities = useMemo(() => {
    const g = liveMarket?.globalMacro;
    if (!g) return [];
    return g.commodities ?? [];
  }, [liveMarket]);

  const marketIntelligence = liveMarket?.terminalIntelligence as TerminalIntelligence | undefined;
  const isSnapshotFallback = liveMarket?.isSnapshotFallback ?? false;
  const [tickerIntelligence, setTickerIntelligence] = useState<TerminalIntelligence | null>(null);

  const selectedQuote = useMemo(
    () => selectedTickerForView ? liveMarket?.stockQuotes?.[selectedTickerForView] ?? stocks.find((stock) => stock.ticker === selectedTickerForView) : undefined,
    [selectedTickerForView, liveMarket, stocks]
  );

  const handleSelect = async (t: string) => {
    setSelectedTicker(t);
    setDrawerOpen(true);

    const tickerIntelligence = liveMarket?.tickerIntelligenceByTicker?.[t];
    if (tickerIntelligence) {
      setTickerIntelligence(tickerIntelligence);
      setDrawerContent({
        stock: stocks.find((s) => s.ticker === t) ?? null,
        analysis: {
          ...tickerIntelligence,
          isSnapshotFallback: liveMarket?.isSnapshotFallback ?? false,
        },
      });
      return;
    }

    try {
      const params = new URLSearchParams();
      if (t) params.set("ticker", t);
      if (selectedPool) params.set("pool", selectedPool);
      const resp = await fetch(`/api/terminal-intelligence${params.toString() ? `?${params.toString()}` : ""}`);
      if (resp.ok) {
        const body = await resp.json();
        const ti = body.terminalIntelligence ?? body;
        setTickerIntelligence(ti);
        setDrawerContent({
          stock: stocks.find((s) => s.ticker === t) ?? null,
          analysis: { ...ti, isSnapshotFallback: body.isSnapshotFallback },
        });
      } else {
        const text = await resp.text();
        setDrawerContent({ stock: stocks.find((s) => s.ticker === t) ?? null, analysis: { error: text } });
      }
    } catch (err) {
      setDrawerContent({ stock: stocks.find((s) => s.ticker === t) ?? null, analysis: { error: String(err) } });
    }
  };

  const handleRefresh = async () => {
    await refreshOnDemand();
  };

  const snapshotAgeMin = liveMarket?.updatedAt ? Math.round((now - new Date(liveMarket.updatedAt).getTime()) / 60000) : null;
  const staleMacroLabel = snapshotAgeMin == null ? "" : `STALE ${snapshotAgeMin}M`;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-50 text-slate-900 font-mono text-xs antialiased">
      <div className="max-w-[1600px] mx-auto p-4 space-y-4">
        <header className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm">
          <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={`w-2.5 h-2.5 rounded-full ${feedStatus === 'live' ? 'bg-emerald-500 animate-pulse' : feedStatus === 'loading' ? 'bg-amber-500' : 'bg-red-500'}`} />
                <h1 className="text-sm font-black tracking-wider text-slate-900">IROS Live Market Intelligence</h1>
              </div>
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider xl:hidden">Nifty 500</span>
            </div>

            <div className="flex items-center justify-between xl:justify-end gap-3">
              <span className="text-[10px] font-bold uppercase text-slate-500 hidden xl:inline tracking-wider">
                {liveMarket?.rawSources?.join(' · ') ?? 'Reuters · TradingView · Moneycontrol'}
              </span>
              <div className="flex items-center gap-2 text-[10px] text-slate-500">
                <span className="hidden sm:inline">
                  {liveMarket?.updatedAt ? new Date(liveMarket.updatedAt).toLocaleTimeString() : '--:--'} IST
                </span>
                <button
                  onClick={handleRefresh}
                  disabled={feedStatus === 'loading'}
                  className="px-3 py-1.5 rounded-full bg-teal-600 text-white text-[10px] font-black uppercase tracking-wider hover:bg-teal-500 disabled:opacity-50 transition"
                >
                  Refresh
                </button>
              </div>
            </div>
          </div>

          {isSnapshotFallback && (
            <div className="px-4 pb-3">
              <div className="bg-amber-50 text-amber-800 border border-amber-200 p-2 rounded text-[11px]">
                Snapshot fallback active — outside scheduled IST refresh window. Showing latest saved analysis.
              </div>
            </div>
          )}
        </header>

        <nav className="bg-white border border-slate-300 border-[0.5px] rounded-xl flex gap-1 p-1 shadow-sm">
          {([
            { key: 'marketSnapshot' as TabKey, label: 'MARKET SNAPSHOT' },
            { key: 'assetMatrix' as TabKey, label: 'ASSET MATRIX' },
          ]).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-2 text-[11px] font-bold uppercase tracking-wider rounded-lg transition relative ${
                activeTab === tab.key ? 'text-teal-700' : 'text-slate-400 hover:text-slate-600'
              }`}
            >
              {activeTab === tab.key && (
                <span className="absolute inset-x-2 -bottom-0.5 h-0.5 bg-teal-600 rounded-full" />
              )}
              {tab.label}
            </button>
          ))}
        </nav>

        {activeTab === 'marketSnapshot' && (
          <div className="space-y-4">
            {/* Row 1: Global Indices + Commodities side-by-side */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2">
                <GlobalIndicesGrid items={globalIndices} staleLabel={staleMacroLabel} />
              </div>
              <div>
                <CommoditiesFxGrid items={commodities} staleLabel={staleMacroLabel} />
              </div>
            </div>

            {/* Row 2: NIFTY TOP 5 GAINERS & LOSERS + NIFTY 100 HEAT MAP side-by-side */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <GainersLosersHeatmap stockQuotes={liveMarket?.stockQuotes} />
              <Nifty100HeatMap stockQuotes={liveMarket?.stockQuotes} />
            </div>

            {/* Row 3: News Feed */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <NewsFeedPanel items={liveMarket?.news} now={now} />
            </div>

            {/* Row 4: India Markets — Top Movers */}
            <IndiaMarketsGrid items={currentMacros} staleLabel={staleMacroLabel} />
          </div>
        )}

        {activeTab === 'assetMatrix' && (
          <div className="space-y-4">
            <ForensicPanel
              onSelect={handleSelect}
              liveMarket={liveMarket}
              refreshOnDemand={refreshOnDemand}
            />
            <StockDetailPanel stock={selectedQuote} />
            <LiveIntelligencePanel />
          </div>
        )}
      </div>

      <RightDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} content={drawerContent} />
    </div>
  );
}