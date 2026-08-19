"use client";

type CashSessionClosedBannerProps = {
  lastPrint?: string | null;
};

export default function CashSessionClosedBanner({ lastPrint }: CashSessionClosedBannerProps) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 shadow-md"
    >
      <span className="inline-flex items-center rounded bg-slate-100 px-2 py-1 text-[10px] font-black uppercase tracking-[0.16em] text-slate-900">
        NSE cash closed
      </span>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-200">
        Last session marks only · 5m hunt idle
      </span>
      {lastPrint ? (
        <span className="ml-auto text-[10px] tabular-nums text-slate-400">{lastPrint}</span>
      ) : null}
    </div>
  );
}
