import React, { useCallback, useEffect, useMemo, useState } from "react";
import MarketSymbolBadge from "./MarketSymbolBadge";
import type { AITickerNewsReport } from "@/lib/market-api";
import { fetchTickerNewsReport } from "@/lib/market-api";

type Tone = "Bullish" | "Bearish" | "Neutral";
type ToneFilter = "All" | Tone;

const CATEGORIES: Array<{ key: keyof AITickerNewsReport; label: string; short: string; icon: string }> = [
  { key: "insider_activity", label: "Insider Activity", short: "Insider", icon: "◎" },
  { key: "institutional_activity", label: "Institutional Activity", short: "Flows", icon: "◈" },
  { key: "order_book_block_deals", label: "Order Book / Block Deals", short: "Blocks", icon: "▦" },
  { key: "future_expansion_capex", label: "Future Expansion / Capex", short: "Capex", icon: "↗" },
  { key: "auditor_changes", label: "Auditor Changes", short: "Audit", icon: "◇" },
  { key: "dividend_news", label: "Dividend / Buyback / Bonus", short: "Capital", icon: "◆" },
  { key: "new_orders_contracts", label: "New Orders / Contracts", short: "Orders", icon: "⌁" },
  { key: "earnings_results", label: "Earnings / Results", short: "Results", icon: "▥" },
  { key: "management_changes", label: "Management Changes", short: "Mgmt", icon: "◉" },
  { key: "regulatory_filings", label: "Regulatory Filings", short: "Filings", icon: "≋" },
];

const EMPTY_INTEL = new Set(["none", "n/a", "na", "nil", "not available", "no data", "no recent news found", "—", "-", "–"]);
const POSITIVE = ["wins", "win ", "order", "contract", "growth", "profit", "surge", "raises", "upgrade", "buyback", "dividend", "expansion", "record", "strong", "beats", "approval"];
const NEGATIVE = ["loss", "falls", "decline", "cuts", "downgrade", "probe", "fraud", "penalty", "default", "weak", "misses", "warning", "resigns", "slump", "delay"];

function isBlankIntel(value?: string): boolean {
  const normalized = value?.trim().toLowerCase().replace(/[.!]+$/g, "") ?? "";
  return !normalized || EMPTY_INTEL.has(normalized);
}

function toneFor(text: string): Tone {
  const value = text.toLowerCase();
  const positive = POSITIVE.reduce((score, word) => score + (value.includes(word) ? 1 : 0), 0);
  const negative = NEGATIVE.reduce((score, word) => score + (value.includes(word) ? 1 : 0), 0);
  return positive > negative ? "Bullish" : negative > positive ? "Bearish" : "Neutral";
}

function toneClasses(tone: Tone) {
  if (tone === "Bullish") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  if (tone === "Bearish") return "border-rose-400/30 bg-rose-400/10 text-rose-300";
  return "border-slate-500/30 bg-slate-500/10 text-slate-300";
}

function relativeTime(value?: string) {
  if (!value) return "time n/a";
  const stamp = new Date(value).getTime();
  if (!Number.isFinite(stamp)) return "time n/a";
  const minutes = Math.max(0, Math.round((Date.now() - stamp) / 60_000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

function sourceMark(source: string) {
  return source.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "N";
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3" aria-label="Loading live news intelligence">
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className="relative overflow-hidden rounded-xl border border-white/5 bg-white/[0.025] p-3">
          <div className="absolute inset-0 -translate-x-full animate-[pulse_1.8s_ease-in-out_infinite] bg-gradient-to-r from-transparent via-cyan-300/[0.035] to-transparent" />
          <div className="mb-2 h-2 w-20 rounded bg-slate-700/70" />
          <div className="mb-1.5 h-3 w-11/12 rounded bg-slate-700/50" />
          <div className="h-3 w-8/12 rounded bg-slate-800" />
        </div>
      ))}
    </div>
  );
}

function RadarPulse({ healthy }: { healthy: boolean }) {
  return (
    <span className="relative flex h-3 w-3 items-center justify-center" aria-hidden="true">
      {healthy && <span className="absolute h-3 w-3 animate-ping rounded-full bg-emerald-400/35 motion-reduce:animate-none" />}
      <span className={`relative h-1.5 w-1.5 rounded-full ${healthy ? "bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,.8)]" : "bg-amber-400"}`} />
    </span>
  );
}

