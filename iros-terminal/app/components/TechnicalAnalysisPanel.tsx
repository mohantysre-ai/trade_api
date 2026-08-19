'use client';

import React, { useMemo, useState } from "react";
import { buildTechnicalSignals, type IntradayMetrics } from "@/lib/drawer-research";
import type { TrendlyneCardSummary } from "@/lib/intelligence-summary";
import { isNseCashSessionNow } from "@/lib/market-api";
import MarketSymbolBadge from "./MarketSymbolBadge";
import CashSessionClosedBanner from "./CashSessionClosedBanner";

type TechnicalAnalysisPanelProps = {
  ticker?: string;
  companyName?: string;
  intraday?: IntradayMetrics | null;
  trendlyne?: TrendlyneCardSummary | null;
  researchLoading?: boolean;
};

/* ── Animated signal meter (light theme) ── */
function SignalMeter({ label, value, max = 100, color }: { label: string; value: number | null; max?: number; color: string }) {
  const pct = value == null ? 0 : Math.min((value / max) * 100, 100);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</span>
        <span className="text-[11px] font-black tabular-nums" style={{ color }}>{value == null ? "—" : value.toFixed(1)}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-200 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-1000 ease-out"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${color}40, ${color})`,
          }}
        />
      </div>
    </div>
  );
}

/* ── Oscillator gauge (light theme) ── */
function OscillatorGauge({ rsi, macd }: { rsi: number | null; macd: number | null }) {
  if (rsi == null && macd == null) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-center text-[11px] text-slate-500">
        Intraday RSI / trend metrics not available in snapshot or Trendlyne.
      </div>
    );
  }

  const rsiVal = rsi ?? 50;
  const macdVal = macd ?? 0;
  const rsiColor = rsiVal > 70 ? '#ef4444' : rsiVal < 30 ? '#22c55e' : '#f59e0b';
  const macdColor = macdVal > 0 ? '#22c55e' : '#ef4444';

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="rounded-xl bg-white border border-slate-200 p-4 text-center shadow-sm">
        <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1 font-bold">RSI</div>
        <div className="text-2xl font-black tabular-nums" style={{ color: rsiColor }}>{rsi != null ? rsiVal.toFixed(0) : "—"}</div>
        <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-1000"
            style={{
              width: `${rsi != null ? (rsiVal / 100) * 100 : 0}%`,
              background: `linear-gradient(90deg, #22c55e, #f59e0b, #ef4444)`,
            }}
          />
        </div>
        <div className="flex justify-between text-[8px] text-slate-400 mt-1">
          <span>Oversold</span>
          <span>Overbought</span>
        </div>
      </div>
      <div className="rounded-xl bg-white border border-slate-200 p-4 text-center shadow-sm">
        <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1 font-bold">MACD</div>
        <div className="text-2xl font-black tabular-nums" style={{ color: macdColor }}>{macd != null ? `${macdVal > 0 ? '+' : ''}${macdVal.toFixed(2)}` : "—"}</div>
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1" style={{ backgroundColor: `${macdColor}15` }}>
          <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: macdColor }} />
          <span className="text-[10px] font-semibold" style={{ color: macdColor }}>
            {macd != null ? (macdVal > 0 ? 'Bullish Crossover' : 'Bearish Crossover') : '—'}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Empty state ── */
function EmptyState() {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(34,197,94,0.08),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(59,130,246,0.06),transparent_36%)]" />
      <div className="relative flex min-h-[240px] sm:min-h-[320px] md:min-h-[400px] flex-col items-center justify-center p-8 text-center">
        <div className="mb-6 relative">
          <div className="h-20 w-20 rounded-3xl tech-analysis-icon flex items-center justify-center shadow-xl">
            <svg viewBox="0 0 24 24" fill="none" className="h-10 w-10">
              <path d="M3 20h18M6 16l4-8 4 6 4-10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="absolute -top-1 -right-1 h-5 w-5 rounded-full tech-analysis-pulse animate-ping" />
        </div>
        <h3 className="text-base font-black uppercase tracking-wider text-slate-900">Technical Analysis</h3>
        <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">
          Select a stock from the Swing Portfolio to view live technical indicators, oscillators, and trend signals.
        </p>
        <div className="mt-6 flex gap-3">
          <div className="h-2 w-12 rounded-full bg-emerald-200 animate-pulse" />
          <div className="h-2 w-8 rounded-full bg-blue-200 animate-pulse" style={{ animationDelay: '0.2s' }} />
          <div className="h-2 w-10 rounded-full bg-amber-200 animate-pulse" style={{ animationDelay: '0.4s' }} />
        </div>
      </div>
    </div>
  );
}

