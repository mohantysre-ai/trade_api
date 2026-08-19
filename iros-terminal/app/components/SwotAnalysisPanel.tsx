'use client';

import React, { useMemo, useState, useEffect } from "react";
import type { AITickerNewsReport, TerminalIntelligence } from "@/lib/market-api";
import { buildFactSwot, type DrawerStockFacts, type IntradayMetrics } from "@/lib/drawer-research";
import type { TrendlyneCardSummary } from "@/lib/intelligence-summary";

type SwotAnalysisPanelProps = {
  ticker?: string;
  companyName?: string;
  intraday?: IntradayMetrics | null;
  tickerNews?: AITickerNewsReport | null;
  terminalAnalysis?: TerminalIntelligence | null;
  stockFacts?: DrawerStockFacts | null;
  trendlyne?: TrendlyneCardSummary | null;
  researchLoading?: boolean;
  researchError?: string | null;
};

/* ── Color-coded quadrant card (light theme: tinted panel + dark text) ── */
function QuadrantCard({
  title,
  icon,
  items,
  gradient,
  accentColor,
  borderGlow,
  titleClass,
  loading = false,
}: {
  title: string;
  icon: React.ReactNode;
  items: string[];
  gradient: string;
  accentColor: string;
  borderGlow: string;
  titleClass: string;
  loading?: boolean;
}) {
  return (
    <div className={`relative overflow-hidden rounded-xl border ${borderGlow} shadow-md group hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5`}>
      <div className={`absolute inset-0 ${gradient}`} />
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-slate-300/40 to-transparent" />

      <div className="relative p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-white shadow-sm border border-slate-100" style={{ color: accentColor }}>
            {icon}
          </div>
          <span className={`text-[11px] font-black uppercase tracking-wider ${titleClass}`}>
            {title}
          </span>
        </div>

        <div className="space-y-2">
          {items.map((item, i) => (
            <div key={i} className="flex items-start gap-2 group/item">
              <span
                className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 transition-all duration-300 group-hover/item:scale-150"
                style={{ backgroundColor: accentColor }}
              />
              <span className="text-[11px] text-slate-700 leading-relaxed group-hover/item:text-slate-900 transition-colors">
                {item}
              </span>
            </div>
          ))}
          {items.length === 0 && (
            <span className="text-[10px] text-slate-400 italic">{loading ? "Loading verified data…" : "No fact-grounded evidence available."}</span>
          )}
        </div>

        <div
          className="absolute -bottom-2 -right-2 w-16 h-16 rounded-full opacity-10 animate-ping"
          style={{ backgroundColor: accentColor }}
        />
      </div>
    </div>
  );
}

/* ── Animated strength meter ── */
function StrengthMeter({ label, score, color }: { label: string; score: number | null; color: string }) {
  const [animVal, setAnimVal] = useState(0);
  const pct = score == null ? 0 : Math.min(score, 100);

  useEffect(() => {
    const id = setTimeout(() => setAnimVal(pct), 100);
    return () => clearTimeout(id);
  }, [pct]);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</span>
        <span className="text-[10px] font-black tabular-nums" style={{ color }}>{score == null ? "—" : `${score.toFixed(0)}%`}</span>
      </div>
      <div className="relative h-4 rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-1000 ease-out relative"
          style={{
            width: `${animVal}%`,
            background: `linear-gradient(90deg, ${color}40, ${color})`,
          }}
        >
          <div className="absolute inset-0 bg-[linear-gradient(90deg,transparent_0%,rgba(255,255,255,0.3)_50%,transparent_100%)] animate-shimmer" />
        </div>
      </div>
    </div>
  );
}

/* ── Score ring (score centered in middle) ── */
function ScoreRing({ value, label, color }: { value: number | null; label: string; color: string }) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - ((value ?? 0) / 100) * circumference;

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-[90px] h-[90px]">
        <svg width="90" height="90" className="transform -rotate-90 absolute inset-0">
          <circle cx="45" cy="45" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="6" />
          <circle
            cx="45"
            cy="45"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-black tabular-nums leading-none" style={{ color }}>{value == null ? "—" : value.toFixed(0)}</span>
          <span className="text-[8px] uppercase tracking-wider text-slate-400 mt-0.5">{label}</span>
        </div>
      </div>
    </div>
  );
}

