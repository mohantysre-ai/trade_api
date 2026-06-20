import React, { useMemo, useState } from "react";

type ConfidenceCheckerPanelProps = {
  ticker?: string;
  companyName?: string;
};

function CheckIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ExternalIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14 4h6v6M20 4l-9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M20 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function WidgetSkeleton() {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
      <div className="relative h-14 w-14 rounded-2xl border border-white/10 bg-white/5 shadow-2xl">
        <div className="absolute inset-2 rounded-xl border border-emerald-400/40" />
        <div className="absolute inset-0 animate-ping rounded-2xl bg-emerald-400/20" />
      </div>
      <div className="space-y-2 text-center">
        <p className="text-xs font-black uppercase tracking-[0.3em] text-emerald-300">Loading checklist</p>
        <p className="max-w-xs text-[11px] leading-relaxed text-slate-300">Fetching Trendlyne health criteria for the selected ticker.</p>
      </div>
    </div>
  );
}

export default function ConfidenceCheckerPanel({ ticker, companyName }: ConfidenceCheckerPanelProps) {
  const normalizedTicker = ticker?.trim().toUpperCase();
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);

  const widgetUrl = useMemo(() => {
    if (!normalizedTicker) return "";
    return `https://trendlyne.com/web-widget/checklist-widget/Poppins/${encodeURIComponent(normalizedTicker)}`;
  }, [normalizedTicker]);

  if (!normalizedTicker) {
    return (
      <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(20,184,166,0.12),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(99,102,241,0.10),transparent_36%)]" />
        <div className="relative flex min-h-[360px] flex-col items-center justify-center p-8 text-center">
          <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-lg shadow-emerald-500/20">
            <CheckIcon className="h-8 w-8" />
          </div>
          <h3 className="text-sm font-black uppercase tracking-wider text-slate-900">Confidence Checker</h3>
          <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">Select a stock from the Asset Matrix to load its live Trendlyne checklist widget.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_10%,rgba(20,184,166,0.16),transparent_34%),radial-gradient(circle_at_85%_20%,rgba(99,102,241,0.12),transparent_32%),radial-gradient(circle_at_50%_100%,rgba(245,158,11,0.10),transparent_38%)]" />
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-400 via-teal-400 to-indigo-500" />

      <div className="relative p-5">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="relative flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-lg shadow-emerald-500/20">
              <CheckIcon className="h-6 w-6" />
              <div className="absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-white bg-emerald-400 animate-pulse" />
            </div>
            <div className="min-w-0">
              <div className="mt-1 flex items-baseline gap-2 min-w-0">
                <span className="truncate text-base font-black text-slate-950">{companyName ?? normalizedTicker}</span>
                <span className="truncate text-[10px] font-bold uppercase tracking-wider text-slate-400">{normalizedTicker}</span>
              </div>
            </div>
          </div>
          <a
            href={widgetUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex flex-shrink-0 items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50/80 px-3 py-1.5 text-[10px] font-black uppercase tracking-wider text-emerald-700 transition hover:border-emerald-300 hover:bg-emerald-100 hover:text-emerald-800"
          >
            Open
            <ExternalIcon className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </a>
        </div>


        <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-slate-950 shadow-2xl">
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-emerald-300 to-transparent opacity-70" />
          <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-indigo-300 to-transparent opacity-70" />
          {!loaded && !errored && <WidgetSkeleton />}
          {errored && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-slate-950/90 p-6 text-center">
              <div className="h-12 w-12 rounded-2xl border border-amber-300/30 bg-amber-400/10 text-amber-300">
                <ExternalIcon className="m-auto h-6 w-6" />
              </div>
              <p className="text-xs font-bold uppercase tracking-wider text-amber-200">Widget blocked or unavailable</p>
              <p className="max-w-xs text-[11px] leading-relaxed text-slate-300">Open the Trendlyne checklist directly if the embedded frame is blocked.</p>
              <a href={widgetUrl} target="_blank" rel="noopener noreferrer" className="rounded-full bg-amber-300 px-4 py-2 text-[11px] font-black text-slate-950 transition hover:bg-amber-200">
                Open Trendlyne checklist
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
            className="h-[560px] w-full bg-white"
          />
        </div>
      </div>
    </div>
  );
}