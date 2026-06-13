'use client';

import React, { useMemo, useState } from 'react';
import {
  useMarketData,
  type LiveStock,
  type MacroRow,
  type LedgerStock,
  type SelectionMeta,
  type TerminalIntelligence,
} from '@/lib/market-api';
import ForensicPanel from './components/ForensicPanel';
import RightDrawer from './components/RightDrawer';

type DrawerContent = {
  stock?: LiveStock | LedgerStock | null;
  analysis?: (TerminalIntelligence & {
    selectionMeta?: SelectionMeta;
    isSnapshotFallback?: boolean;
    error?: string;
  }) | null;
  snapshot?: {
    newsSummary?: string | undefined;
    llmError?: string | null;
    isSnapshotFallback: boolean;
    selectionMeta?: SelectionMeta | null;
    poolDescription?: string | null;
  } | null;
};

type TabKey = 'marketSnapshot' | 'assetMatrix' | 'icGates';

function GlobalIndicesGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-slate-900/80 border border-slate-700 rounded-lg p-4 text-slate-400 text-[10px]">
        Waiting for global macro data.
      </div>
    );
  }

  return (
    <div className="bg-slate-900/80 border border-slate-700 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[9px] uppercase tracking-wider text-slate-400">GLOBAL INDICES</span>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {items.map((item) => (
          <div key={`${item.label}-${item.val}-${item.state}`} className="bg-slate-800/70 border border-slate-700/60 p-2 rounded">
            <span className="text-[9px] text-slate-400 block uppercase tracking-wider">{item.label}</span>
            <span className="text-sm font-bold text-white block mt-0.5">{item.val}</span>
            <span
              className={`text-[9px] block ${
                item.state === 'POSITIVE' ? 'text-emerald-500' : 'text-red-500'
              }`}
            >
              {item.delta}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function IndiaMarketsGrid({ items, staleLabel }: { items: MacroRow[]; staleLabel?: string }) {
  if (!items.length) {
    return (
      <div className="bg-[#070919] border border-slate-800 rounded-lg p-4 text-slate-500 text-[10px]">
        Waiting for Indian market data.
      </div>
    );
  }

  return (
    <div className="bg-[#070919] border border-slate-800 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[9px] uppercase tracking-wider text-slate-400">INDIA MARKETS</span>
        {staleLabel && <span className="text-[9px] text-slate-500 uppercase">{staleLabel}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {items.map((item) => (
          <div key={`${item.label}-${item.val}-${item.state}`} className="bg-[#04050d] border border-slate-800/60 p-2 rounded">
            <span className="text-[9px] text-slate-400 block uppercase tracking-wider">{item.label}</span>
            <span className="text-sm font-bold text-white block mt-0.5">{item.val}</span>
            <span
              className={`text-[9px] block ${
                item.state === 'POSITIVE' ? 'text-emerald-500' : 'text-red-500'
              }`}
            >
              {item.delta}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StockDetailPanel({ stock }: { stock?: LiveStock | LedgerStock | null }) {
  if (!stock) {
    return (
      <div className="bg-[#070919] border border-emerald-500/10 rounded-lg p-4 text-slate-500 min-h-[120px] flex items-center justify-center text-[10px]">
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
    <div className="bg-[#070919] border border-emerald-500/20 rounded-lg p-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-slate-400 text-[10px] uppercase tracking-wider">{name}</div>
          <div className="flex items-baseline gap-3 mt-1">
              <span className="text-3xl font-black text-white">{normalizedPrice}</span>
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
        <div className="bg-[#04050d] border border-slate-800 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">Open</div>
          <div className="font-bold text-white mt-0.5">{open ?? 'N/A'}</div>
        </div>
        <div className="bg-[#04050d] border border-slate-800 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">High</div>
          <div className="font-bold text-white mt-0.5">{high ?? 'N/A'}</div>
        </div>
        <div className="bg-[#04050d] border border-slate-800 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">Low</div>
          <div className="font-bold text-white mt-0.5">{low ?? 'N/A'}</div>
        </div>
        <div className="bg-[#04050d] border border-slate-800 p-2 rounded">
          <div className="text-slate-500 uppercase tracking-wider text-[9px]">Volume</div>
          <div className="font-bold text-white mt-0.5">{volume != null ? new Intl.NumberFormat().format(volume) : 'N/A'}</div>
        </div>
      </div>
    </div>
  );
}

function AISummaryPanel({ summary, llmError, isSnapshotFallback, selectionMeta }: { summary?: string; llmError?: string | null; isSnapshotFallback: boolean; selectionMeta?: { mode?: string; reason?: string; dataDate?: string } | null }) {
  if (llmError) {
    return (
      <div className="bg-[#070919] border border-amber-700/40 rounded-lg p-3">
        <div className="text-[9px] uppercase tracking-wider text-amber-400 mb-1">AI SUMMARY</div>
        <p className="text-[11px] text-amber-200 leading-relaxed">{llmError}</p>
      </div>
    );
  }

  if (summary) {
    return (
    <div className="bg-slate-900/80 border border-slate-700 rounded-lg p-3">
        <div className="text-[9px] uppercase tracking-wider text-slate-400 mb-1">AI SUMMARY</div>
        <p className="text-[11px] text-slate-300 leading-relaxed">{summary}</p>
      </div>
    );
  }

  if (isSnapshotFallback) {
    return (
      <div className="bg-[#070919]/60 border border-amber-700/30 rounded-lg p-3">
        <div className="text-[9px] uppercase tracking-wider text-slate-400 mb-1">AI SUMMARY</div>
        <p className="text-[11px] text-amber-300/90 leading-relaxed">Top market catalysts were not available from the current news feed.</p>
        {selectionMeta?.reason && <p className="text-[9px] text-slate-500 mt-1">Basis: {selectionMeta.reason}</p>}
      </div>
    );
  }

  return (
    <div className="bg-[#070919] border border-slate-800 rounded-lg p-3">
      <div className="text-[9px] uppercase tracking-wider text-slate-400 mb-1">AI SUMMARY</div>
      <p className="text-[11px] text-slate-500 leading-relaxed">Top market catalysts were not available from the current news feed.</p>
    </div>
  );
}

function LiveIntelligencePanel({ count, description }: { count: number; description?: string | null }) {
  return (
    <div className="bg-[#070919] border border-slate-800 rounded-lg p-3">
      <div className="text-[9px] uppercase tracking-wider text-slate-400 mb-1">
        LIVE INTELLIGENCE · {count} NODES
      </div>
      <p className="text-[11px] text-slate-400 leading-relaxed">
        Dynamic live universe label applied for Nifty 500. Gemini / Pydantic mapped payload from live Angel One ingestion stream.
      </p>
      {description && <p className="text-[10px] text-slate-500 mt-1 leading-relaxed">{description}</p>}
    </div>
  );
}

function StructuredReasoningOutput({ intelligence }: { intelligence?: TerminalIntelligence }) {
  const hasData = !!intelligence;

  return (
    <div className="bg-[#04050d] border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Structured Reasoning Output</h3>
          <p className="text-[10px] text-slate-500 mt-0.5">Gemini / Pydantic mapped payload from the live ingestion stream.</p>
        </div>
        <div className="text-[10px] text-slate-500">{hasData ? 'Available' : 'Unavailable'}</div>
      </div>

      {hasData ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[10px] text-slate-300">
            <div className="bg-[#070919] border border-emerald-500/10 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-400 mb-1">News Catalysts</div>
              <p className="text-[11px] text-slate-300 leading-relaxed">{intelligence.news_catalysts_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-[#070919] border border-emerald-500/10 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-400 mb-1">Macro Anchors</div>
              <p className="text-[11px] text-slate-300 leading-relaxed">{intelligence.macro_anchors_card ?? 'Not produced.'}</p>
            </div>
            <div className="bg-[#070919] border border-emerald-500/10 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-400 mb-1">Insider / Insti Activity</div>
              <p className="text-[11px] text-slate-300 leading-relaxed">{intelligence.insider_insti_activity_card ?? 'Not produced.'}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px] text-slate-300 mt-3">
            <div className="bg-[#070919] border border-emerald-500/10 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-400 mb-1">Structural Thesis</div>
              <p className="text-[10px] text-slate-400 leading-relaxed">
                <span className="text-slate-300">Why Interested: </span>
                {intelligence.why_interested ?? 'Not produced.'}
              </p>
              <p className="text-[10px] text-slate-400 mt-1 leading-relaxed">
                <span className="text-slate-300">Forward Revenue: </span>
                {intelligence.future_revenue_model ?? 'Not produced.'}
              </p>
            </div>
            <div className="bg-[#070919] border border-emerald-500/10 p-3 rounded-lg">
              <div className="text-[9px] uppercase tracking-wider text-emerald-400 mb-1">Risk Calc / Factor Hub</div>
              {intelligence.active_risk_calc ? (
                <div className="space-y-1">
                  {Object.entries(intelligence.active_risk_calc).map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-slate-500 uppercase tracking-wider text-[9px]">{label.replace(/_/g, ' ')}</span>
                      <span className="text-slate-300">{String(value)}</span>
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

  const { data: liveMarket, status: feedStatus, refreshOnDemand, invalidateKey } = useMarketData(selectedPool);
  const stocks = liveMarket?.stocks ?? [];
  const selectedTickerForView = useMemo(() => selectedTicker || stocks[0]?.ticker || '', [selectedTicker, stocks]);
  const poolOptions = liveMarket?.availablePools ?? ['Nifty 500', 'Nifty 100', 'Next 100', 'Mid Cap', 'Small Cap', 'Micro Cap', 'Live Universe'];

  const currentMacros = useMemo(() => liveMarket?.macroDataStrip?.[terminalMode] ?? [], [terminalMode, liveMarket]);
  const globalMacroItems = useMemo(() => {
    const g = liveMarket?.globalMacro;
    if (!g) return [];
    return [...(g.indices ?? []), ...(g.commodities ?? [])];
  }, [liveMarket]);

  const newsSummary = liveMarket?.newsSummary;
  const llmError = liveMarket?.llmError;
  const selectionMeta = liveMarket?.selectionMeta ?? null;
  const intelligence = liveMarket?.terminalIntelligence as TerminalIntelligence | undefined;
  const isSnapshotFallback = liveMarket?.isSnapshotFallback ?? false;

  const selectedQuote = useMemo(
    () => selectedTickerForView ? liveMarket?.stockQuotes?.[selectedTickerForView] ?? stocks.find((stock) => stock.ticker === selectedTickerForView) : undefined,
    [selectedTickerForView, liveMarket, stocks]
  );

  const handleSelect = async (t: string) => {
    setSelectedTicker(t);
    setDrawerOpen(true);
    try {
      const params = new URLSearchParams();
      if (t) params.set("ticker", t);
      if (selectedPool) params.set("pool", selectedPool);
      const resp = await fetch(`/api/terminal-intelligence${params.toString() ? `?${params.toString()}` : ""}`);
      if (resp.ok) {
        const body = await resp.json();
        setDrawerContent({
          stock: stocks.find((s) => s.ticker === t) ?? null,
          analysis: { ...(body.terminalIntelligence ?? body), selectionMeta: body.selectionMeta, isSnapshotFallback: body.isSnapshotFallback },
          snapshot: {
            newsSummary: liveMarket?.newsSummary,
            llmError: liveMarket?.llmError,
            isSnapshotFallback: liveMarket?.isSnapshotFallback ?? false,
            selectionMeta: liveMarket?.selectionMeta ?? null,
            poolDescription: liveMarket?.poolDescription ?? null,
          }
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

  const now = Date.now();
  const snapshotAgeMin = liveMarket?.updatedAt ? Math.round((now - new Date(liveMarket.updatedAt).getTime()) / 60000) : null;
  const staleMacroLabel = snapshotAgeMin == null ? "" : `STALE ${snapshotAgeMin}M`;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-100 font-mono text-xs antialiased">
      <div className="max-w-[1600px] mx-auto p-4 space-y-4">
        <header className="bg-[#070919] border border-slate-800 rounded-xl shadow-xl">
          <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={`w-2.5 h-2.5 rounded-full ${feedStatus === 'live' ? 'bg-emerald-500 animate-pulse' : feedStatus === 'loading' ? 'bg-amber-500' : 'bg-red-500'}`} />
                <h1 className="text-sm font-black tracking-wider text-white">IROS Live Market Intelligence</h1>
              </div>
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider xl:hidden">Nifty 500</span>
            </div>

            <div className="flex items-center justify-between xl:justify-end gap-3">
              <span className="text-[10px] font-bold uppercase text-slate-400 hidden xl:inline tracking-wider">
                {liveMarket?.rawSources?.join(' · ') ?? 'Reuters · TradingView · Moneycontrol'}
              </span>
              <div className="flex items-center gap-2 text-[10px] text-slate-400">
                <span className="hidden sm:inline">
                  {liveMarket?.updatedAt ? new Date(liveMarket.updatedAt).toLocaleTimeString() : '--:--'} IST
                </span>
                <button
                  onClick={handleRefresh}
                  disabled={feedStatus === 'loading'}
                  className="px-3 py-1.5 rounded-full bg-emerald-500 text-slate-950 text-[10px] font-black uppercase tracking-wider hover:bg-emerald-400 disabled:opacity-50 transition"
                >
                  Snapshot
                </button>
              </div>
            </div>
          </div>

          {isSnapshotFallback && (
            <div className="px-4 pb-3">
              <div className="bg-amber-900/10 text-amber-200 border border-amber-700 p-2 rounded text-[11px]">
                Snapshot fallback active — outside scheduled IST refresh window. Showing latest saved analysis.
              </div>
            </div>
          )}
        </header>

        <nav className="bg-[#070919] border border-slate-800 rounded-xl flex gap-1 p-1">
          {([
            { key: 'marketSnapshot' as TabKey, label: 'MARKET SNAPSHOT' },
            { key: 'assetMatrix' as TabKey, label: 'ASSET MATRIX' },
            { key: 'icGates' as TabKey, label: 'IC GATES & REASONING' },
          ]).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-2 text-[11px] font-bold uppercase tracking-wider rounded-lg transition relative ${
                activeTab === tab.key ? 'text-white' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {activeTab === tab.key && (
                <span className="absolute inset-x-2 -bottom-0.5 h-0.5 bg-teal-500 rounded-full" />
              )}
              {tab.label}
            </button>
          ))}
        </nav>

        {activeTab === 'marketSnapshot' && (
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            <div className="xl:col-span-8 space-y-4">
              <GlobalIndicesGrid items={globalMacroItems} staleLabel={staleMacroLabel} />
              <IndiaMarketsGrid items={currentMacros} staleLabel={staleMacroLabel} />
            </div>

            <div className="xl:col-span-4 space-y-4">
    <div className="bg-slate-900/80 border border-slate-700 rounded-lg p-3">
                <div className="text-[9px] uppercase tracking-wider text-slate-400 mb-2">Snapshot Status</div>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Snapshot basis active. Open ASSET MATRIX, select a ticker to view quote, AI summary and live intelligence.
                </p>
              </div>
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
            <AISummaryPanel
              summary={newsSummary}
              llmError={llmError}
              isSnapshotFallback={isSnapshotFallback}
              selectionMeta={selectionMeta}
            />
            <LiveIntelligencePanel count={stocks.length} description={liveMarket?.poolDescription} />
          </div>
        )}

        {activeTab === 'icGates' && (
          <div className="bg-[#070919] border border-slate-800 rounded-xl p-4">
            <StructuredReasoningOutput intelligence={intelligence} />
          </div>
        )}
      </div>

      <RightDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} content={drawerContent} />
    </div>
  );
}
