'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

type TrendlyneScreenKey = 'risingDelivery' | 'topLosersVolume' | 'volumeShockers';

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

const TRENDLYNE_SCREENS: { key: TrendlyneScreenKey; label: string; accent: 'emerald' | 'red' | 'amber' }[] = [
  { key: 'risingDelivery', label: 'RISING DELIVERY %', accent: 'emerald' },
  { key: 'topLosersVolume', label: 'TOP LOSERS BY VOLUME', accent: 'red' },
  { key: 'volumeShockers', label: 'VOLUME SHOCKERS', accent: 'amber' },
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
/*  Modern animated tooltip shared components                                  */
/* -------------------------------------------------------------------------- */

function MiniSparkline({ positive }: { positive: boolean }) {
  const color = positive ? '#10b981' : '#ef4444';
  return (
    <svg className="w-full h-10" viewBox="0 0 100 30" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`spark-fill-${positive ? 'g' : 'r'}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {positive ? (
        <>
          <path d="M0,25 L10,22 L20,24 L30,18 L40,16 L50,12 L60,10 L70,8 L80,6 L90,4 L100,2 L100,30 L0,30 Z" fill={`url(#spark-fill-${positive ? 'g' : 'r'})`} />
          <polyline points="0,25 10,22 20,24 30,18 40,16 50,12 60,10 70,8 80,6 90,4 100,2" stroke={color} strokeWidth="1.5" fill="none" className="animate-pulse" />
        </>
      ) : (
        <>
          <path d="M0,5 L10,8 L20,6 L30,12 L40,14 L50,18 L60,20 L70,22 L80,24 L90,26 L100,28 L100,30 L0,30 Z" fill={`url(#spark-fill-${positive ? 'g' : 'r'})`} />
          <polyline points="0,5 10,8 20,6 30,12 40,14 50,18 60,20 70,22 80,24 90,26 100,28" stroke={color} strokeWidth="1.5" fill="none" className="animate-pulse" />
        </>
      )}
    </svg>
  );
}

