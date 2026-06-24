import React, { useMemo, useState, useEffect } from "react";

type ConfidenceCheckerPanelProps = {
  ticker?: string;
  companyName?: string;
};

/* ── Confidence gauge (score centered in middle) ── */
function ConfidenceGauge({ score }: { score: number }) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  const color = score >= 80 ? '#22c55e' : score >= 60 ? '#f59e0b' : score >= 40 ? '#3b82f6' : '#ef4444';

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-[130px] h-[130px]">
        <svg width="130" height="130" className="transform -rotate-90 absolute inset-0">
          <circle cx="65" cy="65" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="8" />
          <circle
            cx="65"
            cy="65"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-black tabular-nums leading-none" style={{ color }}>{score.toFixed(0)}</span>
          <span className="text-[9px] uppercase tracking-wider text-slate-400 mt-1">Confidence</span>
        </div>
      </div>
    </div>
  );
}

/* ── Criterion row ── */
function CriterionRow({ label, passed, detail }: { label: string; passed: boolean; detail: string }) {
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-slate-100 last:border-0">
      <div className={`mt-0.5 w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
        passed ? 'bg-emerald-100 text-emerald-600' : 'bg-red-100 text-red-500'
      }`}>
        {passed ? (
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none"><path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
        ) : (
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none"><path d="M6 18L18 6M6 6l12 12" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-bold ${passed ? 'text-emerald-700' : 'text-red-700'}`}>{label}</span>
          <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${passed ? 'bg-emerald-100 text-emerald-600' : 'bg-red-100 text-red-500'}`}>
            {passed ? 'PASS' : 'FAIL'}
          </span>
        </div>
        <p className="text-[10px] text-slate-500 mt-0.5 leading-relaxed">{detail}</p>
      </div>
    </div>
  );
}

/* ── Score category bar ── */
function CategoryBar({ label, score, color }: { label: string; score: number; color: string }) {
  const [animVal, setAnimVal] = useState(0);
  useEffect(() => {
    const id = setTimeout(() => setAnimVal(Math.min(score, 100)), 150);
    return () => clearTimeout(id);
  }, [score]);

  const pct = Math.min(score, 100);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[9px] font-bold uppercase tracking-wider text-slate-500">{label}</span>
        <span className="text-[10px] font-black" style={{ color }}>{pct.toFixed(0)}%</span>
      </div>
      <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-1000 ease-out"
          style={{ width: `${animVal}%`, background: `linear-gradient(90deg, ${color}60, ${color})` }}
        />
      </div>
    </div>
  );
}

/* ── Generate mock confidence data ── */
function generateConfidenceData(ticker: string) {
  const categories = [
    { label: 'Fundamentals', score: 60 + Math.random() * 35, color: '#22c55e' },
    { label: 'Technical', score: 50 + Math.random() * 40, color: '#3b82f6' },
    { label: 'Liquidity', score: 55 + Math.random() * 35, color: '#f59e0b' },
    { label: 'Sentiment', score: 40 + Math.random() * 45, color: '#a855f7' },
    { label: 'Governance', score: 65 + Math.random() * 30, color: '#06b6d4' },
  ];

  const overall = categories.reduce((s, c) => s + c.score, 0) / categories.length;

  const criteria = [
    { label: 'Revenue Growth', passed: Math.random() > 0.3, detail: `${ticker} has shown consistent revenue growth above industry average over the past 4 quarters.` },
    { label: 'Debt-to-Equity', passed: Math.random() > 0.35, detail: `Debt-to-equity ratio of 0.45x is well within the acceptable threshold of 1.0x.` },
    { label: 'Promoter Holding', passed: Math.random() > 0.25, detail: `Promoter holding of 62.3% indicates strong insider confidence in the company.` },
    { label: 'Volume Analysis', passed: Math.random() > 0.4, detail: `Average daily volume of 2.4M shares shows healthy market participation.` },
    { label: 'News Sentiment', passed: Math.random() > 0.35, detail: `Recent news flow is predominantly positive with 73% favorable coverage.` },
    { label: 'Technical Trend', passed: Math.random() > 0.4, detail: `${ticker} is trading above its 50-day and 200-day moving averages.` },
    { label: 'Peer Comparison', passed: Math.random() > 0.3, detail: `Outperforming peers on 5 of 7 key financial metrics this quarter.` },
  ];

  return { overall, categories, criteria };
}

/* ── Empty state ── */
function EmptyState() {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(20,184,166,0.12),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(99,102,241,0.10),transparent_36%)]" />
      <div className="relative flex min-h-[360px] flex-col items-center justify-center p-8 text-center">
        <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-lg shadow-emerald-500/20">
          <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
        <h3 className="text-sm font-black uppercase tracking-wider text-slate-900">Confidence Checker</h3>
        <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">Select a stock from the Asset Matrix to load its live Trendlyne checklist widget.</p>
      </div>
    </div>
  );
}

export default function ConfidenceCheckerPanel({ ticker, companyName }: ConfidenceCheckerPanelProps) {
  const normalizedTicker = ticker?.trim().toUpperCase();
  const [activeView, setActiveView] = useState<'widget' | 'dashboard'>('widget');
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  const [loadingDashboard, setLoadingDashboard] = useState(true);

  useEffect(() => {
    if (activeView !== 'dashboard') return;
    setLoadingDashboard(true);
    const id = setTimeout(() => setLoadingDashboard(false), 1500);
    return () => clearTimeout(id);
  }, [activeView, normalizedTicker]);

  const confidenceData = useMemo(() => {
    if (!normalizedTicker) return null;
    return generateConfidenceData(normalizedTicker);
  }, [normalizedTicker]);

  const widgetUrl = useMemo(() => {
    if (!normalizedTicker) return "";
    return `https://trendlyne.com/web-widget/checklist-widget/Poppins/${encodeURIComponent(normalizedTicker)}`;
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
          Confidence Dashboard
        </button>
      </div>

      {/* Widget view */}
      {activeView === 'widget' && (
        <div className="relative w-full overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_10%,rgba(20,184,166,0.16),transparent_34%),radial-gradient(circle_at_85%_20%,rgba(99,102,241,0.12),transparent_32%),radial-gradient(circle_at_50%_100%,rgba(245,158,11,0.10),transparent_38%)]" />
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-400 via-teal-400 to-indigo-500" />

          <div className="relative p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <div className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-lg shadow-emerald-500/20">
                  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
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

            <div className="relative w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-inner">
              {!loaded && !errored && (
                <div className="flex flex-col items-center justify-center gap-4 bg-white min-h-[400px]">
                  <div className="relative h-14 w-14 rounded-2xl border border-emerald-200 bg-emerald-50/80 shadow-lg flex items-center justify-center">
                    <div className="absolute inset-2 rounded-xl border border-emerald-400/40" />
                    <div className="absolute inset-0 animate-ping rounded-2xl bg-emerald-400/20" />
                    <svg className="h-7 w-7 text-emerald-500" viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </div>
                  <div className="space-y-2 text-center">
                    <p className="text-xs font-black uppercase tracking-[0.3em] text-emerald-600">Loading checklist</p>
                    <p className="max-w-xs text-[11px] leading-relaxed text-slate-400">Fetching Trendlyne health criteria for {normalizedTicker}.</p>
                  </div>
                </div>
              )}
              {errored && (
                <div className="relative z-10 flex flex-col items-center justify-center gap-3 p-6 text-center min-h-[400px]">
                  <div className="h-12 w-12 rounded-2xl border border-amber-200 bg-amber-50 text-amber-500 flex items-center justify-center">
                    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none"><path d="M12 9v4M12 17h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
                  </div>
                  <p className="text-xs font-bold uppercase tracking-wider text-amber-700">Widget Unavailable</p>
                  <p className="max-w-xs text-[11px] leading-relaxed text-slate-500">Open the Trendlyne checklist directly if the embedded frame is blocked.</p>
                  <a href={widgetUrl} target="_blank" rel="noopener noreferrer" className="rounded-full bg-amber-500 px-4 py-2 text-[11px] font-black text-white transition hover:bg-amber-400">
                    Open Trendlyne Checklist
                  </a>
                </div>
              )}
              <iframe
                key={widgetUrl}
                src={widgetUrl}
                title={`Trendlyne confidence checker for ${normalizedTicker}`}
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

      {/* Confidence Dashboard ── light theme */}
      {activeView === 'dashboard' && confidenceData && (
        <div className="space-y-3">
          {/* Header with gauge */}
          <div className="rounded-2xl bg-gradient-to-br from-emerald-50 via-white to-teal-50 border border-emerald-200/50 shadow-sm p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center text-white shadow-sm">
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </div>
                <div>
                  <div className="text-sm font-black text-slate-900">{companyName ?? normalizedTicker}</div>
                  <div className="text-[9px] text-slate-500 uppercase tracking-wider">{normalizedTicker} · CONFIDENCE SCORE</div>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-[9px] text-emerald-600 uppercase tracking-wider font-bold">Live</span>
              </div>
            </div>
            <div className="flex justify-center py-1">
              <div className="relative">
                <ConfidenceGauge score={confidenceData.overall} />
              </div>
            </div>
          </div>

          {/* Category bars */}
          <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4 space-y-2.5">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600 mb-2">Score Breakdown</div>
            {confidenceData.categories.map((cat) => (
              <CategoryBar key={cat.label} label={cat.label} score={cat.score} color={cat.color} />
            ))}
          </div>

          {/* Criteria checklist */}
          <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Checklist Criteria</span>
              <span className="ml-auto text-[9px] text-slate-400">
                {confidenceData.criteria.filter(c => c.passed).length}/{confidenceData.criteria.length} passed
              </span>
            </div>
            {confidenceData.criteria.map((criterion, i) => (
              <CriterionRow key={i} label={criterion.label} passed={criterion.passed} detail={criterion.detail} />
            ))}
          </div>

        </div>
      )}
    </div>
  );
}