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

type TabKey = 'marketSnapshot' | 'assetMatrix' | 'icGates';

const INDIA_MARKET_LABELS = new Set(['NIFTY 50', 'SENSEX', 'NIFTY BANK', 'NIFTY IT', 'NIFTY PHARMA']);
const GLOBAL_ONLY_LABELS = new Set(['BRENT CRUDE', 'BRENT CRUDE OIL']);

function normalizeMarketLabel(label: string) {
  return label.toUpperCase().replace(/\s+/g, ' ');
}

function marketStateClass(state: string) {
  if (state === 'POSITIVE') return 'text-emerald-500';
  if (state === 'NEGATIVE') return 'text-red-500';
  return 'text-slate-400';
}

function GlobalIndicesGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-4 text-slate-400 text-[10px] shadow-sm">
        Waiting for global macro data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">GLOBAL INDICES</span>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {items.map((item) => (
          <div key={`${item.label}-${item.val}-${item.state}`} className="bg-slate-50 border border-slate-100 p-2 rounded">
            <span className="text-[9px] text-slate-500 block uppercase tracking-wider">{item.label}</span>
            <span className="text-sm font-bold text-slate-900 block mt-0.5">{item.val}</span>
            <span
              className={`text-[9px] block ${marketStateClass(item.state)}`}
            >
              {item.delta}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CommoditiesFxGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-4 text-slate-400 text-[10px] shadow-sm">
        Waiting for commodities & FX data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">COMMODITIES & FX</span>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        {items.map((item) => {
          let displayLabel = item.label;
          if (displayLabel === 'BRENT CRUDE OIL') displayLabel = 'BRENT CRUDE';
          return (
            <div key={`${item.label}-${item.val}-${item.state}`} className="bg-slate-50 border border-slate-100 p-2 rounded">
              <span className="text-[9px] text-slate-500 block uppercase tracking-wider">{displayLabel}</span>
              <span className="text-sm font-bold text-slate-900 block mt-0.5">{item.val}</span>
              <span
                className={`text-[9px] block ${marketStateClass(item.state)}`}
              >
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
      <div className="bg-white border border-slate-200 rounded-lg p-4 text-slate-400 text-[10px] shadow-sm">
        Waiting for Indian market data.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">INDIA MARKETS</span>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2">
        {items.map((item) => {
          let displayLabel = item.label;
          if (displayLabel === 'USD / INR Spot') displayLabel = 'USD / INR';
          return (
            <div key={`${item.label}-${item.val}-${item.state}`} className="bg-slate-50 border border-slate-100 p-2 rounded">
              <span className="text-[9px] text-slate-500 block uppercase tracking-wider">{displayLabel}</span>
              <span className="text-sm font-bold text-slate-900 block mt-0.5">{item.val}</span>
              <span
                className={`text-[9px] block ${marketStateClass(item.state)}`}
              >
                {item.delta}
              </span>
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
      <div className="bg-white border border-emerald-200 rounded-lg p-4 text-slate-500 min-h-[120px] flex items-center justify-center text-[10px] shadow-sm">
        Select an asset to view quote detail.
      </div>
    );
  }

  const name = 'name' in stock ? stock.name : stock.ticker;
  const price = 'ltp' in stock ? stock.ltp : stock.live_price;
  const normalizedPrice = price ? `₹${String(price).replace(/[₹]+/g, '')}` : '';
  const open = 'open' in stock ? stock.open : undefined;
  const high = 'high' in stock ? stock.high : undefined;
  const low = 'low' in stock ? stock.low : undefined;
  const volume = 'volume' in stock ? stock.volume : undefined;
  const delta = 'delta' in stock ? (stock as LiveStock).delta : (stock as LedgerStock).delta;

  return (
    <div className="bg-white border border-emerald-200 rounded-lg p-4 shadow-sm">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-slate-500 text-[10px] uppercase tracking-wider">{name}</div>
          <div className="flex items-baseline gap-3 mt-1">
              <span className="text-3xl font-black text-slate-900">{normalizedPrice}</span>
            {delta && (
              <span
                className={`text-xs font-bold ${
                  delta.includes('+') ? 'text-emerald-500' : 'text-red-500'
                }`}
              >
                {delta}%
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
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm">
      <div className="flex items-center justify-between p-3 border-b border-slate-100">
        <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">LIVE NEWS FEED</span>
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
                  className="text-[11px] font-medium text-slate-800 hover:text-teal-700 leading-tight block truncate"
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
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm" />
  );
}

function StructuredReasoningOutput({ intelligence }: { intelligence?: TerminalIntelligence }) {
  const hasData = !!intelligence;

  return (
    <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
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
            <div className="bg-white border border-emerald-100 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">News Catalysts</div>
              <p className="text-[11px] text-slate-700 leading-relaxed">{intelligence.news_catalysts_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-white border border-emerald-100 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Macro Anchors</div>
              <p className="text-[11px] text-slate-700 leading-relaxed">{intelligence.macro_anchors_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-white border border-emerald-100 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Insider / Insti Activity</div>
              <p className="text-[11px] text-slate-700 leading-relaxed">{intelligence.insider_insti_activity_card ?? 'Not produced.'}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px] text-slate-700 mt-3">
            <div className="bg-white border border-emerald-100 p-3 rounded-lg">
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
            <div className="bg-white border border-emerald-100 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Risk Calc / Factor Hub</div>
              {intelligence.active_risk_calc ? (
                <div className="space-y-1">
                  {Object.entries(intelligence.active_risk_calc).map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-slate-500 uppercase tracking-wider text-[9px]">{label.replace(/_/g, ' ')}</span>
                      <span className="text-slate-700">{String(value)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[10px] text-slate-500">Risk calc data not available.</p>
              )}
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

  const { data: liveMarket, status: feedStatus, refreshOnDemand, invalidateKey } = useMarketData(selectedPool);
  const stocks = liveMarket?.stocks ?? [];
  const selectedTickerForView = useMemo(() => selectedTicker || stocks[0]?.ticker || '', [selectedTicker, stocks]);
  const poolOptions = liveMarket?.availablePools ?? ['Nifty 500', 'Nifty 100', 'Next 100', 'Mid Cap', 'Small Cap', 'Micro Cap', 'Live Universe'];

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
  const intelligence = useMemo(() => tickerIntelligence ?? marketIntelligence, [tickerIntelligence, marketIntelligence]);

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
        <header className="bg-white border border-slate-200 rounded-xl shadow-sm">
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
                  Snapshot
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

        <nav className="bg-white border border-slate-200 rounded-xl flex gap-1 p-1 shadow-sm">
          {([
            { key: 'marketSnapshot' as TabKey, label: 'MARKET SNAPSHOT' },
            { key: 'assetMatrix' as TabKey, label: 'ASSET MATRIX' },
            { key: 'icGates' as TabKey, label: 'IC GATES & REASONING' },
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
          <div className="grid grid-cols-1 gap-4">
            <div className="space-y-4">
              <GlobalIndicesGrid items={globalIndices} staleLabel={staleMacroLabel} />
              <CommoditiesFxGrid items={commodities} staleLabel={staleMacroLabel} />
              <IndiaMarketsGrid items={currentMacros} staleLabel={staleMacroLabel} />
              <NewsFeedPanel items={liveMarket?.news} now={now} />
            </div>
          </div>
        )}

        {activeTab === 'assetMatrix' && (
          <div className="space-y-4">
            <ForensicPanel
              pool={selectedPool}
              onSelect={handleSelect}
              invalidateKey={invalidateKey}
            />
            <StockDetailPanel stock={selectedQuote} />
            <LiveIntelligencePanel />
          </div>
        )}

        {activeTab === 'icGates' && (
          <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
            <StructuredReasoningOutput intelligence={intelligence} />
          </div>
        )}
      </div>

      <RightDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} content={drawerContent} />
    </div>
  );
}
