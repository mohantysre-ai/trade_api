"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export default function SigqQvtPanel({ ticker }: { ticker: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const normalizedTicker = ticker.toUpperCase().trim();
  const widgetUrl = useMemo(
    () => `https://trendlyne.com/web-widget/qvt-widget/Poppins/${encodeURIComponent(normalizedTicker)}/`,
    [normalizedTicker],
  );

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !normalizedTicker) return;
    setFailed(false);
    host.replaceChildren();
    const quote = document.createElement("blockquote");
    quote.className = "trendlyne-widgets";
    quote.dataset.getUrl = widgetUrl;
    quote.dataset.theme = "dark";
    quote.dataset.posCol = "00A25B";
    quote.dataset.primaryCol = "006AFF";
    quote.dataset.negCol = "EB3B00";
    quote.dataset.neuCol = "F7941E";
    host.appendChild(quote);
    const script = document.createElement("script");
    script.async = true;
    script.src = "https://cdn-static.trendlyne.com/static/js/webwidgets/tl-widgets.js";
    script.charset = "utf-8";
    script.onerror = () => setFailed(true);
    host.appendChild(script);
    return () => host.replaceChildren();
  }, [normalizedTicker, widgetUrl]);

  if (!normalizedTicker) return <div className="py-16 text-center text-xs text-slate-400">Select a stock to view SIGQ QVT.</div>;

  return (
    <section className="space-y-3">
      <div className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3">
        <h3 className="text-xs font-black uppercase tracking-wider text-slate-100">SIGQ QVT</h3>
        <p className="mt-1 text-[11px] text-slate-400">Quality, valuation and technical research for {normalizedTicker}.</p>
      </div>
      {failed ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-center">
          <p className="text-xs font-bold text-amber-800">SIGQ QVT is temporarily unavailable.</p>
          <a href={widgetUrl} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex rounded-full bg-amber-500 px-4 py-2 text-[11px] font-black text-white">Open SIGQ QVT</a>
        </div>
      ) : (
        <div ref={hostRef} className="min-h-[420px] overflow-hidden rounded-xl border border-slate-700 bg-slate-950 p-2" />
      )}
    </section>
  );
}
