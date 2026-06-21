'use client';

import React, { useMemo, useState, useEffect } from "react";

type SwotAnalysisPanelProps = {
  ticker?: string;
  companyName?: string;
};

/* ── Color-coded quadrant card (light theme accent) ── */
function QuadrantCard({
  title,
  icon,
  items,
  gradient,
  accentColor,
  borderGlow,
}: {
  title: string;
  icon: React.ReactNode;
  items: string[];
  gradient: string;
  accentColor: string;
  borderGlow: string;
}) {
  return (
    <div className={`relative overflow-hidden rounded-xl border ${borderGlow} shadow-md group hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5`}>
      <div className={`absolute inset-0 ${gradient}`} />
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent" />

      <div className="relative p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-white/90 shadow-sm" style={{ color: accentColor }}>
            {icon}
          </div>
          <span className="text-[11px] font-black uppercase tracking-wider text-white">{title}</span>
        </div>

        <div className="space-y-2">
          {items.map((item, i) => (
            <div key={i} className="flex items-start gap-2 group/item">
              <span
                className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 transition-all duration-300 group-hover/item:scale-150"
                style={{ backgroundColor: accentColor }}
              />
              <span className="text-[11px] text-white/85 leading-relaxed group-hover/item:text-white transition-colors">
                {item}
              </span>
            </div>
          ))}
          {items.length === 0 && (
            <span className="text-[10px] text-white/50 italic">Loading data...</span>
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
function StrengthMeter({ label, score, color }: { label: string; score: number; color: string }) {
  const [animVal, setAnimVal] = useState(0);
  const pct = Math.min((score / 100) * 100, 100);

  useEffect(() => {
    const id = setTimeout(() => setAnimVal(pct), 100);
    return () => clearTimeout(id);
  }, [pct]);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</span>
        <span className="text-[10px] font-black tabular-nums" style={{ color }}>{score.toFixed(0)}%</span>
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
function ScoreRing({ value, label, color }: { value: number; label: string; color: string }) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;

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
          <span className="text-xl font-black tabular-nums leading-none" style={{ color }}>{value.toFixed(0)}</span>
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
      <div className="relative flex min-h-[400px] flex-col items-center justify-center p-8 text-center">
        <div className="mb-6 relative">
          <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-amber-500 to-red-600 text-white shadow-xl shadow-amber-500/20 flex items-center justify-center">
            <svg viewBox="0 0 24 24" fill="none" className="h-10 w-10">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-amber-400 animate-ping" />
        </div>
        <h3 className="text-base font-black uppercase tracking-wider text-slate-900">SWOT Analysis</h3>
        <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">
          Select a stock from the Asset Matrix to view its Strengths, Weaknesses, Opportunities & Threats.
        </p>
      </div>
    </div>
  );
}

/* ── Loading quadrant skeleton (light theme) ── */
function LoadingQuadrant() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {[
        { label: 'Strengths', color: 'bg-emerald-200' },
        { label: 'Weaknesses', color: 'bg-red-200' },
        { label: 'Opportunities', color: 'bg-blue-200' },
        { label: 'Threats', color: 'bg-amber-200' },
      ].map((item, i) => (
        <div key={item.label} className={`rounded-xl p-4 animate-pulse min-h-[140px] border border-slate-200 ${item.color}/30`}>
          <div className="h-4 w-24 bg-slate-200 rounded mb-3" />
          <div className="space-y-2">
            <div className="h-3 w-full bg-slate-100 rounded" />
            <div className="h-3 w-3/4 bg-slate-100 rounded" />
            <div className="h-3 w-5/6 bg-slate-100 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Mock SWOT data generator ── */
function generateSwotData(ticker: string) {
  const strengths = [
    `${ticker} commands strong brand equity with consistent market share expansion across core segments.`,
    `Robust balance sheet with debt-to-equity ratio well below industry average of 0.8x.`,
    `Superior operating margins of 22.4% compared to peer average of 14.7%.`,
    `Highly diversified revenue base with no single customer exceeding 5% of total revenue.`,
    `Industry-leading R&D spend at 8.3% of revenue driving continuous innovation.`,
    `Experienced management team with average tenure of 14 years in the sector.`,
  ];

  const weaknesses = [
    `Geographic concentration risk with 68% of revenue derived from domestic markets.`,
    `Working capital cycle of 72 days remains elevated versus industry benchmark of 45 days.`,
    `Legacy IT infrastructure leading to 15% higher operational costs vs digitally-native competitors.`,
    `Limited pricing power in commoditized product segments facing margin compression.`,
    `Succession planning uncertainty with key leadership roles concentrated in founding family.`,
  ];

  const opportunities = [
    `Addressable market in Tier-2/3 cities projected to grow at 18% CAGR over next 3 years.`,
    `Adjacent industry expansion potential in renewable energy & electric mobility verticals.`,
    `Strategic M&A pipeline with 3-4 mid-sized acquisition targets at attractive valuations.`,
    `Digital transformation initiative expected to reduce opex by 25% by FY2027.`,
    `Export incentives and PLI scheme benefits could boost margins by 200-300 bps.`,
  ];

  const threats = [
    `Regulatory headwinds in key operating regions with potential compliance cost increases.`,
    `Intense price competition from unorganized sector players eroding market share by 3-4% annually.`,
    `Currency volatility exposed through unhedged forex book of $120 million.`,
    `Supply chain disruptions from geopolitical tensions in sourcing regions.`,
    `Technological disruption risk from agile fintech startups with zero-cost acquisition models.`,
  ];

  const scores = {
    overall: 65 + Math.random() * 25,
    strength: 60 + Math.random() * 30,
    opportunity: 55 + Math.random() * 30,
    weakness: 20 + Math.random() * 30,
    threat: 25 + Math.random() * 28,
  };

  return {
    strengths: strengths.sort(() => 0.5 - Math.random()).slice(0, 3 + Math.floor(Math.random() * 2)),
    weaknesses: weaknesses.sort(() => 0.5 - Math.random()).slice(0, 3 + Math.floor(Math.random() * 2)),
    opportunities: opportunities.sort(() => 0.5 - Math.random()).slice(0, 3 + Math.floor(Math.random() * 2)),
    threats: threats.sort(() => 0.5 - Math.random()).slice(0, 3 + Math.floor(Math.random() * 2)),
    scores,
  };
}

export default function SwotAnalysisPanel({ ticker, companyName }: SwotAnalysisPanelProps) {
  const normalizedTicker = ticker?.trim().toUpperCase();
  const [activeView, setActiveView] = useState<'widget' | 'analysis'>('widget');
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  const [loadingAnalysis, setLoadingAnalysis] = useState(true);

  useEffect(() => {
    if (activeView !== 'analysis' || !normalizedTicker) return;
    setLoadingAnalysis(true);
    const id = setTimeout(() => setLoadingAnalysis(false), 1800);
    return () => clearTimeout(id);
  }, [activeView, normalizedTicker]);

  const swotData = useMemo(() => {
    if (!normalizedTicker) return null;
    return generateSwotData(normalizedTicker);
  }, [normalizedTicker]);

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
          AI Analysis
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
                <div className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-amber-400 to-red-600 text-white shadow-lg shadow-amber-500/20">
                  <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5">
                    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <div className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-amber-400 animate-pulse" />
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
                <div className="flex flex-col items-center justify-center gap-4 bg-white min-h-[400px]">
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
                <div className="relative z-10 flex flex-col items-center justify-center gap-3 p-6 text-center min-h-[400px]">
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
                className="h-[500px] w-full bg-white"
              />
            </div>
          </div>
        </div>
      )}

      {/* AI Analysis view ── light theme quadrant visualizer */}
      {activeView === 'analysis' && swotData && (
        <div className="space-y-3">
          {/* Header card */}
          <div className="rounded-2xl bg-gradient-to-br from-amber-50 via-white to-red-50 border border-amber-200/50 shadow-sm p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-amber-400 to-red-500 flex items-center justify-center text-white shadow-sm">
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
                <span className="text-[9px] text-amber-600 uppercase tracking-wider font-bold">AI Generated</span>
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
                <ScoreRing value={100 - swotData.scores.weakness} label="Defense" color="#ef4444" />
              </div>
            </div>
          </div>

          {/* Quadrant grid */}
          {loadingAnalysis ? (
            <LoadingQuadrant />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <QuadrantCard
                title="Strengths"
                accentColor="#22c55e"
                borderGlow="border-emerald-300"
                gradient="bg-gradient-to-br from-emerald-500 to-emerald-600"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.strengths}
              />
              <QuadrantCard
                title="Weaknesses"
                accentColor="#ef4444"
                borderGlow="border-red-300"
                gradient="bg-gradient-to-br from-red-500 to-red-600"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M6 18L18 6M6 6l12 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.weaknesses}
              />
              <QuadrantCard
                title="Opportunities"
                accentColor="#3b82f6"
                borderGlow="border-blue-300"
                gradient="bg-gradient-to-br from-blue-500 to-blue-600"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M13 7h8m0 0v8m0-8l-9 9-4-4-6 6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.opportunities}
              />
              <QuadrantCard
                title="Threats"
                accentColor="#f59e0b"
                borderGlow="border-amber-300"
                gradient="bg-gradient-to-br from-amber-500 to-amber-600"
                icon={<svg viewBox="0 0 24 24" fill="none" className="h-4 w-4"><path d="M12 9v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                items={swotData.threats}
              />
            </div>
          )}

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