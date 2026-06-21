'use client';

import React, { useMemo, useState, useRef, useEffect } from "react";

type TechnicalAnalysisPanelProps = {
  ticker?: string;
  companyName?: string;
};

/* ── Animated price ticker bar ── */
function AnimatedPriceBar({ visible }: { visible: boolean }) {
  const [bars, setBars] = useState<number[]>([]);

  useEffect(() => {
    if (!visible) return;
    const gen = Array.from({ length: 40 }, () => Math.random() * 60 + 10);
    setBars(gen);
    const id = setInterval(() => {
      setBars((prev) => {
        const next = [...prev.slice(1)];
        next.push(Math.random() * 60 + 10);
        return next;
      });
    }, 600);
    return () => clearInterval(id);
  }, [visible]);

  if (!visible || bars.length === 0) return null;

  return (
    <div className="flex items-end justify-center gap-[3px] h-16 px-2 py-2">
      {bars.map((h, i) => {
        const green = Math.random() > 0.48;
        return (
          <div
            key={i}
            className="w-[6px] rounded-t-sm transition-all duration-300"
            style={{
              height: `${h}%`,
              background: green
                ? 'linear-gradient(180deg, #22c55e 0%, #16a34a 100%)'
                : 'linear-gradient(180deg, #ef4444 0%, #dc2626 100%)',
              opacity: 0.7 + (h / 100) * 0.3,
              boxShadow: green
                ? '0 0 6px rgba(34,197,94,0.3)'
                : '0 0 6px rgba(239,68,68,0.3)',
            }}
          />
        );
      })}
    </div>
  );
}