/* ── Empty state ── */
function EmptyState() {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(245,158,11,0.08),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(239,68,68,0.06),transparent_36%)]" />
      <div className="relative flex min-h-[240px] sm:min-h-[320px] md:min-h-[400px] flex-col items-center justify-center p-8 text-center">
        <div className="mb-6 relative">
          <div className="h-20 w-20 rounded-3xl swot-icon flex items-center justify-center shadow-xl">
            <svg viewBox="0 0 24 24" fill="none" className="h-10 w-10">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="absolute -top-1 -right-1 h-5 w-5 rounded-full swot-pulse animate-ping" />
        </div>
        <h3 className="text-base font-black uppercase tracking-wider text-slate-900">SWOT Analysis</h3>
        <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">
          Select a stock from the Swing Portfolio to view its Strengths, Weaknesses, Opportunities & Threats.
        </p>
      </div>
    </div>
  );
}

export default function SwotAnalysisPanel({
  ticker,
  companyName,
  intraday,
  tickerNews,
  terminalAnalysis,
  stockFacts,
  trendlyne,
  researchLoading = false,
  researchError,
}: SwotAnalysisPanelProps) {
  const normalizedTicker = ticker?.trim().toUpperCase();
  const [activeView, setActiveView] = useState<'widget' | 'analysis'>('analysis');
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);

  const swotData = useMemo(() => {
    if (!normalizedTicker) return null;
    return buildFactSwot({
      ticker: normalizedTicker,
      intraday,
      tickerNews,
      terminalAnalysis,
      stock: stockFacts,
      trendlyne,
    });
  }, [normalizedTicker, intraday, tickerNews, terminalAnalysis, stockFacts, trendlyne]);

  const widgetUrl = useMemo(() => {
    if (!normalizedTicker) return "";
    return `https://trendlyne.com/web-widget/swot-widget/Poppins/${encodeURIComponent(normalizedTicker)}`;
  }, [normalizedTicker]);

  if (!normalizedTicker) return <EmptyState />;

  return (
    <div className="space-y-4">
      {/* View toggle */}
      <div className="flex items-center gap-2 bg-slate-100 rounded-xl p-1">
        <button
          onClick={() => setActiveView('widget')}
          className={`flex-1 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all ${
            activeView === 'widget' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          Trendlyne Widget
        </button>
        <button
          onClick={() => setActiveView('analysis')}
          className={`flex-1 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all ${
            activeView === 'analysis' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          Fact Analysis
        </button>
      </div>

      {/* Widget view */}
      {activeView === 'widget' && (
        <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_10%,rgba(245,158,11,0.12),transparent_34%),radial-gradient(circle_at_85%_20%,rgba(239,68,68,0.08),transparent_32%)]" />
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-amber-400 via-orange-400 to-red-500" />

          <div className="relative p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <div className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl swot-icon">
                  <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5">
                    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <div className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 swot-pulse animate-pulse" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-baseline gap-2 min-w-0">
                    <span className="truncate text-sm font-black text-slate-950">{companyName ?? normalizedTicker}</span>
                    <span className="truncate text-[9px] font-bold uppercase tracking-wider text-slate-400">{normalizedTicker}</span>
                  </div>
                </div>
              </div>
              <a
                href={widgetUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex flex-shrink-0 items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50/80 px-2.5 py-1 text-[9px] font-black uppercase tracking-wider text-amber-700 transition hover:border-amber-300 hover:bg-amber-100"
              >
                Open
                <svg className="h-3 w-3 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" viewBox="0 0 24 24" fill="none">
                  <path d="M14 4h6v6M20 4l-9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M20 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </a>
            </div>

            <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-inner">
              {!loaded && !errored && (
                <div className="flex flex-col items-center justify-center gap-4 bg-white min-h-[240px] sm:min-h-[320px] md:min-h-[400px]">
                  <div className="relative h-14 w-14 rounded-2xl border border-amber-200 bg-amber-50/80 shadow-lg flex items-center justify-center">
                    <svg className="h-7 w-7 text-amber-500 animate-pulse" viewBox="0 0 24 24" fill="none">
                      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <div className="space-y-2 text-center">
                    <p className="text-xs font-black uppercase tracking-[0.3em] text-amber-600">Loading SWOT</p>
                    <p className="max-w-xs text-[11px] leading-relaxed text-slate-400">Fetching Trendlyne SWOT report for {normalizedTicker}.</p>
                  </div>
                </div>
              )}
              {errored && (
                <div className="relative z-10 flex flex-col items-center justify-center gap-3 p-6 text-center min-h-[240px] sm:min-h-[320px] md:min-h-[400px]">
                  <div className="h-12 w-12 rounded-2xl border border-amber-200 bg-amber-50 text-amber-500 flex items-center justify-center">
                    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none">
                      <path d="M12 9v4M12 17h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  </div>
                  <p className="text-xs font-bold uppercase tracking-wider text-amber-700">Widget Unavailable</p>
                  <p className="max-w-xs text-[11px] leading-relaxed text-slate-500">Open the Trendlyne SWOT widget directly.</p>
                  <a href={widgetUrl} target="_blank" rel="noopener noreferrer" className="rounded-full bg-amber-500 px-4 py-2 text-[11px] font-black text-white transition hover:bg-amber-400">
                    Open Trendlyne SWOT
                  </a>
                </div>
              )}
              <iframe
                key={widgetUrl}
                src={widgetUrl}
                title={`Trendlyne SWOT analysis for ${normalizedTicker}`}
                loading="lazy"
                referrerPolicy="strict-origin-when-cross-origin"
                onLoad={() => setLoaded(true)}
                onError={() => setErrored(true)}
                className="min-h-[240px] sm:min-h-[320px] md:min-h-[400px] h-[min(70dvh,500px)] md:h-[500px] w-full bg-white"
              />
            </div>
          </div>
        </div>
      )}

      {/* AI Analysis view ── light theme quadrant visualizer */}
      {activeView === 'analysis' && swotData && (
        <div className="space-y-3">
          {swotData.partial && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[10px] font-semibold text-amber-900">
              Partial SWOT — only verified source fields are scored; unavailable categories remain unscored.
            </div>
          )}
          {researchError && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[10px] text-amber-900">
              External research unavailable: {researchError}. Snapshot evidence is still shown.
            </div>
          )}
          {!swotData.hasData && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] text-slate-600">
              No fact-grounded SWOT fields available yet for {normalizedTicker}.
            </div>
          )}
          {/* Header card */}
          <div className="rounded-2xl bg-gradient-to-br from-amber-50 via-white to-red-50 border border-amber-200/50 shadow-sm p-4">
            <div className="flex items-center justify-between mb-3">