function NseTooltipContent({ data }: { data: Record<string, unknown> }) {
  const graphSrc = getNseGraphSrc(data);
  const pchange = typeof data.pchange === 'number' ? data.pchange : (typeof data.pChange === 'number' ? data.pChange : null);
  const positive = pchange !== null && pchange >= 0;

  return (
    <div>
      {/* Animated sparkline header */}
      <div className="mb-3 rounded-t-lg" style={{ background: positive ? 'linear-gradient(180deg, rgba(16,185,129,0.08) 0%, transparent 100%)' : 'linear-gradient(180deg, rgba(239,68,68,0.08) 0%, transparent 100%)' }}>
        <MiniSparkline positive={positive} />
      </div>

      {graphSrc && (
        <div className="mb-3 rounded-lg border border-slate-200 bg-white shadow-sm p-2 transition-transform hover:scale-[1.01]">
          <div className="mb-1.5 flex items-center justify-between text-[9px] uppercase tracking-wider text-slate-400 font-bold">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
              Price Chart
            </span>
            <span className="text-teal-600">30D</span>
          </div>
          <img src={graphSrc} alt="NSE chart" className="h-20 w-full rounded object-contain bg-white" />
        </div>
      )}

      <div className="space-y-0.5">
        {Object.entries(data).map(([key, value], idx) => {
          const isPrice = key === 'lastPrice' || key === 'lastCorpAnnouncementPrice';
          const isChange = key === 'pchange' || key === 'pChange';
          const accentClass = isPrice ? 'text-slate-900 font-bold' : isChange ? (positive ? 'text-emerald-600' : 'text-red-500') : 'text-slate-500';
          return (
            <div key={key} className="group flex items-center justify-between gap-3 px-2 py-1.5 rounded-md transition-all hover:bg-slate-50 hover:scale-[1.01]">
              <div className="text-[9px] uppercase tracking-wider text-slate-400 font-semibold truncate">{formatNseKey(key)}</div>
              <div className={`text-[10px] font-mono text-right ${accentClass} transition-colors`}>{formatNseFieldValue(key, value)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function NseTickerTooltip({ stock, ticker }: { stock: NseStock; ticker: string }) {
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [anchor, setAnchor] = useState({ x: 0, y: 0 });
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewportWidth = typeof window === 'undefined' ? 1024 : window.innerWidth;

  const pchange = typeof stock.pchange === 'number' ? stock.pchange : null;
  const positive = pchange !== null && pchange >= 0;

  const cancelClose = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };

  const scheduleClose = () => {
    closeTimer.current = setTimeout(() => setVisible(false), 180);
  };

  const showTooltip = () => {
    cancelClose();
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      setAnchor({ x: rect.right, y: rect.top });
    }
    setVisible(true);
  };

  const tooltipWidth = 352;
  const tooltipLeft = Math.max(8, Math.min(anchor.x + 4, viewportWidth - tooltipWidth - 8));

  return (
    <span
      ref={triggerRef}
      className={`text-[13px] font-bold cursor-default transition-colors ${positive !== null ? (positive ? 'text-emerald-700 hover:text-emerald-500' : 'text-red-700 hover:text-red-500') : 'text-slate-800'}`}
      onMouseEnter={showTooltip}
      onMouseLeave={scheduleClose}
      onFocus={showTooltip}
      onBlur={() => { cancelClose(); setVisible(false); }}
      tabIndex={0}
    >
      {ticker}
      {visible && (
        <>
          <div
            className="fixed inset-0 z-40"
            onMouseEnter={cancelClose}
            onMouseLeave={scheduleClose}
          />
          <div
            className="fixed z-50 w-[22rem] max-h-[20rem] rounded-xl border border-slate-200 bg-white p-3 text-left shadow-2xl overflow-y-auto"
            style={{
              left: `${tooltipLeft}px`,
              top: `${Math.max(8, anchor.y - 4)}px`,
              boxShadow: positive !== null ? (positive ? '0 8px 32px rgba(16,185,129,0.15), 0 2px 8px rgba(0,0,0,0.06)' : '0 8px 32px rgba(239,68,68,0.15), 0 2px 8px rgba(0,0,0,0.06)') : '0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)',
            }}
            onMouseEnter={() => { cancelClose(); setVisible(true); }}
            onMouseLeave={scheduleClose}
          >
            <div className="flex items-center gap-2 mb-2 flex-shrink-0">
              <span className={`w-1.5 h-1.5 rounded-full ${positive !== null ? (positive ? 'bg-emerald-500' : 'bg-red-500') : 'bg-slate-400'} animate-pulse`} />
              <span className={`text-[9px] uppercase tracking-widest font-bold ${positive !== null ? (positive ? 'text-emerald-600' : 'text-red-500') : 'text-slate-500'}`}>
                {ticker} · NSE
              </span>
              {pchange !== null && (
                <span className={`ml-auto text-[10px] font-black tabular-nums ${positive ? 'text-emerald-600' : 'text-red-500'}`}>
                  {positive ? '↑' : '↓'} {pchange > 0 ? '+' : ''}{pchange.toFixed(2)}%
                </span>
              )}
            </div>
            <NseTooltipContent data={stock} />
          </div>
        </>
      )}
    </span>
  );
}

function TrendlynePanel({ screenKey, label, accentClass }: { screenKey: TrendlyneScreenKey; label: string; accentClass: string }) {
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

  const dotClass = accentClass === 'emerald' ? 'bg-emerald-500' : accentClass === 'red' ? 'bg-red-500' : 'bg-amber-500';
  const textAccentCls = accentClass === 'emerald' ? 'text-emerald-600' : accentClass === 'red' ? 'text-red-500' : 'text-amber-600';

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm overflow-visible">
      <div className={`text-[11px] uppercase tracking-wider ${textAccentCls} font-bold mb-3 flex items-center gap-2`}>
        <span className={`w-2.5 h-2.5 rounded-full ${dotClass}`} />
        {label}
        <span className="ml-auto text-[8px] text-slate-400 font-normal">{loading ? 'loading' : error ? 'err' : `${items.length}`}</span>
      </div>
      <div className="space-y-1.5">
        {loading && items.length === 0 && (
          <div className="text-[11px] text-slate-400 px-3 py-2 animate-pulse">Loading...</div>
        )}
        {error && items.length === 0 && (
          <div className="text-[11px] text-red-400 px-3 py-2">{error}</div>
        )}
        {items.map((item, idx) => {
          const currentPrice = item.tooltipParams.find((p) => p.key === 'currentPrice')?.value ?? '—';
          return (
            <a
              key={`${screenKey}-${item.name}-${idx}`}
              href={item.stockurl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between px-3 py-2 rounded-lg transition-all hover:bg-slate-50 hover:scale-[1.01] cursor-pointer"
              style={{
                backgroundColor: idx % 2 === 0 ? 'rgba(248, 250, 252, 0.5)' : 'transparent',
                borderBottom: '1px solid rgba(226, 232, 240, 0.4)',
              }}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[9px] font-bold text-slate-400 w-4 text-right">{String(idx + 1).padStart(2, '0')}</span>
                <span className="text-[12px] font-bold text-slate-800 truncate">{item.name}</span>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <span className={`text-[11px] font-bold ${textAccentCls}`}>{item.value}%</span>
                <span className="text-[10px] text-slate-500">₹{currentPrice}</span>
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}

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
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-5 shadow-sm min-h-[320px] overflow-visible">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">NIFTY TOP 5 GAINERS & LOSERS</span>
        <span className="text-[9px] text-slate-400 bg-slate-100 px-2 py-1 rounded">
          {loading ? 'LOADING' : error ? 'ERROR' : `${totalStocks} stocks`}
        </span>
      </div>
      {error && totalStocks === 0 && (
        <div className="text-[11px] text-red-500 px-3 py-2 mb-3">{error}</div>
      )}
      <div className="grid grid-cols-2 gap-4">
        {NSE_TOP_FIVE_CATEGORIES.map((category) => {
          const stocks = categories[category.key] ?? [];
          const accentClass = getCategoryAccentClass(category.key);
          const dotClass = getCategoryDotClass(category.key);
          const rowStyle = getCategoryRowStyle(category.key);

          return (
            <div key={category.key}>
              <div className={`text-[11px] uppercase tracking-wider ${accentClass} font-bold mb-3 flex items-center gap-2`}>
                <span className={`w-2.5 h-2.5 rounded-full ${dotClass}`} />
                {category.label}
              </div>
              <div className="space-y-2">
                {stocks.length === 0 && (
                  <div className="text-[11px] text-slate-400 px-3 py-2">No data</div>
                )}
                {stocks.map((stock, index) => {
                  const ticker = stock.symbol ?? 'UNKNOWN';
                  const changeText = typeof stock.pchange === 'number' ? `${stock.pchange > 0 ? '+' : ''}${stock.pchange.toFixed(2)}%` : 'N/A';
                  const changeClass = typeof stock.pchange === 'number' ? (stock.pchange >= 0 ? 'text-emerald-600' : 'text-red-500') : 'text-slate-500';

                  return (
                    <div
                      key={`${category.key}-${ticker}-${index}`}
                      className="group flex items-center justify-between px-4 py-2.5 rounded-lg transition-all hover:scale-[1.02] cursor-default overflow-visible"
                      style={rowStyle}
                    >
                      <NseTickerTooltip stock={stock} ticker={ticker} />
                      <div className="flex items-center gap-3">
                        <span className="text-[12px] text-slate-500">{formatNseNumber(stock.lastPrice)}</span>
                        <span className={`text-[12px] font-bold ${changeClass}`}>{changeText}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Trendlyne Panels */}
      <div className="mt-5 pt-4 border-t border-slate-200">
        <div className="flex items-center gap-2 mb-4">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
          <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">TRENDLYNE SCREENERS</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {TRENDLYNE_SCREENS.map((screen) => (
            <TrendlynePanel key={screen.key} screenKey={screen.key} label={screen.label} accentClass={screen.accent} />
          ))}
        </div>
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

function NseHeatMapTooltip({ stock, ticker, colors }: { stock: NseEquityStock; ticker: string; colors: { bg: string; text: string; border: string } }) {
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [anchor, setAnchor] = useState({ x: 0, y: 0 });
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewportWidth = typeof window === 'undefined' ? 1024 : window.innerWidth;
  const viewportHeight = typeof window === 'undefined' ? 768 : window.innerHeight;
  const tooltipWidth = 384;
  const tooltipLeft = Math.max(12, Math.min(anchor.x + 12, viewportWidth - tooltipWidth - 12));
  const tooltipTop = Math.max(12, Math.min(anchor.y, viewportHeight - 320));

  const cancelClose = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };

  const scheduleClose = () => {
    closeTimer.current = setTimeout(() => setVisible(false), 180);
  };

  const showTooltip = () => {
    cancelClose();
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      setAnchor({ x: rect.left, y: rect.top });
    }
    setVisible(true);
  };

  return (
    <>
      <div
        ref={triggerRef}
        className="flex flex-col items-center justify-center rounded-md py-3 px-2 transition-all hover:shadow-md cursor-default"
        style={{
          backgroundColor: colors.bg,
          border: `1px solid ${colors.border}`,
        }}
        onMouseEnter={showTooltip}
        onMouseLeave={scheduleClose}
        onFocus={showTooltip}
        onBlur={() => { cancelClose(); setVisible(false); }}
        tabIndex={0}
      >
        <span className="text-[10px] font-bold leading-tight" style={{ color: colors.text }}>
          {ticker}
        </span>
        <span className="text-[9px] font-semibold mt-1" style={{ color: colors.text }}>
          {typeof stock.pChange === 'number' ? `${stock.pChange > 0 ? '+' : ''}${stock.pChange.toFixed(2)}%` : 'N/A'}
        </span>
      </div>
      <div
        aria-hidden={!visible}
        className={`fixed z-50 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-slate-300 bg-white p-4 text-left shadow-lg transition-all pointer-events-auto overflow-y-auto max-h-[calc(100vh-2rem)] ${visible ? 'visible opacity-100' : 'invisible opacity-0'}`}
        style={{ left: `${tooltipLeft}px`, top: `${tooltipTop}px` }}
        onMouseEnter={() => { cancelClose(); setVisible(true); }}
        onMouseLeave={scheduleClose}
      >
        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-bold mb-3">API DATA</div>
        <div className="overflow-visible max-h-none">
          <NseTooltipContent data={stock} />
        </div>
      </div>
    </>
  );
}

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

  const heatMapStocks = useMemo(
    () => stocks.map((stock) => ({ stock, ticker: stock.symbol ?? 'UNKNOWN', changePct: typeof stock.pChange === 'number' ? stock.pChange : 0 })),
    [stocks]
  );

  const gainers = useMemo(() => heatMapStocks.filter(s => s.changePct >= 0).length, [heatMapStocks]);
  const losers = useMemo(() => heatMapStocks.filter(s => s.changePct < 0).length, [heatMapStocks]);

  if (loading || (error && heatMapStocks.length === 0)) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-5 shadow-sm min-h-[520px]">
        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-bold mb-3">NIFTY 100 HEAT MAP</div>
        <div className="text-[11px] text-slate-400">{error ?? 'Waiting for live data...'}</div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-5 shadow-sm min-h-[520px]">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">NIFTY 100 HEAT MAP</span>
          <span className="text-[10px] text-slate-400 bg-slate-100 px-2 py-1 rounded">{heatMapStocks.length} stocks</span>
        </div>
        <div className="flex items-center gap-3 text-[9px] uppercase tracking-wider text-slate-400">
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded bg-emerald-800" /> Gainers <span className="text-emerald-700 font-bold">{gainers}</span></span>
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded bg-red-800" /> Losers <span className="text-red-700 font-bold">{losers}</span></span>
        </div>
      </div>
      <div className="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10 gap-2">
        {heatMapStocks.map((stock) => {
          const colors = getHeatColor(stock.changePct);
          return (
            <NseHeatMapTooltip
              key={stock.ticker}
              stock={stock.stock}
              ticker={stock.ticker}
              colors={colors}
            />
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
  if (!items?.length) {
    return (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 p-3 border-b border-slate-100 bg-gradient-to-r from-slate-50/80 to-white">
          <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
          <span className="text-[9px] uppercase tracking-widest text-slate-500 font-bold">LIVE NEWS FEED</span>
          <span className="ml-auto text-[8px] text-slate-400 uppercase tracking-wider">Waiting for data</span>
        </div>
        <div className="p-8 text-center text-slate-400 text-[10px]">No news stories available.</div>
      </div>
    );
  }

  const timeAgo = (dateStr: string) => {
    const diff = now - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  };

  const TRACK_HEIGHT = 38;
  const VISIBLE_ITEMS = 15;

  return (
    <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden flex flex-col flex-1 min-h-[580px]">
      {/* Header - no padding left/right to match full width */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-slate-100 bg-gradient-to-r from-slate-50/80 to-white flex-shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-[9px] uppercase tracking-widest text-slate-600 font-bold">Live News Feed</span>
        <span className="ml-auto text-[8px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-100">
          {items.length} stories
        </span>
      </div>

      {/* Ticker track with continuous scroll - no padding */}
      <div className="relative flex-1 overflow-hidden" style={{ minHeight: TRACK_HEIGHT * 2 }}>
        <div
          className="hover:[animation-play-state:paused] absolute inset-0"
          style={{
            animation: "tickerScroll 30s linear infinite",
          }}
        >
          {items.map((item, i) => (
            <a
              key={`${item.title}-${i}`}
              href={item.link}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-2.5 border-b border-slate-100 px-4 py-2 group hover:bg-emerald-50/50 transition-all duration-200 cursor-pointer"
              style={{ minHeight: TRACK_HEIGHT }}
            >
              {/* Sequence badge */}
              <span className="text-[8px] font-bold text-slate-400 bg-slate-100 w-5 h-5 flex items-center justify-center rounded border border-slate-200 flex-shrink-0 mt-0.5">
                {String(i + 1).padStart(2, "0")}
              </span>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <span className="text-[11px] font-semibold text-slate-800 leading-snug line-clamp-2 group-hover:text-emerald-700 transition-colors">
                  {item.title}
                </span>
                <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                  <span className="text-[8px] font-semibold text-slate-400 uppercase tracking-wider truncate max-w-[100px]">
                    {item.source.split(" ").slice(0, 2).join(" ")}
                  </span>
                  {item.summary && (
                    <>
                      <span className="text-slate-300">·</span>
                      <span className="text-[9px] text-slate-500 line-clamp-1">{item.summary}</span>
                    </>
                  )}
                </div>
              </div>

              {/* Timestamp */}
              <span className="text-[8px] font-mono text-slate-400 flex-shrink-0 mt-0.5">
                {timeAgo(item.publishedAt)}
              </span>
            </a>
          ))}
        </div>
      </div>

      <style>{`
        @keyframes tickerScroll {
          0%   { transform: translateY(0%); }
          100% { transform: translateY(-50%); }
        }
      `}</style>
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
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
              <div className="lg:col-span-2">
                <GlobalIndicesGrid items={globalIndices} staleLabel={staleMacroLabel} />
              </div>
              <div>
                <CommoditiesFxGrid items={commodities} staleLabel={staleMacroLabel} />
              </div>
            </div>

            {/* Row 2: Left column — Gainers/Losers + News Feed | Right column — NIFTY 100 Heat Map */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-stretch">
              <div className="flex flex-col gap-5">
                <GainersLosersHeatmap />
                <NewsFeedPanel items={liveMarket?.news} now={now} />
              </div>
              <div>
                <Nifty100HeatMap />
              </div>
            </div>

            {/* Row 3: India Markets */}
            <div className="grid grid-cols-1 gap-4 items-start">
              <IndiaMarketsGrid items={currentMacros} staleLabel={staleMacroLabel} />
            </div>
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