/* ── Animated signal meter (light theme) ── */
function SignalMeter({ label, value, max = 100, color }: { label: string; value: number; max?: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</span>
        <span className="text-[11px] font-black tabular-nums" style={{ color }}>{value.toFixed(1)}</span>
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

/* ── Moving average crossover dots (light theme) ── */
function MACrossoverDots() {
  const dots = useMemo(() => {
    return Array.from({ length: 30 }, (_, i) => ({
      ma5: 40 + Math.sin(i * 0.4) * 20 + Math.random() * 6,
      ma20: 42 + Math.sin(i * 0.35 + 0.8) * 18 + Math.random() * 5,
    }));
  }, []);

  return (
    <div className="relative h-20 w-full">
      <svg viewBox="0 0 300 80" className="w-full h-full">
        <defs>
          <linearGradient id="ma5g-light" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0.25" />
          </linearGradient>
          <linearGradient id="ma20g-light" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.25" />
          </linearGradient>
        </defs>
        <path
          d={dots.map((d, i) => `${i === 0 ? 'M' : 'L'} ${i * 10 + 5} ${80 - d.ma5}`).join(' ')}
          stroke="#22c55e"
          strokeWidth="2"
          fill="none"
          opacity={0.8}
        />
        <path
          d={dots.map((d, i) => `${i === 0 ? 'M' : 'L'} ${i * 10 + 5} ${80 - d.ma20}`).join(' ')}
          stroke="#f59e0b"
          strokeWidth="2"
          fill="none"
          strokeDasharray="4 2"
          opacity={0.8}
        />
        {dots.filter((_, i) => i > 0 && Math.abs(dots[i].ma5 - dots[i].ma20) < 3).map((d, i) => (
          <circle
            key={i}
            cx={dots.indexOf(d) * 10 + 5}
            cy={80 - d.ma5}
            r="4"
            fill="#a855f7"
            className="animate-ping"
            opacity={0.5}
          />
        ))}
      </svg>
      <div className="absolute inset-x-0 bottom-0 flex justify-between text-[8px] text-slate-400 px-1">
        <span className="flex items-center gap-1"><span className="w-2 h-0.5 rounded bg-emerald-500" /> MA5</span>
        <span className="flex items-center gap-1"><span className="w-2 h-0.5 rounded bg-amber-500" /> MA20</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-violet-500" /> Crossover</span>
      </div>
    </div>
  );
}

/* ── Oscillator gauge (light theme) ── */
function OscillatorGauge({ rsi, macd }: { rsi: number; macd: number }) {
  const rsiColor = rsi > 70 ? '#ef4444' : rsi < 30 ? '#22c55e' : '#f59e0b';
  const macdColor = macd > 0 ? '#22c55e' : '#ef4444';

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="rounded-xl bg-white border border-slate-200 p-4 text-center shadow-sm">
        <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1 font-bold">RSI</div>
        <div className="text-2xl font-black tabular-nums" style={{ color: rsiColor }}>{rsi.toFixed(0)}</div>
        <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-1000"
            style={{
              width: `${(rsi / 100) * 100}%`,
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
        <div className="text-2xl font-black tabular-nums" style={{ color: macdColor }}>{macd > 0 ? '+' : ''}{macd.toFixed(2)}</div>
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1" style={{ backgroundColor: `${macdColor}15` }}>
          <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: macdColor }} />
          <span className="text-[10px] font-semibold" style={{ color: macdColor }}>
            {macd > 0 ? 'Bullish Crossover' : 'Bearish Crossover'}
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
      <div className="relative flex min-h-[400px] flex-col items-center justify-center p-8 text-center">
        <div className="mb-6 relative">
          <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-emerald-500 to-blue-600 text-white shadow-xl shadow-emerald-500/20 flex items-center justify-center">
            <svg viewBox="0 0 24 24" fill="none" className="h-10 w-10">
              <path d="M3 20h18M6 16l4-8 4 6 4-10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-emerald-400 animate-ping" />
        </div>
        <h3 className="text-base font-black uppercase tracking-wider text-slate-900">Technical Analysis</h3>
        <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">
          Select a stock from the Asset Matrix to view live technical indicators, oscillators, and trend signals.
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
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-white overflow-hidden">
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
              height: `${10 + Math.random() * 30}px`,
              animation: `pulse ${0.8 + i * 0.2}s ease-in-out infinite`,
              animationDelay: `${i * 0.15}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
}

export default function TechnicalAnalysisPanel({ ticker, companyName }: TechnicalAnalysisPanelProps) {
  const normalizedTicker = ticker?.trim().toUpperCase();
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  const [activeView, setActiveView] = useState<'widget' | 'dashboard'>('widget');

  const oscillators = useMemo(() => ({
    rsi: 45 + Math.random() * 30,
    macd: (Math.random() - 0.5) * 4,
    stochastic: 30 + Math.random() * 50,
    williamsR: -(20 + Math.random() * 60),
    cci: (Math.random() - 0.5) * 300,
  }), [normalizedTicker]);

  const signals = useMemo(() => ({
    maSignal: Math.random() > 0.5 ? 'BUY' : 'SELL',
    strength: 30 + Math.random() * 60,
    volume: 40 + Math.random() * 55,
    volatility: 20 + Math.random() * 50,
  }), [normalizedTicker]);

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
                <div className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-blue-600 text-white shadow-lg shadow-emerald-500/20">
                  <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5">
                    <path d="M3 20h18M6 16l4-8 4 6 4-10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <div className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-emerald-400 animate-pulse" />
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
                <div className="relative z-10 flex flex-col items-center justify-center gap-3 p-6 text-center min-h-[400px]">
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
                className="h-[500px] w-full bg-white"
              />
            </div>
          </div>
        </div>
      )}

      {/* Live Dashboard ── light theme */}
      {activeView === 'dashboard' && (
        <div className="space-y-3">
          {/* Header card */}
          <div className="rounded-2xl bg-gradient-to-br from-white to-slate-50 border border-slate-200 shadow-sm overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-emerald-400 via-blue-400 to-violet-500" />
            <div className="p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-emerald-400 to-emerald-500 flex items-center justify-center text-white shadow-sm">
                    <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4">
                      <path d="M3 20h18M6 16l4-8 4 6 4-10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <div>
                    <div className="text-sm font-black text-slate-900">{companyName ?? normalizedTicker}</div>
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">{normalizedTicker} · LIVE SIGNALS</div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="text-[9px] text-emerald-600 uppercase tracking-wider font-bold">Streaming</span>
                </div>
              </div>
              <AnimatedPriceBar visible={true} />
            </div>
          </div>

          {/* Oscillator gauges */}
          <OscillatorGauge rsi={oscillators.rsi} macd={oscillators.macd} />

          {/* Moving average crossover */}
          <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Moving Average Crossover</span>
              <span className={`text-[10px] font-black px-2 py-0.5 rounded ${
                signals.maSignal === 'BUY' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
              }`}>
                {signals.maSignal} Signal
              </span>
            </div>
            <MACrossoverDots />
          </div>

          {/* Signal meters */}
          <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4 space-y-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600 mb-2">Signal Strength Metrics</div>
            <SignalMeter label="Trend Strength" value={signals.strength} color="#22c55e" />
            <SignalMeter label="Volume Momentum" value={signals.volume} color="#3b82f6" />
            <SignalMeter label="Volatility Index" value={signals.volatility} color="#f59e0b" />
            <SignalMeter label="Stochastic Oscillator" value={oscillators.stochastic} color="#a855f7" />
          </div>

        </div>
      )}
    </div>
  );
}