export default function AITickerNewsPanel({
  ticker,
  companyName,
  onClose,
  initialReport,
}: {
  ticker: string;
  companyName?: string;
  onClose?: () => void;
  initialReport?: AITickerNewsReport | null;
}) {
  const [report, setReport] = useState<AITickerNewsReport | null>(initialReport ?? null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toneFilter, setToneFilter] = useState<ToneFilter>("All");
  const [sourceFilter, setSourceFilter] = useState("All");
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    setReport(initialReport ?? null);
    setToneFilter("All");
    setSourceFilter("All");
  }, [initialReport, ticker]);

  useEffect(() => {
    if (!ticker || initialReport) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTickerNewsReport(ticker, { company: companyName, maxArticles: 8, includeRaw: true })
      .then((result) => { if (!cancelled) setReport(result); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Failed to fetch news report"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ticker, companyName, initialReport]);

  const fetchNews = useCallback(async (forceRefresh = false) => {
    if (!ticker) return;
    report ? setRefreshing(true) : setLoading(true);
    setError(null);
    try {
      setReport(await fetchTickerNewsReport(ticker, { company: companyName, maxArticles: 8, includeRaw: true, forceRefresh }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch news report");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [ticker, companyName, report]);

  const hasNews = Boolean(report && !report.error);
  const headlines = useMemo(() => (report?.latest_verified_headlines ?? []).map((item) => ({ ...item, tone: toneFor(item.title) })), [report]);
  const sources = useMemo(() => Array.from(new Set(headlines.map((item) => item.source))).sort(), [headlines]);
  const toneCounts = useMemo(() => headlines.reduce<Record<Tone, number>>((acc, item) => {
    acc[item.tone] += 1;
    return acc;
  }, { Bullish: 0, Bearish: 0, Neutral: 0 }), [headlines]);
  const hasHeadlineSentiment = headlines.length > 0;
  const visibleHeadlines = useMemo(() => headlines.filter((item) =>
    (toneFilter === "All" || item.tone === toneFilter) && (sourceFilter === "All" || item.source === sourceFilter)
  ), [headlines, toneFilter, sourceFilter]);
  const activeCategories = useMemo(() => CATEGORIES.filter((category) => !isBlankIntel(report?.[category.key] as string | undefined)), [report]);
  const diagnostics = report?.source_diagnostics ?? [];
  const healthySources = diagnostics.filter((item) => ["SUCCESS", "ZERO_RESULTS", "STALE_OR_UNDATED", "SKIPPED_SUFFICIENT_EVIDENCE"].includes(item.status));
  const failedSources = diagnostics.filter((item) => !["SUCCESS", "ZERO_RESULTS", "STALE_OR_UNDATED", "SKIPPED_SUFFICIENT_EVIDENCE"].includes(item.status));
  const overall = (report?.sentiment_overall?.trim() || "Neutral") as string;
  const overallTone: Tone = /bull/i.test(overall) ? "Bullish" : /bear/i.test(overall) ? "Bearish" : "Neutral";
  const isLive = Boolean(report && !report.cached && !refreshing);

  return (
    <section className="group relative overflow-hidden rounded-2xl border border-cyan-300/10 bg-[linear-gradient(145deg,rgba(8,15,28,.98),rgba(12,22,38,.96)_45%,rgba(6,13,25,.99))] text-slate-100 shadow-[0_20px_70px_rgba(2,8,23,.42)]">
      <div className="pointer-events-none absolute inset-0 opacity-70 [background-image:linear-gradient(rgba(148,163,184,.025)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,.025)_1px,transparent_1px)] [background-size:22px_22px]" />
      <div className="pointer-events-none absolute -right-24 -top-24 h-52 w-52 rounded-full bg-cyan-400/[0.06] blur-3xl transition-opacity duration-700 group-hover:opacity-100" />
      <div className="pointer-events-none absolute -bottom-24 -left-20 h-48 w-48 rounded-full bg-violet-500/[0.055] blur-3xl" />

      <header className="relative border-b border-white/[0.06] px-4 pb-3.5 pt-4">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/70 to-transparent" />
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="relative">
              <div className="absolute inset-0 rounded-xl bg-cyan-400/20 blur-lg" />
              <div className="relative rounded-xl border border-white/10 bg-slate-950/70 p-1.5">
                <MarketSymbolBadge symbol={ticker} size="md" />
              </div>
            </div>
            <div className="min-w-0">
              <div className="mb-0.5 flex items-center gap-2">
                <h3 className="truncate text-[11px] font-black uppercase tracking-[0.18em] text-slate-100">Live News Intelligence</h3>
                <span className="flex items-center gap-1 rounded-full border border-white/[0.07] bg-white/[0.035] px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wider text-slate-400">
                  <RadarPulse healthy={isLive} /> {refreshing ? "sync" : isLive ? "live" : report?.cached ? "cached" : "standby"}
                </span>
              </div>
              <p className="truncate text-[9px] text-slate-500">
                {report?.company_name ?? companyName ?? ticker}
                {report && <span> · {report.articles_after_dedup ?? report.articles_scraped} verified items · {report.lookback_days ?? 7}d window</span>}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {report?.generated_at && <span className="hidden text-[8px] tabular-nums text-slate-600 sm:inline">{relativeTime(report.generated_at)}</span>}
            <button onClick={() => fetchNews(true)} disabled={loading || refreshing} title="Refresh news intelligence" className="grid h-7 w-7 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.035] text-[12px] text-slate-400 transition duration-300 hover:-translate-y-0.5 hover:border-cyan-300/30 hover:bg-cyan-300/10 hover:text-cyan-200 disabled:opacity-40 motion-reduce:transform-none">
              <span className={refreshing ? "animate-spin motion-reduce:animate-none" : ""}>↻</span>
            </button>
            {onClose && <button onClick={onClose} title="Close" className="grid h-7 w-7 place-items-center rounded-lg border border-white/[0.05] text-slate-500 transition hover:border-white/10 hover:bg-white/[0.05] hover:text-slate-200">×</button>}
          </div>
        </div>

        {hasNews && report?.summary_headline && (
          <div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-3 rounded-xl border border-cyan-600/20 bg-white/95 p-3 shadow-sm dark:border-cyan-300/10 dark:bg-gradient-to-r dark:from-cyan-300/[0.07] dark:via-white/[0.025] dark:to-transparent dark:shadow-none">
            <div className="min-w-0">
              <div className="mb-1 flex items-center gap-1.5 text-[8px] font-black uppercase tracking-[0.18em] text-cyan-700 dark:text-cyan-300/80"><span className="h-1 w-1 animate-pulse rounded-full bg-cyan-500 dark:bg-cyan-300 motion-reduce:animate-none" /> Desk headline</div>
              <p className="line-clamp-2 text-[10px] font-semibold leading-relaxed text-slate-800 dark:font-medium dark:text-slate-200">{report.summary_headline}</p>
            </div>
            <div className={`rounded-lg border px-2 py-1.5 text-center ${toneClasses(overallTone)}`}>
              <div className="text-[7px] font-bold uppercase tracking-widest opacity-70">Bias</div>
              <div className="mt-0.5 text-[9px] font-black uppercase">{overallTone}</div>
            </div>
          </div>
        )}
      </header>

      <div className="relative p-4">
        {loading && !report && <LoadingSkeleton />}
        {error && !report && (
          <div className="rounded-xl border border-rose-400/20 bg-rose-400/[0.06] p-3 text-[10px] text-rose-200">
            <div className="flex items-center justify-between gap-3"><span>{error}</span><button onClick={() => fetchNews()} className="rounded-md border border-rose-300/20 px-2 py-1 text-[8px] font-black uppercase tracking-wider hover:bg-rose-300/10">Retry</button></div>
          </div>
        )}

        {hasNews && report && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-2">
              {(["Bullish", "Bearish", "Neutral"] as Tone[]).map((tone) => (
                <button key={tone} onClick={() => hasHeadlineSentiment && setToneFilter(toneFilter === tone ? "All" : tone)} disabled={!hasHeadlineSentiment} className={`relative overflow-hidden rounded-xl border p-2 text-left transition duration-300 hover:-translate-y-0.5 motion-reduce:transform-none ${toneFilter === tone ? toneClasses(tone) : "border-white/[0.06] bg-white/[0.025] text-slate-400 hover:border-white/10 hover:bg-white/[0.045]"}`}>
                  <div className="text-[7px] font-black uppercase tracking-[0.16em] opacity-70">{tone}</div>
                  <div className="mt-1 flex items-end justify-between"><span className="text-lg font-black tabular-nums leading-none">{hasHeadlineSentiment ? toneCounts[tone] : "—"}</span><span className={`mb-0.5 h-1.5 w-1.5 rounded-full ${tone === "Bullish" ? "bg-emerald-400" : tone === "Bearish" ? "bg-rose-400" : "bg-slate-400"}`} /></div>
                </button>
              ))}
            </div>

            {sources.length > 0 && (
              <div className="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {["All", ...sources].map((source) => <button key={source} onClick={() => setSourceFilter(source)} className={`whitespace-nowrap rounded-full border px-2 py-1 text-[8px] font-bold transition ${sourceFilter === source ? "border-cyan-300/30 bg-cyan-300/10 text-cyan-200" : "border-white/[0.06] bg-white/[0.02] text-slate-500 hover:border-white/10 hover:text-slate-300"}`}>{source === "All" ? "All sources" : source}</button>)}
              </div>
            )}

            {diagnostics.length > 0 && (
              <div className="flex items-center justify-between rounded-lg border border-white/[0.05] bg-black/10 px-2.5 py-2 text-[8px] text-slate-500">
                <span className="flex items-center gap-1.5"><RadarPulse healthy={failedSources.length === 0} /> {healthySources.length}/{diagnostics.length} sources responding</span>
                {failedSources.length > 0 && <span className="text-amber-300/80">{failedSources.length} degraded</span>}
              </div>
            )}

            <div>
              <div className="mb-2 flex items-center justify-between"><span className="text-[8px] font-black uppercase tracking-[0.18em] text-slate-500">Live tape</span><span className="text-[8px] text-slate-600">{visibleHeadlines.length} shown</span></div>
              <div className="space-y-2">
                {visibleHeadlines.length > 0 ? visibleHeadlines.map((headline, index) => (
                  <a key={`${headline.url}-${index}`} href={headline.url} target="_blank" rel="noopener noreferrer" className="group/item relative block overflow-hidden rounded-xl border border-white/[0.055] bg-white/[0.025] p-3 transition duration-300 hover:-translate-y-0.5 hover:border-cyan-300/20 hover:bg-cyan-300/[0.045] hover:shadow-[0_10px_30px_rgba(6,182,212,.06)] motion-reduce:transform-none">
                    <div className="absolute inset-y-0 left-0 w-px bg-gradient-to-b from-transparent via-cyan-300/40 to-transparent opacity-0 transition-opacity group-hover/item:opacity-100" />
                    <div className="flex gap-2.5">
                      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-slate-950/80 text-[8px] font-black text-cyan-300/75 shadow-inner">{sourceMark(headline.source)}</div>
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[7px] font-bold uppercase tracking-wider text-slate-600"><span className="text-cyan-300/70">{headline.source}</span><span>•</span><span>{relativeTime(headline.published_at)}</span>{headline.relevance && <><span>•</span><span>{headline.relevance}</span></>}</div>
                        <p className="line-clamp-2 text-[10px] font-semibold leading-relaxed text-slate-200 transition-colors group-hover/item:text-white">{headline.title}</p>
                        <div className="mt-2 flex items-center justify-between"><span className={`rounded border px-1.5 py-0.5 text-[7px] font-black uppercase tracking-wider ${toneClasses(headline.tone)}`}>{headline.tone}</span><span className="translate-x-1 text-[10px] text-slate-700 opacity-0 transition-all group-hover/item:translate-x-0 group-hover/item:text-cyan-300/80 group-hover/item:opacity-100 motion-reduce:transform-none">↗</span></div>
                      </div>
                    </div>
                  </a>
                )) : <div className="rounded-xl border border-dashed border-white/[0.07] px-3 py-6 text-center text-[9px] text-slate-600">No headlines match the selected filters.</div>}
              </div>
            </div>

            {activeCategories.length > 0 && (
              <div>
                <div className="mb-2 flex items-center justify-between"><span className="text-[8px] font-black uppercase tracking-[0.18em] text-slate-500">Intelligence stack</span><span className="rounded-full border border-white/[0.05] px-1.5 py-0.5 text-[7px] text-slate-600">{activeCategories.length} signals</span></div>
                <div className="grid grid-cols-2 gap-2">
                  {activeCategories.map((category, index) => {
                    const value = report[category.key] as string;
                    const expanded = expandedCategory === category.key;
                    return <button key={category.key} onClick={() => setExpandedCategory(expanded ? null : String(category.key))} className={`group/card relative overflow-hidden rounded-xl border p-2.5 text-left transition duration-300 hover:-translate-y-0.5 motion-reduce:transform-none ${expanded ? "col-span-2 border-violet-300/20 bg-violet-300/[0.055]" : "border-white/[0.055] bg-white/[0.02] hover:border-violet-300/15 hover:bg-violet-300/[0.035]"}`} style={{ transitionDelay: `${Math.min(index * 12, 80)}ms` }}>
                      <div className="mb-1.5 flex items-center justify-between gap-2"><span className="flex items-center gap-1.5 text-[8px] font-black uppercase tracking-wider text-slate-400"><span className="text-violet-300/80">{category.icon}</span>{category.short}</span><span className={`text-[9px] text-slate-600 transition-transform ${expanded ? "rotate-45" : ""}`}>+</span></div>
                      <p className={`${expanded ? "whitespace-pre-wrap" : "line-clamp-2"} text-[9px] leading-relaxed text-slate-500 group-hover/card:text-slate-300`}>{value}</p>
                    </button>;
                  })}
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <div className={`rounded-xl border p-2.5 ${toneClasses(overallTone)}`}><div className="text-[7px] font-black uppercase tracking-widest opacity-60">Overall sentiment</div><div className="mt-1 text-[11px] font-black">{overallTone}</div></div>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5"><div className="text-[7px] font-black uppercase tracking-widest text-slate-600">Risk flags</div><p className="mt-1 line-clamp-2 text-[9px] leading-relaxed text-slate-400">{isBlankIntel(report.risk_flags) ? "No material flag in current digest" : report.risk_flags}</p></div>
            </div>

            {report.llmError && <div className="rounded-lg border border-amber-400/15 bg-amber-400/[0.05] px-2.5 py-2 text-[8px] leading-relaxed text-amber-200/75">AI digest degraded: {report.llmError}</div>}

            {report.raw_articles && report.raw_articles.length > 0 && (
              <div>
                <button onClick={() => setShowRaw(!showRaw)} className="flex w-full items-center justify-between rounded-lg border border-white/[0.05] bg-white/[0.018] px-2.5 py-2 text-[8px] font-bold uppercase tracking-wider text-slate-500 transition hover:border-white/10 hover:text-slate-300"><span>Source ledger · {report.raw_articles.length} scraped</span><span className={`transition-transform ${showRaw ? "rotate-45" : ""}`}>+</span></button>
                {showRaw && <div className="mt-2 max-h-64 space-y-1.5 overflow-y-auto pr-1 [scrollbar-color:rgba(100,116,139,.35)_transparent]">{report.raw_articles.map((article, index) => <a key={`${article.url}-${index}`} href={article.url} target="_blank" rel="noopener noreferrer" className="block rounded-lg border border-white/[0.045] bg-black/10 px-2.5 py-2 transition hover:border-cyan-300/15 hover:bg-cyan-300/[0.03]"><div className="mb-1 flex items-center gap-1.5 text-[7px] uppercase tracking-wider text-slate-600"><span className="text-cyan-300/60">{article.source}</span><span>•</span><span>{relativeTime(article.published_at)}</span></div><p className="line-clamp-2 text-[9px] font-medium leading-relaxed text-slate-400">{article.title}</p></a>)}</div>}
              </div>
            )}
          </div>
        )}

        {!loading && !report && !error && <div className="py-10 text-center"><div className="mx-auto mb-3 h-8 w-8 rounded-full border border-cyan-300/10 bg-cyan-300/[0.04] p-2"><div className="h-full w-full animate-pulse rounded-full bg-cyan-300/30 motion-reduce:animate-none" /></div><p className="text-[9px] uppercase tracking-[0.18em] text-slate-600">No live news intelligence for {ticker}</p></div>}
      </div>
    </section>
  );
}
