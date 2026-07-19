'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  useMarketData,
  type LiveStock,
  type MacroRow,
  type LedgerStock,
  type TerminalIntelligence,
  type AITickerNewsReport,
} from '@/lib/market-api';
import ForensicPanel from './components/ForensicPanel';
import RightDrawer from './components/RightDrawer';
import IntradayMatrixPanel from './components/IntradayMatrixPanel';

type DrawerContent = {
  stock?: LiveStock | LedgerStock | null;
  analysis?: (TerminalIntelligence & {
    isSnapshotFallback?: boolean;
    error?: string;
  }) | null;
  tickerNews?: AITickerNewsReport | null;
};

type TabKey = 'marketSnapshot' | 'stockHeatMap' | 'assetMatrix' | 'intradayMatrix';

const INDIA_MARKET_LABELS = new Set(['NIFTY 100', 'SENSEX', 'NIFTY BANK', 'NIFTY IT', 'NIFTY PHARMA', 'NIFTY MIDCAP', 'NIFTY SMALLCAP', 'GIFT NIFTY']);
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
/*  Helper: parse delta string like "+2.73" or "-3.12"                      */
/* -------------------------------------------------------------------------- */
function parseDeltaPct(delta: string | undefined): number {
  if (!delta) return 0;
  const cleaned = delta.replace('%', '').replace(',', '');
  return parseFloat(cleaned) || 0;
}

type TrendlyneScreenKey = 'risingDelivery' | 'topLosersVolume' | 'volumeShockers' | 'highVolumeGain' | 'highVolumeLoss' | 'outPerformanceWeek';

type TrendlyneStock = {
  name: string;
  value: string;
  stockurl: string;
  tooltipParams: Array<{ name: string; key: string; value: string }>;
};

type TrendlyneScreenData = {
  screen: {
    description: string;
    title: string;
  };
  isNextPage: boolean;
  screenData: TrendlyneStock[];
};

const TRENDLYNE_SCREENS: { key: TrendlyneScreenKey; label: string; accent: 'emerald' | 'red' | 'amber' | 'indigo' }[] = [
  { key: 'risingDelivery', label: 'RISING DELIVERY %', accent: 'emerald' },
  { key: 'topLosersVolume', label: 'TOP LOSERS BY VOLUME', accent: 'red' },
  { key: 'volumeShockers', label: 'VOLUME SHOCKERS', accent: 'amber' },
  { key: 'highVolumeGain', label: 'HIGH VOLUME/GAIN', accent: 'emerald' },
  { key: 'highVolumeLoss', label: 'HIGH VOLUME/LOSS', accent: 'red' },
  { key: 'outPerformanceWeek', label: 'OUTPERFORMANCE /WEEK', accent: 'indigo' },
];

type NseTopFiveCategoryKey = 'topGainers' | 'topLoosers' | 'mostActiveValue' | 'mostActiveVolume';

type NseTopFiveCategory = {
  label: string;
  flag: 'G' | 'L' | 'MAVA' | 'MAVO';
  key: NseTopFiveCategoryKey;
};

type NseStock = Record<string, unknown> & {
  symbol?: string;
  lastPrice?: number;
  pchange?: number;
};

type NseTopFiveResponse = {
  data?: {
    topGainers?: NseStock[];
    topLoosers?: NseStock[];
    mostActiveValue?: NseStock[];
    mostActiveVolume?: NseStock[];
    timestamp?: string;
  };
};

type NseEquityStock = Record<string, unknown> & {
  symbol?: string;
  pChange?: number;
};

type NseEquityStockIndicesResponse = {
  data?: NseEquityStock[];
};

const NSE_TOP_FIVE_CATEGORIES: NseTopFiveCategory[] = [
  { label: 'TOP GAINERS', flag: 'G', key: 'topGainers' },
  { label: 'TOP LOSERS', flag: 'L', key: 'topLoosers' },
  { label: 'MOST ACTIVE', flag: 'MAVA', key: 'mostActiveValue' },
  { label: 'HIGHEST VOLUME', flag: 'MAVO', key: 'mostActiveVolume' },
];

function formatNseNumber(value: number | undefined) {
  if (typeof value !== 'number') return 'N/A';
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

function formatNseValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') return formatNseNumber(value);
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function formatNseFieldValue(key: string, value: unknown) {
  if (typeof value === 'number' && key === 'totalTradedVolume') return `${(value / 100000).toFixed(2)} Lakhs`;
  if (typeof value === 'number' && key === 'totalTradedValue') return `${(value / 10000000).toFixed(2)} Cr.`;
  return formatNseValue(value);
}

function getNseGraphSrc(data: Record<string, unknown>) {
  if (typeof data.chart30dPath === 'string' && data.chart30dPath) return data.chart30dPath;
  if (typeof data.chart365dPath === 'string' && data.chart365dPath) return data.chart365dPath;
  return null;
}

function formatNseKey(key: string) {
  return key.replace(/([A-Z])/g, ' $1').replace(/^./, (letter) => letter.toUpperCase());
}

function getCategoryAccentClass(categoryKey: NseTopFiveCategoryKey) {
  if (categoryKey === 'topGainers') return 'text-emerald-600';
  if (categoryKey === 'topLoosers') return 'text-red-500';
  return 'text-slate-600';
}

function getCategoryDotClass(categoryKey: NseTopFiveCategoryKey) {
  if (categoryKey === 'topGainers') return 'bg-emerald-500';
  if (categoryKey === 'topLoosers') return 'bg-red-500';
  return 'bg-slate-500';
}

function getCategoryRowStyle(categoryKey: NseTopFiveCategoryKey): React.CSSProperties {
  if (categoryKey === 'topGainers') {
    return { backgroundColor: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.2)' };
  }
  if (categoryKey === 'topLoosers') {
    return { backgroundColor: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.2)' };
  }
  return { backgroundColor: 'rgba(15, 23, 42, 0.03)', border: '1px solid rgba(148, 163, 184, 0.2)' };
}

function getNseStocks(response: NseTopFiveResponse, key: NseTopFiveCategoryKey) {
  const stocks = response.data?.[key];
  if (!Array.isArray(stocks)) return [];
  return stocks.filter((stock): stock is NseStock => stock !== null && typeof stock === 'object');
}

async function fetchNseTopFiveStock(flag: NseTopFiveCategory['flag']) {
  const params = new URLSearchParams();
  params.set('flag', flag);
  params.set('index', 'NIFTY 500');
  const res = await fetch(`/api/nse-top-five-stock?${params.toString()}`, { cache: 'no-store' });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(detail || `NSE API HTTP ${res.status}`);
  }
  return (await res.json()) as NseTopFiveResponse;
}

function getNseHeatMapStocks(response: NseEquityStockIndicesResponse) {
  const stocks = response.data ?? [];
  if (!Array.isArray(stocks)) return [];
  return stocks.filter((stock): stock is NseEquityStock => {
    if (stock === null || typeof stock !== 'object') return false;
    return stock.symbol !== 'NIFTY 200' && typeof stock.pChange === 'number';
  });
}

async function fetchNseEquityStockIndices() {
  const params = new URLSearchParams();
  params.set('index', 'NIFTY 200');
  const res = await fetch(`/api/nse-equity-stock-indices?${params.toString()}`, { cache: 'no-store' });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(detail || `NSE API HTTP ${res.status}`);
  }
  return (await res.json()) as NseEquityStockIndicesResponse;
}

/* -------------------------------------------------------------------------- */
/*  Adaptive tooltip hook - positions tooltip near trigger element             */
/* -------------------------------------------------------------------------- */

function useAdaptiveTooltip() {
  const triggerRef = useRef<HTMLDivElement | HTMLSpanElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  const cancelClose = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };

  const scheduleClose = () => {
    closeTimer.current = setTimeout(() => setVisible(false), 200);
  };

  const showTooltip = () => {
    cancelClose();
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const viewportW = window.innerWidth;
      const viewportH = window.innerHeight;
      const tooltipW = 240;
      const tooltipH = 200;

      // Default: position below the trigger
      let top = rect.bottom + 8;
      let left = rect.left + rect.width / 2 - tooltipW / 2;

      // If below would overflow, position above
      if (top + tooltipH > viewportH) {
        top = rect.top - tooltipH - 8;
      }

      // If left would overflow, align to left edge
      if (left < 8) left = 8;
      // If right would overflow, align to right edge
      if (left + tooltipW > viewportW - 8) {
        left = viewportW - tooltipW - 8;
      }

      // If still out of viewport (very small screen), center horizontally
      if (left < 8 && viewportW < tooltipW + 16) {
        left = 8;
      }

      setPosition({ top, left });
    }
    setVisible(true);
  };

  return { triggerRef, visible, position, setVisible, showTooltip, scheduleClose, cancelClose, mounted };
}

/* -------------------------------------------------------------------------- */
/*  Mini sparkline component                                                    */
/* -------------------------------------------------------------------------- */