<div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-lg swot-icon flex items-center justify-center shadow-sm">
                  <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4">
                    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div>
                  <div className="text-sm font-black text-slate-900">{companyName ?? normalizedTicker}</div>
                  <div className="text-[9px] text-slate-500 uppercase tracking-wider">{normalizedTicker} · SWOT REPORT</div>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                <span className="text-[9px] text-amber-600 uppercase tracking-wider font-bold">Fact-grounded</span>
              </div>
            </div>

            {/* Score rings row */}
            <div className="flex justify-around py-2">
              <div className="relative">
                <ScoreRing value={swotData.scores.overall} label="Overall" color="#f59e0b" />
              </div>
              <div className="relative">
                <ScoreRing value={swotData.scores.strength} label="Strength" color="#22c55e" />
              </div>
              <div className="relative">
                <ScoreRing value={swotData.scores.opportunity} label="Opportunity" color="#3b82f6" />
              </div>
              <div className="relative">
                <ScoreRing value={swotData.scores.weakness == null ? null : 100 - swotData.scores.weakness} label="Defense" color="#ef4444" />
              </div>
            </div>
          </div>

          {/* Quadrant grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <QuadrantCard
                title="Strengths"
                accentColor="#059669"
                borderGlow="border-emerald-300"
                gradient="bg-gradient-to-br from-emerald-50 to-white"
                titleClass="text-emerald-800"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.strengths}
                loading={researchLoading}
              />
              <QuadrantCard
                title="Weaknesses"
                accentColor="#dc2626"
                borderGlow="border-red-300"
                gradient="bg-gradient-to-br from-red-50 to-white"
                titleClass="text-red-800"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M6 18L18 6M6 6l12 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.weaknesses}
                loading={researchLoading}
              />
              <QuadrantCard
                title="Opportunities"
                accentColor="#2563eb"
                borderGlow="border-blue-300"
                gradient="bg-gradient-to-br from-blue-50 to-white"
                titleClass="text-blue-800"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M13 7h8m0 0v8m0-8l-9 9-4-4-6 6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.opportunities}
                loading={researchLoading}
              />
              <QuadrantCard
                title="Threats"
                accentColor="#d97706"
                borderGlow="border-amber-300"
                gradient="bg-gradient-to-br from-amber-50 to-white"
                titleClass="text-amber-800"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M12 9v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.threats}
                loading={researchLoading}
              />
            </div>

          {/* Strength meters */}
          <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4 space-y-3">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Key Metrics</span>
            </div>
            <StrengthMeter label="Strengths Score" score={swotData.scores.strength} color="#22c55e" />
            <StrengthMeter label="Opportunity Score" score={swotData.scores.opportunity} color="#3b82f6" />
            <StrengthMeter label="Weakness Risk" score={swotData.scores.weakness} color="#ef4444" />
            <StrengthMeter label="Threat Level" score={swotData.scores.threat} color="#f59e0b" />
          </div>

        </div>
      )}
    </div>
  );
}