/* ── Light theme loading skeleton ── */
function LoadingSkeleton() {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-white overflow-hidden min-h-[240px] sm:min-h-[320px] md:min-h-[400px]">
      <div className="relative">
        <div className="h-16 w-16 rounded-2xl border border-emerald-200 bg-emerald-50/80 shadow-lg flex items-center justify-center">
          <svg className="h-8 w-8 text-emerald-500 animate-spin" viewBox="0 0 24 24" fill="none">
            <path d="M3 20h18M6 16l4-8 4 6 4-10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>
      <div className="space-y-2 text-center">
        <p className="text-sm font-black uppercase tracking-[0.3em] text-emerald-600">Analyzing Technicals</p>
        <p className="max-w-xs text-[11px] leading-relaxed text-slate-400">Computing moving averages, RSI, MACD & trend indicators.</p>
      </div>
      <div className="flex gap-1.5 mt-4">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="w-2 rounded-full bg-emerald-300/60"
            style={{
              height: `${10 + i * 6}px`,
              animation: `pulse ${0.8 + i * 0.2}s ease-in-out infinite`,
              animationDelay: `${i * 0.15}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
}

export default function TechnicalAnalysisPanel({ ticker, companyName, intraday, trendlyne, researchLoading = false }: TechnicalAnalysisPanelProps) {
  const normalizedTicker = ticker?.trim().toUpperCase();
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  const [activeView, setActiveView] = useState<'widget' | 'dashboard'>('dashboard');

  const signals = useMemo(() => buildTechnicalSignals(intraday, trendlyne), [intraday, trendlyne]);
  const sessionOpen = isNseCashSessionNow();

  const widgetUrl = useMemo(() => {
    if (!normalizedTicker) return "";
    return `https://trendlyne.com/web-widget/technical-widget/Poppins/${encodeURIComponent(normalizedTicker)}`;
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
          onClick={() => setActiveView('dashboard')}
          className={`flex-1 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all ${
            activeView === 'dashboard' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          Live Dashboard
        </button>
      </div>

      {/* Widget view */}
      {activeView === 'widget' && (
        <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_10%,rgba(34,197,94,0.12),transparent_34%),radial-gradient(circle_at_85%_20%,rgba(59,130,246,0.08),transparent_32%)]" />
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-400 via-blue-400 to-violet-500" />

          <div className="relative p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <div className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl tech-analysis-icon">
                  <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5">
                    <path d="M3 20h18M6 16l4-8 4 6 4-10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <div className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 tech-analysis-pulse animate-pulse" />
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
                className="group flex flex-shrink-0 items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50/80 px-2.5 py-1 text-[9px] font-black uppercase tracking-wider text-emerald-700 transition hover:border-emerald-300 hover:bg-emerald-100"
              >
                Open
                <svg className="h-3 w-3 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" viewBox="0 0 24 24" fill="none">
                  <path d="M14 4h6v6M20 4l-9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M20 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </a>
            </div>

            <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-inner">
              {!loaded && !errored && <LoadingSkeleton />}
              {errored && (
                <div className="relative z-10 flex flex-col items-center justify-center gap-3 p-6 text-center min-h-[240px] sm:min-h-[320px] md:min-h-[400px]">
                  <div className="h-12 w-12 rounded-2xl border border-amber-200 bg-amber-50 text-amber-500 flex items-center justify-center">
                    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none">
                      <path d="M12 9v4M12 17h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  </div>
                  <p className="text-xs font-bold uppercase tracking-wider text-amber-700">Widget Unavailable</p>
                  <p className="max-w-xs text-[11px] leading-relaxed text-slate-500">Open the Trendlyne technical widget directly.</p>
                  <a href={widgetUrl} target="_blank" rel="noopener noreferrer" className="rounded-full bg-amber-500 px-4 py-2 text-[11px] font-black text-white transition hover:bg-amber-400">
                    Open Trendlyne Technicals
                  </a>
                </div>
              )}
              <iframe
                key={widgetUrl}
                src={widgetUrl}
                title={`Trendlyne technical analysis for ${normalizedTicker}`}
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

      {/* Live Dashboard ── light theme */}
      {activeView === 'dashboard' && (
        <div className={`space-y-3 ${sessionOpen ? "" : "grayscale-[0.45]"}`}>
          {!sessionOpen && (
            <CashSessionClosedBanner lastPrint={trendlyne?.lastModified} />
          )}
          {!signals.hasData && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[10px] font-semibold text-amber-900">
              {researchLoading ? `Loading Trendlyne technicals for ${normalizedTicker}…` : `Partial desk view — live 5m metrics and Trendlyne technicals are unavailable for ${normalizedTicker}. Missing values remain unscored.`}
            </div>
          )}
          {/* Header card */}
          <div className="rounded-2xl bg-gradient-to-br from-white to-slate-50 border border-slate-200 shadow-sm overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-emerald-400 via-blue-400 to-violet-500" />
            <div className="p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <MarketSymbolBadge symbol={normalizedTicker} size="md" />
                  <div>
                    <div className="text-sm font-black text-slate-900">{companyName ?? normalizedTicker}</div>
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">{normalizedTicker} · {sessionOpen ? "LIVE SIGNALS" : "SESSION CLOSED"}{signals.metricSource === "trendlyne" ? " · TRENDLYNE" : signals.metricSource === "mixed" ? " · 5M + TRENDLYNE" : ""}</div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${!sessionOpen ? "bg-slate-500" : signals.hasData ? "bg-emerald-500 animate-pulse" : "bg-amber-500"}`} />
                  <span className={`text-[9px] uppercase tracking-wider font-bold ${!sessionOpen ? "text-slate-600" : signals.hasData ? "text-emerald-600" : "text-amber-700"}`}>{!sessionOpen ? "Closed" : signals.hasData ? "Streaming" : "Partial"}</span>
                </div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-[10px] text-slate-600">
                Research bias: {trendlyne?.technicalBias ?? "—"} · MA buy/sell: {trendlyne?.maBullish ?? "—"}/{trendlyne?.maTotal != null && trendlyne.maBullish != null ? trendlyne.maTotal - trendlyne.maBullish : "—"} · Oscillator buy/sell: {trendlyne?.oscillatorBullish ?? "—"}/{trendlyne?.oscillatorTotal != null && trendlyne.oscillatorBullish != null ? trendlyne.oscillatorTotal - trendlyne.oscillatorBullish : "—"}
              </div>
            </div>
          </div>

          {/* Oscillator gauges */}
          <OscillatorGauge rsi={signals.rsi} macd={signals.macd} />

          {/* Moving average crossover */}
          <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Moving Average Crossover</span>
              <span className={`text-[10px] font-black px-2 py-0.5 rounded ${
                signals.maSignal === 'BUY' ? 'bg-emerald-100 text-emerald-700' : signals.maSignal === 'SELL' ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-700'
              }`}>
                {signals.maSignal} Signal
              </span>
            </div>
            <div className="text-[10px] text-slate-500 mb-2">
              {signals.vwapLabel}: {signals.aboveVwap == null ? "—" : signals.aboveVwap ? "above" : "below"} · {signals.emaLabel}: {signals.aboveEma9 == null ? "—" : signals.aboveEma9 ? "above" : "below"}
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-[10px] text-slate-500">
              {signals.metricSource === "trendlyne" || signals.metricSource === "mixed"
                ? "Trendlyne widget technicals fill RSI/MACD/MA when 5m candle anchors are missing. No synthetic price path is generated."
                : "Only sourced VWAP/EMA9 relationships are shown; no synthetic price path is generated."}
            </div>
          </div>

          {/* Signal meters */}
          <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4 space-y-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600 mb-2">Signal Strength Metrics</div>
            <SignalMeter label="Trend Strength (RSI)" value={signals.strength} color="#22c55e" />
            <SignalMeter label="Volume Momentum" value={signals.volume} color="#3b82f6" />
            <SignalMeter label="Volatility Index (ATR)" value={signals.volatility} color="#f59e0b" />
            <SignalMeter label="Stochastic" value={signals.stochastic} color="#a855f7" />
          </div>

        </div>
      )}
    </div>
  );
}