function MiniSparkline({ positive }: { positive: boolean }) {
  const color = positive ? '#10b981' : '#ef4444';
  const id = `mini-${positive ? 'g' : 'r'}-${Math.random().toString(36).slice(2, 6)}`;
  const fillUrl = 'url(#' + id + ')';

  let pathD: string;
  let areaD: string;
  if (positive) {
    pathD = 'M 0,25 C 20,22 30,24 50,18 C 70,12 80,8 100,4';
    areaD = 'M 0,25 C 20,22 30,24 50,18 C 70,12 80,8 100,4 L 100,30 L 0,30 Z';
  } else {
    pathD = 'M 0,5 C 20,8 30,6 50,12 C 70,18 80,22 100,26';
    areaD = 'M 0,5 C 20,8 30,6 50,12 C 70,18 80,22 100,26 L 100,30 L 0,30 Z';
  }

  return (
    <svg className="w-full h-8" viewBox="0 0 100 30" preserveAspectRatio="none">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={fillUrl} />
      <path d={pathD} stroke={color} strokeWidth="0.75" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/*  NseTooltipContent - shared tooltip content for NSE stocks                   */
/* -------------------------------------------------------------------------- */

function NseTooltipContent({ data }: { data: Record<string, unknown> }) {
  const graphSrc = getNseGraphSrc(data);
  const pchange = typeof data.pchange === 'number' ? data.pchange : (typeof data.pChange === 'number' ? data.pChange : null);
  const positive = pchange !== null && pchange >= 0;

  return (
    <div>
      {/* Sparkline header */}
      <div className="mb-2 rounded-t-lg p-1.5" style={{ background: positive ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)' }}>
        <MiniSparkline positive={positive} />
      </div>

      {graphSrc && (
        <div className="mb-2 rounded-lg border border-slate-200 bg-white shadow-sm p-1.5 transition-transform hover:scale-[1.01]">
          <div className="mb-1 flex items-center justify-between text-[8px] uppercase tracking-wider text-slate-400 font-bold">
            <span className="flex items-center gap-1">
              <span className="w-1 h-1 rounded-full bg-teal-500 animate-pulse" />
              Price Chart
            </span>
            <span className="text-teal-600">30D</span>
          </div>
          <img src={graphSrc} alt="NSE chart" className="h-16 w-full rounded object-contain bg-white" />
        </div>
      )}

      <div className="space-y-0.5">
        {Object.entries(data).map(([key, value]) => {
          const isPrice = key === 'lastPrice' || key === 'lastCorpAnnouncementPrice';
          const isChange = key === 'pchange' || key === 'pChange';
          const accentClass = isPrice ? 'text-slate-900 font-bold' : isChange ? (positive ? 'text-emerald-600' : 'text-red-500') : 'text-slate-500';
          return (
            <div key={key} className="group flex items-center justify-between gap-3 px-2 py-1 rounded-md transition-all hover:bg-slate-50 hover:scale-[1.01]">
              <div className="text-[8px] uppercase tracking-wider text-slate-400 font-semibold truncate">{formatNseKey(key)}</div>
              <div className={`text-[9px] font-mono text-right ${accentClass} transition-colors`}>{formatNseFieldValue(key, value)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Shared adaptive tooltip portal component                                    */
/* -------------------------------------------------------------------------- */

function AdaptiveTooltipPortal({
  visible,
  position,
  mounted,
  positive,
  ticker,
  pchange,
  stock,
  onMouseEnter,
  onMouseLeave,
}: {
  visible: boolean;
  position: { top: number; left: number };
  mounted: boolean;
  positive: boolean | null;
  ticker: string;
  pchange: number | null;
  stock: Record<string, unknown>;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}) {
  if (!visible || !mounted) return null;

  return createPortal(
    <div
      style={{
        position: 'fixed',
        zIndex: 9999,
        maxWidth: '240px',
        maxHeight: '50vh',
        top: position.top,
        left: position.left,
        borderRadius: '10px',
        border: '1px solid #e2e8f0',
        background: 'white',
        padding: '10px',
        boxShadow: positive !== null
          ? (positive
              ? '0 8px 32px rgba(16,185,129,0.15), 0 2px 8px rgba(0,0,0,0.06)'
              : '0 8px 32px rgba(239,68,68,0.15), 0 2px 8px rgba(0,0,0,0.06)')
          : '0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)',
        overflowY: 'auto',
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-center gap-2 mb-2 flex-shrink-0">
        <span className={`w-1.5 h-1.5 rounded-full ${positive !== null ? (positive ? 'bg-emerald-500' : 'bg-red-500') : 'bg-slate-400'} animate-pulse`} />
        <span className={`text-[9px] uppercase tracking-widest font-bold ${positive !== null ? (positive ? 'text-emerald-600' : 'text-red-500') : 'text-slate-500'}`}>
          {ticker} · NSE
        </span>
        {pchange !== null && (
          <span className={`ml-auto text-[10px] font-black tabular-nums ${positive ? 'text-emerald-600' : 'text-red-500'}`}>
            {positive ? '↑' : '↓'} {pchange > 0 ? '+' : ''}{pchange.toFixed(2)}
          </span>
        )}
      </div>
      <NseTooltipContent data={stock} />
    </div>,
    document.body
  );
}

/* -------------------------------------------------------------------------- */
/*  NseTickerTooltip - tooltip for top gainers/losers stocks with adaptive pos  */
/* -------------------------------------------------------------------------- */

function NseTickerTooltip({ stock, ticker }: { stock: NseStock; ticker: string }) {
  const { triggerRef, visible, position, showTooltip, scheduleClose, cancelClose, mounted } = useAdaptiveTooltip();

  const pchange = typeof stock.pchange === 'number' ? stock.pchange : null;
  const positive = pchange !== null && pchange >= 0;
  const symbol = (typeof stock.symbol === 'string' ? stock.symbol : ticker) || ticker;

  const handleClick = () => {
    const nseUrl = `https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(symbol)}`;
    window.open(nseUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <>
      <span
        ref={triggerRef as React.RefObject<HTMLSpanElement | null>}
        className={`text-[12px] font-bold cursor-pointer transition-colors ${positive !== null ? (positive ? 'text-emerald-700 hover:text-emerald-500' : 'text-red-700 hover:text-red-500') : 'text-slate-800'}`}
        onClick={handleClick}
        onKeyDown={(e) => { if (e.key === 'Enter') handleClick(); }}
        onMouseEnter={showTooltip}
        onMouseLeave={scheduleClose}
        onFocus={showTooltip}
        onBlur={() => { cancelClose(); }}
        tabIndex={0}
      >
        {ticker}
      </span>
      <AdaptiveTooltipPortal
        visible={visible}
        position={position}
        mounted={mounted}
        positive={positive}
        ticker={ticker}
        pchange={pchange}
        stock={stock}
        onMouseEnter={() => { cancelClose(); }}
        onMouseLeave={scheduleClose}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  TrendlyneCategoryPanel                                                      */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/*  TrendlyneTickerTooltip - tooltip for Trendlyne screener stocks             */
/* -------------------------------------------------------------------------- */

function TrendlyneTickerTooltip({ item }: { item: TrendlyneStock }) {
  const { triggerRef, visible, position, showTooltip, scheduleClose, cancelClose, mounted } = useAdaptiveTooltip();

  return (
    <>
      <span
        ref={triggerRef as React.RefObject<HTMLSpanElement | null>}
        className="text-[12px] font-bold text-slate-800 truncate cursor-pointer hover:text-indigo-600 transition-colors"
        onMouseEnter={showTooltip}
        onMouseLeave={scheduleClose}
        onFocus={showTooltip}
        onBlur={() => { cancelClose(); }}
        tabIndex={0}
      >
        {item.name}
      </span>
      {visible && mounted && (
        <div
          style={{
            position: 'fixed',
            zIndex: 9999,
            maxWidth: '340px',
            maxHeight: '85vh',
            top: position.top,
            left: position.left,
            borderRadius: '12px',
            border: '1px solid #e2e8f0',
            background: 'white',
            padding: '14px',
            boxShadow: '0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)',
            overflowY: 'auto',
          }}
          onMouseEnter={() => { cancelClose(); }}
          onMouseLeave={scheduleClose}
        >
          <div className="flex items-center gap-2 mb-2 flex-shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse" />
            <span className="text-[9px] uppercase tracking-widest font-bold text-slate-500">
              {item.name} · TRENDLYNE
            </span>
          </div>
          <div className="space-y-0.5">
            {item.tooltipParams.map((param) => (
              <div key={param.key} className="group flex items-center justify-between gap-3 px-2 py-1 rounded-md transition-all hover:bg-slate-50 hover:scale-[1.01]">
                <div className="text-[8px] uppercase tracking-wider text-slate-400 font-semibold truncate">{param.name}</div>
                <span className="text-[9px] font-mono text-right text-slate-900 font-bold">{param.value || '—'}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function TrendlyneCategoryPanel({ screenKey, label, accentClass }: { screenKey: TrendlyneScreenKey; label: string; accentClass: string }) {
  const [items, setItems] = useState<TrendlyneStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/trendlyne-screener?screen=${screenKey}`, { cache: 'no-store' });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data: TrendlyneScreenData = await res.json();
      setItems(data.screenData?.slice(0, 5) ?? []);
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Trendlyne unavailable');
      setLoading(false);
    }
  }, [screenKey]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      await fetchData();
      if (cancelled) return;
    };
    void load();
    const id = window.setInterval(() => { if (!cancelled) fetchData(); }, 900_000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [fetchData]);

  const dotCls = accentClass === 'emerald' ? 'bg-emerald-500' : accentClass === 'red' ? 'bg-red-500' : accentClass === 'indigo' ? 'bg-indigo-500' : 'bg-amber-500';
  const textAccentCls = accentClass === 'emerald' ? 'text-emerald-600' : accentClass === 'red' ? 'text-red-500' : accentClass === 'indigo' ? 'text-indigo-600' : 'text-amber-600';

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-2 min-h-[160px] overflow-visible shadow-sm">
      <div className={`text-[13px] uppercase tracking-wider ${textAccentCls} font-bold mb-2 flex items-center gap-1.5`}>
        <span className={`w-2 h-2 rounded-full ${dotCls}`} />
        {label}
      </div>
      {error && items.length === 0 && (
        <div className="text-[11px] text-red-500 px-2 py-1 mb-1">{error}</div>
      )}
      <div className="space-y-0">
        {items.length === 0 && !loading && !error && (
          <div className="text-[13px] text-slate-400 px-2 py-1">No data</div>
        )}
        {items.map((item, idx) => {
          const currentPrice = item.tooltipParams.find((p) => p.key === 'currentPrice')?.value ?? '—';
          return (
            <a
              key={`${screenKey}-${item.name}-${idx}`}
              href={item.stockurl}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-center justify-between py-1.5 cursor-pointer border-b border-slate-100 last:border-b-0 hover:bg-slate-50 transition-colors"
            >
              <div className="flex-1 min-w-0 flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${dotCls} flex-shrink-0`} />
                <TrendlyneTickerTooltip item={item} />
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className={`text-[13px] font-bold ${textAccentCls}`}>{item.value}</span>
                <span className="text-[13px] text-slate-500">₹{currentPrice}</span>
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  GainersLosersHeatmap                                                         */
/* -------------------------------------------------------------------------- */

function GainersLosersHeatmap() {
  const [categories, setCategories] = useState<Record<NseTopFiveCategoryKey, NseStock[]>>({
    topGainers: [],
    topLoosers: [],
    mostActiveValue: [],
    mostActiveVolume: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadCategories = async () => {
      setLoading(true);
      setError(null);
      try {
        const responses = await Promise.all(
          NSE_TOP_FIVE_CATEGORIES.map(async (category) => ({
            category,
            stocks: getNseStocks(await fetchNseTopFiveStock(category.flag), category.key),
          }))
        );
        if (cancelled) return;

        const nextCategories = NSE_TOP_FIVE_CATEGORIES.reduce<Record<NseTopFiveCategoryKey, NseStock[]>>(
          (acc, category) => {
            const response = responses.find((item) => item.category.key === category.key);
            acc[category.key] = response?.stocks ?? [];
            return acc;
          },
          { topGainers: [], topLoosers: [], mostActiveValue: [], mostActiveVolume: [] }
        );

        setCategories(nextCategories);
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'NSE API unavailable');
          setLoading(false);
        }
      }
    };

    void loadCategories();
    const id = window.setInterval(loadCategories, 900_000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const totalStocks = useMemo(
    () => NSE_TOP_FIVE_CATEGORIES.reduce((sum, category) => sum + (categories[category.key]?.length ?? 0), 0),
    [categories]
  );

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-2.5 shadow-sm min-h-[160px] overflow-visible">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[12px] uppercase tracking-wider text-slate-500 font-bold">NIFTY TOP 5 GAINERS & LOSERS</span>
        <span className="text-[12px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
          {loading ? 'LOADING' : error ? 'ERROR' : `${totalStocks} stocks`}
        </span>
      </div>
      {error && totalStocks === 0 && (
        <div className="text-[9px] text-red-500 px-2 py-1 mb-1">{error}</div>
      )}
      <div className="grid grid-cols-5 gap-1.5">
        {NSE_TOP_FIVE_CATEGORIES.map((category) => {
          const stocks = categories[category.key] ?? [];
          const accentClass = getCategoryAccentClass(category.key);
          const dotClass = getCategoryDotClass(category.key);

          return (
            <div key={category.key} className="bg-white border border-slate-200 rounded-lg p-2 min-h-[160px] overflow-visible shadow-sm">
              <div className={`text-[13px] uppercase tracking-wider ${accentClass} font-bold mb-2 flex items-center gap-1.5`}>
                <span className={`w-2 h-2 rounded-full ${dotClass}`} />
                {category.label}
              </div>
              <div className="space-y-0">
                {stocks.length === 0 && (
                  <div className="text-[13px] text-slate-400 px-2 py-1">No data</div>
                )}
                {stocks.map((stock, index) => {
                  const ticker = stock.symbol ?? 'UNKNOWN';
                  const changeText = typeof stock.pchange === 'number' ? `${stock.pchange > 0 ? '+' : ''}${stock.pchange.toFixed(2)}` : 'N/A';
                  const changeClass = typeof stock.pchange === 'number' ? (stock.pchange >= 0 ? 'text-emerald-600' : 'text-red-500') : 'text-slate-500';

                  return (
                    <div
                      key={`${category.key}-${ticker}-${index}`}
                      className="group flex items-center justify-between py-1.5 cursor-default border-b border-slate-100 last:border-b-0"
                    >
                      <div className="flex-1 min-w-0">
                        <NseTickerTooltip stock={stock} ticker={ticker} />
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className="text-[13px] text-slate-600 font-medium tabular-nums">₹{formatNseNumber(stock.lastPrice)}</span>
                        <span className={`text-[13px] font-bold tabular-nums min-w-[60px] text-right ${changeClass}`}>{changeText}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        <TrendlyneCategoryPanel screenKey={TRENDLYNE_SCREENS[0].key} label={TRENDLYNE_SCREENS[0].label} accentClass={TRENDLYNE_SCREENS[0].accent} />
      </div>

      {/* NIFTY SCREENERS Panels */}
      <div className="flex items-center gap-1.5 mb-1.5 mt-2">
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
        <span className="text-[12px] uppercase tracking-wider text-slate-500 font-bold">NIFTY SCREENERS</span>
      </div>
      {/* Remaining 5 Trendlyne screens in one row */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-1.5">
        {TRENDLYNE_SCREENS.slice(1).map((screen) => (
          <TrendlyneCategoryPanel key={screen.key} screenKey={screen.key} label={screen.label} accentClass={screen.accent} />
        ))}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  NIFTY 100 HEAT MAP (live from NSE equity stock indices)                   */
/* -------------------------------------------------------------------------- */
function getReadableTextColor(r: number, g: number, b: number): string {
  const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  return luminance > 0.52 ? 'rgb(15, 23, 42)' : 'rgb(255, 255, 255)';
}

function getHeatColor(pct: number): { bg: string; text: string; border: string } {
  const abs = Math.min(Math.abs(pct) / 4, 1);
  if (pct > 0) {
    const r = Math.round(220 - abs * 160);
    const g = Math.round(245 - abs * 65);
    const b = Math.round(220 - abs * 140);
    return {
      bg: `rgba(${r}, ${g}, ${b}, 0.85)`,
      text: getReadableTextColor(r, g, b),
      border: `rgba(16, 185, 129, ${0.2 + abs * 0.4})`,
    };
  } else {
    const absVal = Math.abs(pct) / 4;
    const r = Math.round(245 - absVal * 25);
    const g = Math.round(220 - absVal * 170);
    const b = Math.round(220 - absVal * 170);
    return {
      bg: `rgba(${r}, ${g}, ${b}, 0.85)`,
      text: getReadableTextColor(r, g, b),
      border: `rgba(239, 68, 68, ${0.2 + absVal * 0.4})`,
    };
  }
}

/* -------------------------------------------------------------------------- */
/*  Adaptive heat map tooltip with adaptive positioning                         */
/* -------------------------------------------------------------------------- */

function NseHeatMapTooltip({ stock, ticker, colors }: { stock: NseEquityStock; ticker: string; colors: { bg: string; text: string; border: string } }) {
  const { triggerRef, visible, position, showTooltip, scheduleClose, cancelClose, mounted } = useAdaptiveTooltip();

  const pchange = typeof stock.pChange === 'number' ? stock.pChange : null;
  const positive = pchange !== null && pchange >= 0;
  const symbol = stock.symbol ?? ticker;

  const handleClick = () => {
    const nseUrl = `https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(symbol)}`;
    window.open(nseUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <>
      <div
        ref={triggerRef as React.RefObject<HTMLDivElement | null>}
        className="flex flex-col items-center justify-center rounded-md py-1.5 px-1.5 transition-all duration-300 hover:shadow-xl hover:scale-110 cursor-pointer group relative"
        style={{
          backgroundColor: colors.bg,
          border: `2px solid ${colors.border}`,
        }}
        onClick={handleClick}
        onMouseEnter={showTooltip}
        onMouseLeave={scheduleClose}
        onFocus={showTooltip}
        onBlur={() => { cancelClose(); }}
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') handleClick(); }}
      >
        <span className="text-[9px] font-bold leading-tight relative z-10" style={{ color: colors.text }}>
          {ticker}
        </span>
        <span className="text-[8px] font-semibold mt-0.5 relative z-10" style={{ color: colors.text }}>
          {typeof stock.pChange === 'number' ? `${stock.pChange > 0 ? '+' : ''}${stock.pChange.toFixed(2)}` : 'N/A'}
        </span>
      </div>
      <AdaptiveTooltipPortal
        visible={visible}
        position={position}
        mounted={mounted}
        positive={positive}
        ticker={ticker}
        pchange={pchange}
        stock={stock}
        onMouseEnter={() => { cancelClose(); }}
        onMouseLeave={scheduleClose}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  Nifty100HeatMap - SORTED by gainers first, then losers                     */
/* -------------------------------------------------------------------------- */

function Nifty100HeatMap() {
  const [stocks, setStocks] = useState<NseEquityStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadStocks = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetchNseEquityStockIndices();
        if (cancelled) return;
        setStocks(getNseHeatMapStocks(response));
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'NSE API unavailable');
          setLoading(false);
        }
      }
    };

    void loadStocks();
    const id = window.setInterval(loadStocks, 900_000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Sorted heat map: gainers first (descending by change), then losers (ascending by change)
  const heatMapStocks = useMemo(() => {
    const mapped = stocks.map((stock) => ({
      stock,
      ticker: stock.symbol ?? 'UNKNOWN',
      changePct: typeof stock.pChange === 'number' ? stock.pChange : 0,
    }));
    // Sort: gainers (change >= 0) first descending by change, then losers ascending by change
    return mapped.sort((a, b) => {
      const aIsGainer = a.changePct >= 0;
      const bIsGainer = b.changePct >= 0;
      if (aIsGainer && !bIsGainer) return -1;
      if (!aIsGainer && bIsGainer) return 1;
      if (aIsGainer && bIsGainer) return b.changePct - a.changePct;
      return a.changePct - b.changePct; // losers: most negative last
    });
  }, [stocks]);

  const gainers = useMemo(() => heatMapStocks.filter(s => s.changePct >= 0).length, [heatMapStocks]);
  const losers = useMemo(() => heatMapStocks.filter(s => s.changePct < 0).length, [heatMapStocks]);

  if (loading || (error && heatMapStocks.length === 0)) {
    return (
      <div className="bg-gradient-to-br from-white to-slate-50 border border-slate-300 border-[0.5px] rounded-xl p-4 shadow-lg min-h-[400px]">
        <div className="flex flex-col items-center justify-center h-full">
          <div className="w-12 h-12 rounded-full bg-gradient-to-br from-teal-400 to-blue-500 animate-spin mb-3 shadow-lg" />
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">NIFTY 100 HEAT MAP</div>
          <div className="text-[10px] text-slate-400">{error ?? 'Waiting for live data...'}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gradient-to-br from-white via-slate-50/30 to-white border border-slate-300 border-[0.5px] rounded-xl p-3 shadow-lg">
      {/* Header */}
      <div className="relative mb-2">
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-teal-400 via-blue-400 to-purple-400 rounded-t-xl" />
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-2">
            <div className="relative">
              <div className="w-6 h-6 rounded-xl bg-gradient-to-br from-teal-500 to-blue-600 flex items-center justify-center shadow-lg">
                <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
            </div>
            <div>
              <h3 className="text-[10px] font-black text-slate-900 uppercase tracking-wider">NIFTY 100 HEAT MAP</h3>
              <p className="text-[7px] text-slate-500">Sorted by gainers / losers</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="px-1.5 py-0.5 rounded-lg bg-gradient-to-r from-slate-100 to-slate-50 border border-slate-200">
              <span className="text-[8px] text-slate-600 font-semibold">{heatMapStocks.length} stocks</span>
            </div>
            <div className="flex items-center gap-1 text-[7px] uppercase tracking-wider">
              <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-lg bg-emerald-50 border border-emerald-200">
                <div className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-emerald-700 font-bold">{gainers}</span>
                <span className="text-emerald-600">Gainers</span>
              </div>
              <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-lg bg-red-50 border border-red-200">
                <div className="w-1 h-1 rounded-full bg-red-500 animate-pulse" />
                <span className="text-red-700 font-bold">{losers}</span>
                <span className="text-red-600">Losers</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Heat Map Grid */}
      <div className="relative">
        <div className="absolute inset-0 bg-gradient-to-br from-teal-50/30 via-blue-50/20 to-purple-50/30 rounded-lg blur-2xl opacity-60" />
        <div className="relative grid grid-cols-5 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 xl:grid-cols-12 gap-1">
          {heatMapStocks.map((stock, index) => {
            const colors = getHeatColor(stock.changePct);
            return (
              <div
                key={stock.ticker}
                className="animate-fadeIn"
                style={{ animationDelay: `${index * 15}ms` }}
              >
                <NseHeatMapTooltip
                  stock={stock.stock}
                  ticker={stock.ticker}
                  colors={colors}
                />
              </div>
            );
          })}
        </div>
      </div>

      <style>{`
        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: scale(0.9) translateY(10px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
        .animate-fadeIn {
          animation: fadeIn 0.5s ease-out forwards;
          opacity: 0;
        }
      `}</style>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  GlobalIndicesGrid                                                            */
/* -------------------------------------------------------------------------- */

function GlobalIndicesGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-3 text-slate-400 text-[11px] shadow-sm">
        Waiting for global macro data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">GLOBAL INDICES</span>
        {staleLabel && <span className="text-[10px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-1.5">
        {items.map((item) => {
          const isPositive = item.state === 'POSITIVE';
          const gradient = getGlobalIndexGradient(item.label);
          return (
            <div
              key={item.label}
              className="relative overflow-hidden rounded-lg p-2.5 transition-all hover:scale-105 flex items-center gap-2 cursor-pointer"
              style={{
                background: gradient.background,
                border: gradient.border,
                minHeight: '80px',
              }}
              onClick={() => window.open(getIndexClickUrl(item.label), '_blank', 'noopener,noreferrer')}
              onKeyDown={(e) => { if (e.key === 'Enter') window.open(getIndexClickUrl(item.label), '_blank', 'noopener,noreferrer'); }}
              tabIndex={0}
              role="link"
              aria-label={`View ${item.label} details`}
            >
              <div className="flex-1 min-w-0 z-10">
                <span className="text-[11px] text-slate-700 block uppercase tracking-wider font-semibold">{item.label}</span>
                <span className="text-lg font-bold text-slate-900 block mt-0.5 font-mono">{item.val}</span>
                <span className={`text-[12px] font-bold block mt-0.5 ${marketStateClass(item.state)}`}>
                  {isPositive ? '↑' : '↓'} {item.delta}
                </span>
              </div>
              <div className="w-16 h-14 flex-shrink-0 relative">
                {item.sparkline && item.sparkline.length >= 2 ? (
                  <SparklineSVG positive={isPositive} data={item.sparkline} />
                ) : (
                  <div className="absolute top-0 right-0 w-full h-full opacity-70">
                    <MiniSparkline positive={isPositive} />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function getCommodityGradient(label: string): { background: string; border: string } {
  const upper = label.toUpperCase();
  if (upper.includes('GOLD')) {
    return { background: 'linear-gradient(135deg, #FEF3C7 0%, #FCD34D 100%)', border: '1px solid #FCD34D' };
  }
  if (upper.includes('SILVER')) {
    return { background: 'linear-gradient(135deg, #E0F2FE 0%, #BAE6FD 100%)', border: '1px solid #BAE6FD' };
  }
  if (upper.includes('BRENT')) {
    return { background: 'linear-gradient(135deg, #FEE2E2 0%, #FECACA 100%)', border: '1px solid #FECACA' };
  }
  if (upper.includes('WTI')) {
    return { background: 'linear-gradient(135deg, #FEE2E2 0%, #FECACA 100%)', border: '1px solid #FECACA' };
  }
  if (upper.includes('NATURAL') || upper.includes('GAS')) {
    return { background: 'linear-gradient(135deg, #D1FAE5 0%, #A7F3D0 100%)', border: '1px solid #A7F3D0' };
  }
  if (upper.includes('ALUMINUM')) {
    return { background: 'linear-gradient(135deg, #F3E8FF 0%, #E9D5FF 100%)', border: '1px solid #DDD6FE' };
  }
  if (upper.includes('ZINC')) {
    return { background: 'linear-gradient(135deg, #F3E8FF 0%, #E9D5FF 100%)', border: '1px solid #DDD6FE' };
  }
  if (upper.includes('NICKEL')) {
    return { background: 'linear-gradient(135deg, #F3E8FF 0%, #E9D5FF 100%)', border: '1px solid #DDD6FE' };
  }
  if (upper.includes('BITCOIN')) {
    return { background: 'linear-gradient(135deg, #FEF08A 0%, #FDE047 100%)', border: '1px solid #FDE047' };
  }
  if (upper.includes('COPPER')) {
    return { background: 'linear-gradient(135deg, #FBDDD8 0%, #F7C2B5 100%)', border: '1px solid #F5A896' };
  }
  if (upper.includes('PLATINUM')) {
    return { background: 'linear-gradient(135deg, #E0E7FF 0%, #C7D2FE 100%)', border: '1px solid #C7D2FE' };
  }
  if (upper.includes('PALLADIUM')) {
    return { background: 'linear-gradient(135deg, #F1F5F9 0%, #E2E8F0 100%)', border: '1px solid #E2E8F0' };
  }
  if (upper.includes('WHEAT')) {
    return { background: 'linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%)', border: '1px solid #FDE68A' };
  }
  return { background: 'linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%)', border: '1px solid #E2E8F0' };
}

function getIndiaMarketGradient(label: string): { background: string; border: string } {
  const upper = label.toUpperCase();
  if (upper.includes('NIFTY 50') || upper.includes('NIFTY BANK') || upper.includes('NIFTY IT') || upper.includes('NIFTY PHARMA')) {
    return { background: 'linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%)', border: '1px solid #A7F3D0' };
  }
  if (upper.includes('SENSEX')) {
    return { background: 'linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%)', border: '1px solid #BFDBFE' };
  }
  if (upper.includes('MIDCAP')) {
    return { background: 'linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%)', border: '1px solid #FDE68A' };
  }
  if (upper.includes('SMALLCAP')) {
    return { background: 'linear-gradient(135deg, #FCE7F3 0%, #FBCFE8 100%)', border: '1px solid #F9A8D4' };
  }
  if (upper.includes('USD') || upper.includes('VIX') || upper.includes('GIFT')) {
    return { background: 'linear-gradient(135deg, #F3E8FF 0%, #E9D5FF 100%)', border: '1px solid #DDD6FE' };
  }
  return { background: 'linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%)', border: '1px solid #E2E8F0' };
}

function getIndexClickUrl(label: string): string {
  const upper = label.toUpperCase();
  // Indian indices → Moneycontrol (most reliable for Indian markets)
  if (upper.includes('NIFTY 50') || upper === 'NIFTY' || upper === 'NIFTY50') return 'https://www.moneycontrol.com/indian-indices/nifty-50-9.html';
  if (upper.includes('SENSEX')) return 'https://www.moneycontrol.com/indian-indices/sensex-1.html';
  if (upper.includes('NIFTY BANK')) return 'https://www.moneycontrol.com/indian-indices/nifty-bank-11.html';
  if (upper.includes('NIFTY IT')) return 'https://www.moneycontrol.com/indian-indices/nifty-it-16.html';
  if (upper.includes('NIFTY PHARMA')) return 'https://www.moneycontrol.com/indian-indices/nifty-pharma-22.html';
  if (upper.includes('NIFTY MIDCAP')) return 'https://www.moneycontrol.com/indian-indices/nifty-midcap-100-36.html';
  if (upper.includes('NIFTY SMALLCAP')) return 'https://www.moneycontrol.com/indian-indices/nifty-smallcap-100-41.html';
  if (upper.includes('GIFT NIFTY') || upper.includes('GIFT')) return 'https://www.moneycontrol.com/live-index/gift-nifty?symbol=in;gsx';
  if (upper.includes('VIX') || upper.includes('INDIA VIX')) return 'https://www.moneycontrol.com/indian-indices/india-vix-48.html';
  if (upper.includes('NIFTY 100')) return 'https://www.moneycontrol.com/indian-indices/nifty-100-34.html';
  if (upper.includes('USD') && upper.includes('INR')) return 'https://www.moneycontrol.com/currency/usd-inr';
  if (upper.includes('NIFTY')) return 'https://www.moneycontrol.com/indian-indices/nifty-50-9.html';
  // Global indices → Google Finance (reliable)
  if (upper.includes('DOW') || upper.includes('DJI')) return 'https://www.google.com/finance/quote/.DJI:INDEXDJX';
  if (upper.includes('S&P 500') || upper.includes('SPX')) return 'https://www.google.com/finance/quote/.INX:INDEXSP';
  if (upper.includes('NASDAQ')) return 'https://www.google.com/finance/quote/.IXIC:INDEXNASDAQ';
  if (upper.includes('NIKKEI')) return 'https://www.google.com/finance/quote/NI225:INDEXNIKKEI';
  if (upper.includes('HANG SENG')) return 'https://www.google.com/finance/quote/HSI:INDEXHANGSENG';
  if (upper.includes('SHANGHAI')) return 'https://www.google.com/finance/quote/000001:SHA';
  if (upper.includes('DAX')) return 'https://www.google.com/finance/quote/DAX:INDEXDB';
  if (upper.includes('FTSE')) return 'https://www.google.com/finance/quote/UKX:INDEXFTSE';
  if (upper.includes('CAC')) return 'https://www.google.com/finance/quote/PX1:INDEXEUROPA';
  if (upper.includes('EURO')) return 'https://www.google.com/finance/quote/SX5E:INDEXSTOXX';
  if (upper.includes('ASX')) return 'https://www.google.com/finance/quote/AS51:INDEXASX';
  if (upper.includes('BOVESPA')) return 'https://www.google.com/finance/quote/IBOV:INDEXBVMF';
  if (upper.includes('KOSPI')) return 'https://www.google.com/finance/quote/KS11:KRX';
  if (upper.includes('TSX')) return 'https://www.google.com/finance/quote/OSPTX:INDEXTSI';
  // Commodities → Google Finance
  if (upper.includes('GOLD')) return 'https://www.google.com/finance/quote/GC=F:CME';
  if (upper.includes('SILVER')) return 'https://www.google.com/finance/quote/SI=F:CME';
  if (upper.includes('BRENT') || upper.includes('CRUDE') || upper.includes('WTI')) return 'https://www.google.com/finance/quote/CL=F:NYMEX';
  if (upper.includes('BITCOIN') || upper.includes('BTC')) return 'https://www.google.com/finance/quote/BTC-USD';
  if (upper.includes('COPPER')) return 'https://www.google.com/finance/quote/HG=F:CME';
  if (upper.includes('NATURAL') || upper.includes('GAS')) return 'https://www.google.com/finance/quote/NG=F:NYMEX';
  if (upper.includes('ALUMINUM')) return 'https://www.google.com/finance/quote/ALI=F:CME';
  if (upper.includes('PLATINUM')) return 'https://www.google.com/finance/quote/PL=F:NYMEX';
  if (upper.includes('PALLADIUM')) return 'https://www.google.com/finance/quote/PA=F:NYMEX';
  if (upper.includes('WHEAT')) return 'https://www.google.com/finance/quote/ZW=F:CBOT';
  if (upper.includes('ZINC')) return 'https://www.google.com/finance/quote/ZNC=F:CME';
  if (upper.includes('NICKEL')) return 'https://www.google.com/finance/quote/NID=F:CME';
  return `https://www.google.com/finance/quote/${encodeURIComponent(label)}`;
}

/* -------------------------------------------------------------------------- */
/*  Hook: fetch sparkline data from Moneycontrol for indices missing sparklines */
/* -------------------------------------------------------------------------- */
function useIndexSparklines(items: MacroRow[]): Record<string, number[]> {
  const [sparklines, setSparklines] = useState<Record<string, number[]>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const missingLabels = items
      .filter((item) => (!item.sparkline || item.sparkline.length < 2) && !fetchedRef.current.has(item.label))
      .map((item) => item.label);

    if (missingLabels.length === 0) return;

    missingLabels.forEach((label) => fetchedRef.current.add(label));

    const fetchSparklines = async () => {
      const results = await Promise.allSettled(
        missingLabels.map(async (label) => {
          const res = await fetch(`/api/index-sparkline?label=${encodeURIComponent(label)}`, { cache: 'no-store' });
          if (!res.ok) return { label, sparkline: [] as number[] };
          const data = await res.json();
          return { label, sparkline: (data.sparkline as number[]) ?? [] };
        })
      );

      const updates: Record<string, number[]> = {};
      for (const result of results) {
        if (result.status === 'fulfilled' && result.value.sparkline.length >= 2) {
          updates[result.value.label] = result.value.sparkline;
        }
      }

      if (Object.keys(updates).length > 0) {
        setSparklines((prev) => ({ ...prev, ...updates }));
      }
    };

    void fetchSparklines();
  }, [items]);

  return sparklines;
}

function getGlobalIndexGradient(label: string): { background: string; border: string } {
  const upper = label.toUpperCase();
  if (upper.includes('DJI') || upper.includes('S&P 500') || upper.includes('NASDAQ') || upper.includes('DOW')) {
    return { background: 'linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%)', border: '1px solid #BFDBFE' };
  }
  if (upper.includes('NIKKEI')) {
    return { background: 'linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%)', border: '1px solid #FDE68A' };
  }
  if (upper.includes('HANG SENG') || upper.includes('SHANGHAI')) {
    return { background: 'linear-gradient(135deg, #FEE2E2 0%, #FECACA 100%)', border: '1px solid #FECACA' };
  }
  if (upper.includes('DAX') || upper.includes('CAC') || upper.includes('FTSE') || upper.includes('EURO')) {
    return { background: 'linear-gradient(135deg, #F3E8FF 0%, #E9D5FF 100%)', border: '1px solid #DDD6FE' };
  }
  if (upper.includes('ASX') || upper.includes('BOVESPA')) {
    return { background: 'linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%)', border: '1px solid #A7F3D0' };
  }
  return { background: 'linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%)', border: '1px solid #E2E8F0' };
}

/* -------------------------------------------------------------------------- */
/*  CommoditiesFxGrid                                                            */
/* -------------------------------------------------------------------------- */

function CommoditiesFxGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-3 text-slate-400 text-[11px] shadow-sm">
        Waiting for commodities & FX data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
          <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">COMMODITIES & FX</span>
        </div>
        {staleLabel && <span className="text-[10px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-1.5">
        {items.map((item) => {
          let displayLabel = item.label;
          if (displayLabel === 'BRENT CRUDE OIL') displayLabel = 'BRENT CRUDE';
          const gradient = getCommodityGradient(displayLabel);
          const isPositive = item.state === 'POSITIVE';
          return (
            <div
              key={item.label}
              className="relative overflow-hidden rounded-lg p-2.5 transition-all hover:scale-105 flex items-center gap-2 cursor-pointer"
              style={{
                background: gradient.background,
                border: gradient.border,
                minHeight: '80px',
              }}
              onClick={() => window.open(getIndexClickUrl(item.label), '_blank', 'noopener,noreferrer')}
              onKeyDown={(e) => { if (e.key === 'Enter') window.open(getIndexClickUrl(item.label), '_blank', 'noopener,noreferrer'); }}
              tabIndex={0}
              role="link"
              aria-label={`View ${displayLabel} details`}
            >
              <div className="flex-1 min-w-0 z-10">
                <span className="text-[11px] text-slate-700 block uppercase tracking-wider font-semibold">{displayLabel}</span>
                <span className="text-lg font-bold text-slate-900 block mt-0.5 font-mono">{item.val}</span>
                <span className={`text-[12px] font-bold block mt-0.5 ${marketStateClass(item.state)}`}>
                  {isPositive ? '↑' : '↓'} {item.delta}
                </span>
              </div>
              <div className="w-16 h-14 flex-shrink-0 relative">
                {item.sparkline && item.sparkline.length >= 2 ? (
                  <SparklineSVG positive={isPositive} data={item.sparkline} />
                ) : (
                  <div className="absolute top-0 right-0 w-full h-full opacity-70">
                    <MiniSparkline positive={isPositive} />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  IndiaMarketsGrid                                                             */
/* -------------------------------------------------------------------------- */

function IndiaMarketsGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-3 text-slate-400 text-[11px] shadow-sm">
        Waiting for Indian market data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">INDIA MARKETS — TOP MOVERS</span>
        {staleLabel && <span className="text-[10px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-1.5">
        {items.map((item) => {
          let displayLabel = item.label;
          if (displayLabel === 'USD / INR Spot') displayLabel = 'USD / INR';
          const isPositive = item.state === 'POSITIVE';
          const gradient = getIndiaMarketGradient(displayLabel);
          return (
            <div
              key={item.label}
              className="relative overflow-hidden rounded-lg p-2.5 transition-all hover:scale-105 flex items-center gap-2 cursor-pointer"
              style={{
                background: gradient.background,
                border: gradient.border,
                minHeight: '80px',
              }}
              onClick={() => window.open(getIndexClickUrl(item.label), '_blank', 'noopener,noreferrer')}
              onKeyDown={(e) => { if (e.key === 'Enter') window.open(getIndexClickUrl(item.label), '_blank', 'noopener,noreferrer'); }}
              tabIndex={0}
              role="link"
              aria-label={`View ${displayLabel} details`}
            >
              <div className="flex-1 min-w-0 z-10">
                <span className="text-[11px] text-slate-700 block uppercase tracking-wider font-semibold">{displayLabel}</span>
                <span className="text-lg font-bold text-slate-900 block mt-0.5 font-mono">{item.val}</span>
                <span className={`text-[12px] font-bold block mt-0.5 ${marketStateClass(item.state)}`}>
                  {isPositive ? '↑' : '↓'} {item.delta}
                </span>
              </div>
              <div className="w-16 h-14 flex-shrink-0 relative">
                {item.sparkline && item.sparkline.length >= 2 ? (
                  <SparklineSVG positive={isPositive} data={item.sparkline} />
                ) : (
                  <div className="absolute top-0 right-0 w-full h-full opacity-70">
                    <MiniSparkline positive={isPositive} />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  StockDetailPanel                                                             */
/* -------------------------------------------------------------------------- */

function StockDetailPanel({ stock }: { stock?: LiveStock | LedgerStock | null }) {
  if (!stock) {
    return (
      <div className="bg-white border border-emerald-300 border-[0.5px] rounded-lg p-3 text-slate-500 min-h-[90px] flex items-center justify-center text-[9px] shadow-sm">
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
    <div className="bg-white border border-emerald-300 border-[0.5px] rounded-lg p-3 shadow-sm">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-slate-500 text-[9px] uppercase tracking-wider">{name}</div>
          <div className="flex items-baseline gap-3 mt-1">
              <span className="text-2xl font-black text-slate-900">{normalizedPrice}</span>
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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5 mt-2 text-[9px]">
        <div className="bg-slate-50 border border-slate-100 p-1.5 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[8px]">Open</div>
          <div className="font-bold text-slate-900 mt-0.5">{open ?? 'N/A'}</div>
        </div>
        <div className="bg-slate-50 border border-slate-100 p-1.5 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[8px]">High</div>
          <div className="font-bold text-slate-900 mt-0.5">{high ?? 'N/A'}</div>
        </div>
        <div className="bg-slate-50 border border-slate-100 p-1.5 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[8px]">Low</div>
          <div className="font-bold text-slate-900 mt-0.5">{low ?? 'N/A'}</div>
        </div>
        <div className="bg-slate-50 border border-slate-100 p-1.5 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[8px]">Volume</div>
          <div className="font-bold text-slate-900 mt-0.5">{volume != null ? new Intl.NumberFormat().format(volume) : 'N/A'}</div>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  NewsFeedPanel                                                                */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/*  NewsFeedPanel — modern, non-scrolling grid of source cards                 */
/* -------------------------------------------------------------------------- */

type NewsItem = {
  source: string;
  title: string;
  link: string;
  summary: string;
  publishedAt: string;
  sentiment?: "Bullish" | "Bearish" | "Neutral";
  category?: string;
};

const SOURCE_BRAND: Record<string, string> = {
  moneycontrol: "#ff6f00",
  livemint: "#1a7a5a",
  news18: "#d6336c",
  "indian express": "#c0392b",
  inc42: "#0a66c2",
  yourstory: "#e8490b",
  google: "#1a73e8",
  "business standard": "#1565c0",
  "economic times": "#e0a800",
  "financial express": "#c62828",
  "business line": "#00897b",
  "business today": "#1976d2",
  forbes: "#111111",
  zee: "#6a1b9a",
  cnbc: "#0b6e4f",
  mint: "#1a7a5a",
};

const FALLBACK_PALETTE = ["#6366f1", "#0ea5e9", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#22c55e"];

function sourceColor(name: string): string {
  const lower = name.toLowerCase();
  for (const key of Object.keys(SOURCE_BRAND)) {
    if (lower.includes(key)) return SOURCE_BRAND[key];
  }
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return FALLBACK_PALETTE[hash % FALLBACK_PALETTE.length];
}

const SENTIMENT_STYLE: Record<string, { bg: string; txt: string; dot: string; label: string }> = {
  Bullish: { bg: "bg-emerald-50", txt: "text-emerald-700", dot: "bg-emerald-500", label: "Bullish" },
  Bearish: { bg: "bg-red-50", txt: "text-red-700", dot: "bg-red-500", label: "Bearish" },
  Neutral: { bg: "bg-slate-100", txt: "text-slate-600", dot: "bg-slate-400", label: "Neutral" },
};

const CATEGORY_STYLE: Record<string, { bg: string; txt: string }> = {
  Market: { bg: "bg-sky-50", txt: "text-sky-700" },
  Earnings: { bg: "bg-violet-50", txt: "text-violet-700" },
  Regulatory: { bg: "bg-amber-50", txt: "text-amber-700" },
  Corporate: { bg: "bg-indigo-50", txt: "text-indigo-700" },
  Economy: { bg: "bg-teal-50", txt: "text-teal-700" },
  Commodity: { bg: "bg-orange-50", txt: "text-orange-700" },
  Global: { bg: "bg-cyan-50", txt: "text-cyan-700" },
};

function categoryStyle(category?: string): { bg: string; txt: string } {
  if (category && CATEGORY_STYLE[category]) return CATEGORY_STYLE[category];
  return { bg: "bg-slate-100", txt: "text-slate-600" };
}

function NewsFeedPanel({ items, now, sidebar }: { items?: NewsItem[]; now: number; sidebar?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [sentimentFilter, setSentimentFilter] = useState<string | null>(null);
  const railRef = useRef<HTMLDivElement | null>(null);
  const [infiniteItems, setInfiniteItems] = useState<NewsItem[]>([]);
  const [infiniteOffset, setInfiniteOffset] = useState(0);
  const [infiniteHasMore, setInfiniteHasMore] = useState(true);
  const [infiniteLoading, setInfiniteLoading] = useState(false);
  const pageSize = 50;


  const timeAgo = (dateStr: string) => {
    const diff = now - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  };

  const baseItems = sidebar ? infiniteItems : (items ?? []);

  const sources = useMemo(() => {
    const set = new Set<string>();
    baseItems.forEach((it) => it.source && set.add(it.source));
    return Array.from(set).sort();
  }, [baseItems]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    baseItems.forEach((it) => it.category && set.add(it.category));
    return Array.from(set).sort();
  }, [baseItems]);

  const filtered = useMemo(() => {
    return baseItems.filter((it) => {
      if (sourceFilter && it.source !== sourceFilter) return false;
      if (categoryFilter && (it.category ?? "Market") !== categoryFilter) return false;
      if (sentimentFilter && (it.sentiment ?? "Neutral") !== sentimentFilter) return false;
      return true;
    });
  }, [baseItems, sourceFilter, categoryFilter, sentimentFilter]);

  const hasFilters = sourceFilter || categoryFilter || sentimentFilter;
  const displayed = sidebar ? filtered : (expanded ? filtered : filtered.slice(0, 12));

  const loadMoreSidebarNews = useCallback(async () => {
    if (!sidebar || infiniteLoading || !infiniteHasMore) return;
    setInfiniteLoading(true);
    try {
      const res = await fetch(`/api/live-news?offset=${infiniteOffset}&limit=${pageSize}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      const next: NewsItem[] = Array.isArray(body?.payload) ? body.payload : [];
      setInfiniteItems((prev) => {
        const seen = new Set(prev.map((p) => `${p.title}::${p.link}`));
        const merged = [...prev];
        for (const n of next) {
          const key = `${n.title}::${n.link}`;
          if (!seen.has(key)) {
            seen.add(key);
            merged.push(n);
          }
        }
        return merged;
      });
      setInfiniteOffset((prev) => prev + next.length);
      setInfiniteHasMore(Boolean(body?.hasMore) && next.length > 0);
    } catch {
      setInfiniteHasMore(false);
    } finally {
      setInfiniteLoading(false);
    }
  }, [sidebar, infiniteLoading, infiniteHasMore, infiniteOffset]);

  useEffect(() => {
    if (!sidebar) return;
    setInfiniteItems([]);
    setInfiniteOffset(0);
    setInfiniteHasMore(true);
  }, [sidebar]);

  useEffect(() => {
    if (!sidebar) return;
    if (infiniteItems.length === 0 && !infiniteLoading && infiniteHasMore) {
      void loadMoreSidebarNews();
    }
  }, [sidebar, infiniteItems.length, infiniteLoading, infiniteHasMore, loadMoreSidebarNews]);

  const handleSidebarScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    if (!sidebar || infiniteLoading || !infiniteHasMore) return;
    const el = e.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 48;
    if (nearBottom) {
      void loadMoreSidebarNews();
    }
  }, [sidebar, infiniteLoading, infiniteHasMore, loadMoreSidebarNews]);

  const hasAnyItems = sidebar ? baseItems.length > 0 : Boolean(items?.length);

  if (!hasAnyItems) {
    const containerCls = sidebar
      ? "bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden"
      : "bg-white border border-slate-300 border-[0.5px] rounded-2xl shadow-sm overflow-hidden";
    return (
      <div className={containerCls}>
        <div className="flex items-center gap-2 p-3 border-b border-slate-100 bg-gradient-to-r from-slate-50/80 to-white">
          <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
          <span className="text-[10px] uppercase tracking-widest text-slate-700 font-black">Live News Feed</span>
          <span className="ml-auto text-[9px] text-slate-400 uppercase tracking-wider">Waiting for data</span>
        </div>
        <div className="p-6 text-center text-slate-400 text-[11px]">No news stories available.</div>
      </div>
    );
  }

  const resetFilters = () => {
    setSourceFilter(null);
    setCategoryFilter(null);
    setSentimentFilter(null);
  };

  // Sidebar mode: compact, vertically scrollable news list
  if (sidebar) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-2.5 shadow-sm h-[1270px] overflow-hidden news-sidebar flex flex-col">
        {/* Compact Header */}
        <div className="flex items-center justify-between px-1 py-1.5 border-b border-slate-100 bg-gradient-to-r from-slate-50/80 to-white">
          <div className="flex items-center gap-2">
            <div className="relative flex items-center justify-center w-5 h-5 rounded-md bg-gradient-to-br from-teal-500 to-blue-600 shadow-sm">
              <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
              </svg>
            </div>
            <div>
              <h3 className="text-[10px] font-black text-slate-800 uppercase tracking-wider">Live News Feed</h3>
              <p className="text-[7px] text-slate-500">{filtered.length} stories · {sources.length} sources</p>
            </div>
          </div>
          <span className="text-[8px] font-semibold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded-full border border-emerald-100">
            RSS
          </span>
        </div>

        {/* Vertically scrollable news list */}
        <div
          className="news-sidebar-rail pt-2 space-y-1.5 flex-1 min-h-0 overflow-y-auto overflow-x-hidden pr-1"
          tabIndex={0}
          ref={railRef}
          onScroll={handleSidebarScroll}
        >
          {displayed.map((item, i) => {
            const color = sourceColor(item.source);
            const sentiment = item.sentiment ?? "Neutral";
            const st = SENTIMENT_STYLE[sentiment];
            const cat = categoryStyle(item.category);
            return (
              <a
                key={`${item.title}-${i}`}
                href={item.link}
                target="_blank"
                rel="noopener noreferrer"
                className="news-sidebar-card group block rounded-lg border border-slate-200 hover:border-slate-300 bg-white hover:shadow-sm transition-all duration-200 overflow-hidden"
              >
                <div className="flex items-start gap-2 p-2.5">
                  {/* Left accent bar */}
                  <div className="w-0.5 h-full min-h-[3rem] rounded-full flex-shrink-0" style={{ background: color }} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1 mb-0.5">
                      <span
                        className="text-[7px] font-black uppercase tracking-wider px-1 py-0.5 rounded text-white truncate max-w-[80px]"
                        style={{ background: color }}
                      >
                        {item.source}
                      </span>
                      <span className="text-[7px] font-mono text-slate-400 ml-auto whitespace-nowrap">{timeAgo(item.publishedAt)}</span>
                    </div>
                    <h4 className="text-[10px] font-bold text-slate-800 leading-snug group-hover:text-teal-700 transition-colors line-clamp-2">
                      {item.title}
                    </h4>
                    <div className="flex items-center gap-1 mt-0.5">
                      <span className={`text-[7px] font-bold px-1 py-0.5 rounded ${cat.bg} ${cat.txt}`}>{item.category ?? "Market"}</span>
                      <span className={`flex items-center gap-0.5 text-[7px] font-bold px-1 py-0.5 rounded ${st.bg} ${st.txt}`}>
                        <span className={`w-1 h-1 rounded-full ${st.dot}`} />
                        {st.label}
                      </span>
                    </div>
                  </div>
                </div>
              </a>
            );
          })}
          {infiniteLoading && (
            <div className="text-[8px] text-slate-400 px-2 py-1 text-center">Loading more stories...</div>
          )}
        </div>

        {filtered.length > 20 && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            className="w-full py-1.5 text-[9px] font-bold uppercase tracking-wider text-slate-500 hover:text-teal-700 hover:bg-slate-50 border-t border-slate-100 transition-colors"
          >
            Show {filtered.length} stories
          </button>
        )}
      </div>
    );
  }

  // Non-sidebar (full-width horizontal) mode - unchanged
  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-gradient-to-r from-slate-50/80 to-white">
        <div className="flex items-center gap-2.5">
          <div className="relative flex items-center justify-center w-7 h-7 rounded-lg bg-gradient-to-br from-teal-500 to-blue-600 shadow-md">
            <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
            </svg>
          </div>
          <div>
            <h3 className="text-[11px] font-black text-slate-800 uppercase tracking-wider">Live News Feed</h3>
            <p className="text-[8px] text-slate-500">{filtered.length} of {(items ?? []).length} stories · {sources.length} sources</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden sm:inline-flex text-[9px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-1 rounded-full border border-emerald-100">
            RSS · live
          </span>
          {hasFilters && (
            <button
              onClick={resetFilters}
              className="text-[9px] font-bold text-slate-500 hover:text-red-600 bg-slate-100 hover:bg-slate-200 px-2 py-1 rounded-full transition-colors"
            >
              Clear
            </button>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[9px] font-bold text-slate-500 hover:text-teal-700 bg-slate-100 hover:bg-slate-200 px-2 py-1 rounded-full transition-colors"
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
        </div>
      </div>

      {/* Sticky filter bar */}
      <div className="sticky top-2 z-20 flex flex-wrap items-center gap-1.5 px-4 py-2 bg-white/95 backdrop-blur border-b border-slate-100">
        <span className="text-[8px] uppercase tracking-widest text-slate-400 font-bold mr-0.5">Filter:</span>
        <select
          value={categoryFilter ?? ""}
          onChange={(e) => setCategoryFilter(e.target.value || null)}
          className="text-[9px] font-semibold text-slate-600 bg-slate-50 border border-slate-200 rounded-full px-2 py-1 outline-none focus:ring-1 focus:ring-teal-300 cursor-pointer"
        >
          <option value="">All Categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        {(["Bullish", "Bearish", "Neutral"] as const).map((s) => {
          const st = SENTIMENT_STYLE[s];
          const active = sentimentFilter === s;
          return (
            <button
              key={s}
              onClick={() => setSentimentFilter(active ? null : s)}
              className={`flex items-center gap-1 text-[9px] font-bold px-2 py-1 rounded-full border transition-colors ${
                active ? `${st.bg} ${st.txt} border-current` : "bg-slate-50 text-slate-500 border-slate-200 hover:bg-slate-100"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
              {st.label}
            </button>
          );
        })}
        <select
          value={sourceFilter ?? ""}
          onChange={(e) => setSourceFilter(e.target.value || null)}
          className="ml-auto text-[9px] font-semibold text-slate-600 bg-slate-50 border border-slate-200 rounded-full px-2 py-1 outline-none focus:ring-1 focus:ring-teal-300 cursor-pointer max-w-[140px]"
        >
          <option value="">All Sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* News rail (horizontal scroll) */}
      {displayed.length === 0 ? (
        <div className="p-6 text-center text-slate-400 text-[11px]">No stories match the current filters.</div>
      ) : (
        <div className="news-rail gap-3 p-3" tabIndex={0} aria-label="Scrollable live news stories" ref={railRef}>
          {displayed.map((item, i) => {
            const color = sourceColor(item.source);
            const sentiment = item.sentiment ?? "Neutral";
            const st = SENTIMENT_STYLE[sentiment];
            const cat = categoryStyle(item.category);
            return (
              <a
                key={`${item.title}-${i}`}
                href={item.link}
                target="_blank"
                rel="noopener noreferrer"
                className="news-card group block break-inside-avoid mb-3 rounded-xl border border-slate-200 hover:border-slate-300 bg-white hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 overflow-hidden"
              >
                {/* Top accent bar in source brand color */}
                <div className="h-1 w-full" style={{ background: color }} />
                <div className="p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className="text-[8px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded text-white truncate max-w-[120px]"
                      style={{ background: color }}
                      title={item.source}
                    >
                      {item.source}
                    </span>
                    <span className="ml-auto text-[8px] font-mono text-slate-400 whitespace-nowrap">{timeAgo(item.publishedAt)}</span>
                  </div>

                  <div className="flex items-center gap-1 mb-1.5">
                    <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${cat.bg} ${cat.txt}`}>{item.category ?? "Market"}</span>
                    <span className={`flex items-center gap-1 text-[8px] font-bold px-1.5 py-0.5 rounded ${st.bg} ${st.txt}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                      {st.label}
                    </span>
                  </div>

                  <h4 className="text-[11px] font-bold text-slate-800 leading-snug group-hover:text-teal-700 transition-colors line-clamp-3">
                    {item.title}
                  </h4>

                  {/* Summary preview — revealed on hover */}
                  <div className="grid grid-rows-[0fr] group-hover:grid-rows-[1fr] transition-all duration-200">
                    <p className="overflow-hidden text-[9px] text-slate-500 leading-relaxed mt-0 group-hover:mt-1.5 line-clamp-4">
                      {item.summary}
                    </p>
                  </div>
                </div>
              </a>
            );
          })}
        </div>
      )}

      {!expanded && filtered.length > 12 && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500 hover:text-teal-700 hover:bg-slate-50 border-t border-slate-100 transition-colors"
        >
          Show {filtered.length - 12} more stories
        </button>
      )}
    </div>
  );
}

function LiveIntelligencePanel() {
  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-2.5 shadow-sm" />
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
      <div className="bg-white border border-slate-300 border-[0.5px] p-3 rounded-lg shadow-sm">
        <p className="text-[9px] text-slate-500">Risk calc / factor data not available.</p>
      </div>
    );
  }

  const riskFlagEntry = riskCalc ? Object.entries(riskCalc).find(([k]) => k.toLowerCase() === 'risk_flag' || k.toLowerCase() === 'risk_flag_value') : undefined;
  const regularRiskEntries = riskCalc ? Object.entries(riskCalc).filter(([k]) => k.toLowerCase() !== 'risk_flag' && k.toLowerCase() !== 'risk_flag_value') : [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
      {hasRisk && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
          <div className="bg-slate-100 px-3 py-2 border-b border-slate-200">
            <h4 className="text-[10px] font-bold text-slate-700 uppercase tracking-wider">Risk Calc</h4>
            <p className="text-[8px] text-slate-500 mt-0.5">Quantified risk metrics from live analysis.</p>
          </div>
          <div className="p-2.5 space-y-0">
            {riskFlagEntry && (
              <div className="flex items-center justify-between gap-3 py-1.5 border-b border-red-100 bg-red-50/40 -mx-2.5 px-2.5 mb-0">
                <span className="text-[9px] text-red-700 uppercase tracking-wider font-bold leading-tight">Risk Flag</span>
                <span className="text-[11px] text-red-700 font-black uppercase tracking-wider animate-pulse">{String(riskFlagEntry[1])}</span>
              </div>
            )}
            {regularRiskEntries.map(([label, value], idx, arr) => (
              <div key={label} className={`flex items-center justify-between gap-3 py-1.5 ${idx < arr.length - 1 ? 'border-b border-slate-100' : ''}`}>
                <span className="text-[9px] text-slate-500 uppercase tracking-wider leading-tight">{formatSnakeKey(label)}</span>
                <span className="text-[10px] text-slate-900 font-bold text-right leading-tight">{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasFactor && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
          <div className="bg-emerald-50 px-3 py-2 border-b border-emerald-100">
            <h4 className="text-[10px] font-bold text-emerald-700 uppercase tracking-wider">Factor Hub</h4>
            <p className="text-[8px] text-slate-500 mt-0.5">Active factor exposures and signals.</p>
          </div>
          <div className="p-2.5 space-y-0">
            {Object.entries(factorHub).map(([label, value], idx, arr) => (
              <div key={label} className={`py-1.5 ${idx < arr.length - 1 ? 'border-b border-emerald-50' : ''}`}>
                <div className="text-[8px] text-emerald-700 uppercase tracking-wider mb-0.5">{formatSnakeKey(label)}</div>
                <div className="text-[10px] text-slate-700 leading-relaxed">{value}</div>
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
    <div className="bg-slate-50 border border-slate-300 border-[0.5px] rounded-xl p-3">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h3 className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">Structured Reasoning Output</h3>
          <p className="text-[9px] text-slate-500 mt-0.5">Gemini / Pydantic mapped payload from the live ingestion stream.</p>
        </div>
        <div className="text-[9px] text-slate-500">{hasData ? 'Available' : 'Unavailable'}</div>
      </div>

      {hasData ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[9px] text-slate-700">
            <div className="bg-white border border-emerald-200 border-[0.5px] p-2.5 rounded-lg">
              <div className="text-[8px] uppercase tracking-wider text-emerald-700 mb-1">News Catalysts</div>
              <p className="text-[10px] text-slate-700 leading-relaxed">{intelligence.news_catalysts_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-white border border-emerald-200 border-[0.5px] p-2.5 rounded-lg">
              <div className="text-[8px] uppercase tracking-wider text-emerald-700 mb-1">Macro Anchors</div>
              <p className="text-[10px] text-slate-700 leading-relaxed">{intelligence.macro_anchors_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-white border border-emerald-200 border-[0.5px] p-2.5 rounded-lg">
              <div className="text-[8px] uppercase tracking-wider text-emerald-700 mb-1">Insider / Insti Activity</div>
              <p className="text-[10px] text-slate-700 leading-relaxed">{intelligence.insider_insti_activity_card ?? 'Not produced.'}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2 text-[9px] text-slate-700 mt-2">
            <div className="bg-white border border-emerald-200 border-[0.5px] p-2.5 rounded-lg">
              <div className="text-[8px] uppercase tracking-wider text-emerald-700 mb-1">Structural Thesis</div>
              <p className="text-[9px] text-slate-600 leading-relaxed">
                <span className="text-slate-700">Why Interested: </span>
                {intelligence.why_interested ?? 'Not produced.'}
              </p>
              <p className="text-[9px] text-slate-600 mt-1 leading-relaxed">
                <span className="text-slate-700">Forward Revenue: </span>
                {intelligence.future_revenue_model ?? 'Not produced.'}
              </p>
            </div>
            <div className="bg-white border border-emerald-200 border-[0.5px] rounded-xl overflow-hidden">
              <div className="text-[8px] uppercase tracking-wider text-emerald-700 mb-1">Risk Calc / Factor Hub</div>
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
        <div className="text-slate-500 text-[9px]">
          Terminal intelligence is not currently generated. Start the backend with Gemini/OpenAI keys for structured JSON mapping.
        </div>
      )}
    </div>
  );
}

let sparkIdCounter = 0;

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

/* Real data-driven sparkline rendered from an array of close prices.
 * Uses Catmull-Rom spline for smooth, organic curves. */
function SparklineSVG({ positive, data }: { positive: boolean; data?: number[] }) {
  const [id] = useState(() => `spk-${positive ? 'g' : 'r'}-${++sparkIdCounter}`);
  const color = positive ? '#10b981' : '#ef4444';
  const fillUrl = 'url(#' + id + ')';

  // Need at least 2 points to draw a meaningful line
  if (!data || data.length < 2) return null;

  const W = 100;
  const H = 60;
  const pad = 4;

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
  const lastPoint = points[points.length - 1];

  return (
    <svg className="absolute top-0 right-0 w-full h-full opacity-70" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.5" />
          <stop offset="100%" stopColor={color} stopOpacity="0.05" />
        </linearGradient>
      </defs>
      {/* Area fill */}
      <path d={areaD} fill={fillUrl} />
      {/* Smooth line with Catmull-Rom spline */}
      <path d={pathD} stroke={color} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* End dot */}
      <circle cx={lastPoint[0]} cy={lastPoint[1]} r="2" fill={color} stroke="white" strokeWidth="1" />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/*  MAIN COMPONENT                                                              */
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
    const normalize = (label: string) => normalizeMarketLabel(label);
    const dedup = (arr: MacroRow[]) => {
      const seen = new Set<string>();
      return arr.filter((item) => {
        const n = normalize(item.label);
        if (seen.has(n)) return false;
        seen.add(n);
        return true;
      });
    };
    const macrosDeduped = dedup(macros.filter((item) => !GLOBAL_ONLY_LABELS.has(normalize(item.label))));
    const seenMacros = new Set(macrosDeduped.map((item) => normalize(item.label)));
    const indiaFromGlobal = dedup(globalIndices.filter((item) => INDIA_MARKET_LABELS.has(normalize(item.label))));
    const merged = [
      ...macrosDeduped,
      ...indiaFromGlobal.filter((item) => !seenMacros.has(normalize(item.label))),
    ];
    return merged;
  }, [terminalMode, liveMarket]);

  const globalIndices = useMemo(() => {
    const g = liveMarket?.globalMacro;
    if (!g) return [];
    const seen = new Set<string>();
    return (g.indices ?? []).filter((item) => {
      if (INDIA_MARKET_LABELS.has(normalizeMarketLabel(item.label))) return false;
      const n = normalizeMarketLabel(item.label);
      if (seen.has(n)) return false;
      seen.add(n);
      return true;
    });
  }, [liveMarket]);

  const commodities = useMemo(() => {
    const g = liveMarket?.globalMacro;
    if (!g) return [];
    const seen = new Set<string>();
    return (g.commodities ?? []).filter((item) => {
      const n = normalizeMarketLabel(item.label);
      if (seen.has(n)) return false;
      seen.add(n);
      return true;
    });
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
    const tickerNewsFromSnapshot = liveMarket?.tickerNewsByTicker?.[t] as AITickerNewsReport | undefined;
    if (tickerIntelligence) {
      setTickerIntelligence(tickerIntelligence);
      setDrawerContent({
        stock: stocks.find((s) => s.ticker === t) ?? null,
        analysis: {
          ...tickerIntelligence,
          isSnapshotFallback: liveMarket?.isSnapshotFallback ?? false,
        },
        tickerNews: tickerNewsFromSnapshot ?? null,
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
          tickerNews: tickerNewsFromSnapshot ?? null,
        });
      } else {
        const text = await resp.text();
        setDrawerContent({ stock: stocks.find((s) => s.ticker === t) ?? null, analysis: { error: text } });
      }
    } catch (err) {
      setDrawerContent({ stock: stocks.find((s) => s.ticker === t) ?? null, analysis: { error: String(err) } });
    }

    if (!tickerNewsFromSnapshot) {
      fetch(`/api/ticker-news?ticker=${encodeURIComponent(t)}`, { cache: "no-store" }).catch(() => {});
    }
  };

  const handleRefresh = async () => {
    await refreshOnDemand();
  };

  const snapshotAgeMin = liveMarket?.updatedAt ? Math.round((now - new Date(liveMarket.updatedAt).getTime()) / 60000) : null;
  const staleMacroLabel = snapshotAgeMin == null ? "" : `STALE ${snapshotAgeMin}M`;

  /* Fetch sparkline data from Moneycontrol for indices that are missing sparklines */
  const mcSparklines = useIndexSparklines(currentMacros);
  const mcGlobalSparklines = useIndexSparklines(globalIndices);

  /* Merge sparkline data into macro rows */
  const enrichedMacros = useMemo(
    () => currentMacros.map((item) => ({
      ...item,
      sparkline: (item.sparkline && item.sparkline.length >= 2) ? item.sparkline : (mcSparklines[item.label] ?? item.sparkline),
    })),
    [currentMacros, mcSparklines]
  );

  const enrichedGlobalIndices = useMemo(
    () => globalIndices.map((item) => ({
      ...item,
      sparkline: (item.sparkline && item.sparkline.length >= 2) ? item.sparkline : (mcGlobalSparklines[item.label] ?? item.sparkline),
    })),
    [globalIndices, mcGlobalSparklines]
  );

  return (
    <div className="terminal-shell min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-50 text-slate-900 font-mono text-xs antialiased">
      <div className="max-w-[1600px] mx-auto p-3 space-y-3">
        <header className="terminal-header bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm">
          <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-2 p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${feedStatus === 'live' ? 'bg-emerald-500 animate-pulse' : feedStatus === 'loading' ? 'bg-amber-500' : 'bg-red-500'}`} />
                <h1 className="text-xs font-black tracking-wider text-slate-900">IROS Live Market Intelligence</h1>
              </div>
                  <span className="text-[9px] text-slate-500 uppercase tracking-wider xl:hidden">Nifty 500</span>
            </div>

            <div className="flex items-center justify-between xl:justify-end gap-2">
              <span className="text-[9px] font-bold uppercase text-slate-500 hidden xl:inline tracking-wider">
                {liveMarket?.rawSources?.join(' · ') ?? 'Reuters · TradingView · Moneycontrol'}
              </span>
              <div className="flex items-center gap-1.5 text-[9px] text-slate-500">
                <span className="hidden sm:inline">
                  {liveMarket?.updatedAt ? new Date(liveMarket.updatedAt).toLocaleTimeString() : '--:--'} IST
                </span>
                <button
                  onClick={handleRefresh}
                  disabled={feedStatus === 'loading'}
                  className="px-2.5 py-1 rounded-full bg-teal-600 text-white text-[9px] font-black uppercase tracking-wider hover:bg-teal-500 disabled:opacity-50 transition"
                >
                  Refresh
                </button>
              </div>
            </div>
          </div>

          {isSnapshotFallback && (
            <div className="px-3 pb-2">
              <div className="bg-amber-50 text-amber-800 border border-amber-200 p-1.5 rounded text-[10px]">
                Snapshot fallback active — outside scheduled IST refresh window. Showing latest saved analysis.
              </div>
            </div>
          )}
        </header>

        <nav className="terminal-tabs bg-white border border-slate-300 border-[0.5px] rounded-xl flex gap-1 p-1 shadow-sm">
          {([
            { key: 'marketSnapshot' as TabKey, label: 'MARKET SNAPSHOT' },
            { key: 'stockHeatMap' as TabKey, label: 'STOCK HEAT MAP' },
            { key: 'assetMatrix' as TabKey, label: 'ASSET MATRIX' },
            { key: 'intradayMatrix' as TabKey, label: 'INTRA DAY MATRIX' },
          ]).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-lg transition relative ${
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
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-3 items-stretch">
            {/* Left Column: Core Market Panels */}
            <div className="space-y-3 min-w-0">
              {/* Row 1: India Markets — TOP MOVERS */}
              <div className="grid grid-cols-1 gap-3 items-start">
                <IndiaMarketsGrid items={enrichedMacros} staleLabel={staleMacroLabel} />
              </div>

              {/* Row 2: Global Indices */}
              <div>
                <GlobalIndicesGrid items={enrichedGlobalIndices} staleLabel={staleMacroLabel} />
              </div>

              {/* Row 3: Commodities & FX */}
              <div>
                <CommoditiesFxGrid items={commodities} staleLabel={staleMacroLabel} />
              </div>

              {/* Row 4: Gainers/Losers + Screeners */}
              <div className="flex flex-col gap-4">
                <GainersLosersHeatmap />
              </div>
            </div>

            {/* Right Column: Live News Feed Sidebar */}
            <div className="flex flex-col">
              <NewsFeedPanel items={liveMarket?.news} now={now} sidebar={true} />
            </div>

          </div>
        )}

        {activeTab === 'stockHeatMap' && (
          <div className="space-y-3">
            <Nifty100HeatMap />
          </div>
        )}

        {activeTab === 'assetMatrix' && (
          <div className="space-y-3">
            <ForensicPanel
              onSelect={handleSelect}
              liveMarket={liveMarket}
              refreshOnDemand={refreshOnDemand}
            />
            <StockDetailPanel stock={selectedQuote} />
            <LiveIntelligencePanel />
            <RightDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} content={drawerContent} />
          </div>
        )}

        {activeTab === 'intradayMatrix' && (
          <div className="space-y-3">
            <IntradayMatrixPanel />
          </div>
        )}
      </div>
    </div>
  );
}
