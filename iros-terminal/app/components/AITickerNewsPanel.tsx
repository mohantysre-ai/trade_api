import React, { useCallback, useEffect, useState } from "react";
import type { AITickerNewsReport } from "@/lib/market-api";
import { fetchTickerNewsReport } from "@/lib/market-api";

// ---------------------------------------------------------------------------
// Category configuration with enriched styling
// ---------------------------------------------------------------------------

const CATEGORIES: Array<{
  key: keyof AITickerNewsReport;
  label: string;
  icon: string;
  accent: string;
  gradient: string;
  badgeClass: string;
}> = [
  {
    key: "insider_activity",
    label: "Insider Activity",
    icon: "🔒",
    accent: "border-l-purple-500",
    gradient: "from-purple-50 to-white",
    badgeClass: "bg-purple-100 text-purple-700 border-purple-200",
  },
  {
    key: "institutional_activity",
    label: "Institutional Activity",
    icon: "🏦",
    accent: "border-l-blue-500",
    gradient: "from-blue-50 to-white",
    badgeClass: "bg-blue-100 text-blue-700 border-blue-200",
  },
  {
    key: "order_book_block_deals",
    label: "Order Book / Block Deals",
    icon: "📋",
    accent: "border-l-cyan-500",
    gradient: "from-cyan-50 to-white",
    badgeClass: "bg-cyan-100 text-cyan-700 border-cyan-200",
  },
  {
    key: "future_expansion_capex",
    label: "Future Expansion / Capex",
    icon: "🚀",
    accent: "border-l-emerald-500",
    gradient: "from-emerald-50 to-white",
    badgeClass: "bg-emerald-100 text-emerald-700 border-emerald-200",
  },
  {
    key: "auditor_changes",
    label: "Auditor Changes",
    icon: "🔍",
    accent: "border-l-amber-500",
    gradient: "from-amber-50 to-white",
    badgeClass: "bg-amber-100 text-amber-700 border-amber-200",
  },
  {
    key: "dividend_news",
    label: "Dividend / Buyback / Bonus",
    icon: "💰",
    accent: "border-l-green-500",
    gradient: "from-green-50 to-white",
    badgeClass: "bg-green-100 text-green-700 border-green-200",
  },
  {
    key: "new_orders_contracts",
    label: "New Orders / Contracts",
    icon: "📝",
    accent: "border-l-teal-500",
    gradient: "from-teal-50 to-white",
    badgeClass: "bg-teal-100 text-teal-700 border-teal-200",
  },
  {
    key: "earnings_results",
    label: "Earnings / Results",
    icon: "📊",
    accent: "border-l-indigo-500",
    gradient: "from-indigo-50 to-white",
    badgeClass: "bg-indigo-100 text-indigo-700 border-indigo-200",
  },
  {
    key: "management_changes",
    label: "Management Changes",
    icon: "👔",
    accent: "border-l-orange-500",
    gradient: "from-orange-50 to-white",
    badgeClass: "bg-orange-100 text-orange-700 border-orange-200",
  },
  {
    key: "regulatory_filings",
    label: "Regulatory Filings",
    icon: "⚖️",
    accent: "border-l-rose-500",
    gradient: "from-rose-50 to-white",
    badgeClass: "bg-rose-100 text-rose-700 border-rose-200",
  },
];

const SENTIMENT_CONFIG: Record<string, { label: string; gradient: string; text: string; border: string; icon: string }> = {
  bullish: {
    label: "Bullish",
    gradient: "bg-gradient-to-br from-emerald-50 to-white",
    text: "text-emerald-700",
    border: "border-emerald-300",
    icon: "📈",
  },
  neutral: {
    label: "Neutral",
    gradient: "bg-gradient-to-br from-slate-50 to-white",
    text: "text-slate-600",
    border: "border-slate-200",
    icon: "➡️",
  },
  bearish: {
    label: "Bearish",
    gradient: "bg-gradient-to-br from-red-50 to-white",
    text: "text-red-700",
    border: "border-red-300",
    icon: "📉",
  },
};

// ---------------------------------------------------------------------------
// Loading skeleton — shimmer effect
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="flex gap-3">
        <div className="h-10 w-10 rounded-full bg-slate-200" />
        <div className="flex-1 space-y-2">
          <div className="h-4 bg-slate-200 rounded w-3/4" />
          <div className="h-3 bg-slate-200 rounded w-1/2" />
        </div>
      </div>
      <div className="h-12 bg-slate-100 rounded-lg" />
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-24 bg-slate-100 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mini Sparkline — decorative animated bar chart
// ---------------------------------------------------------------------------

function MiniSparkline({ className = "" }: { className?: string }) {
  const bars = [40, 65, 45, 80, 55, 90, 70, 95, 75, 85];
  return (
    <div className={`flex items-end gap-[2px] h-6 ${className}`}>
      {bars.map((h, i) => (
        <div
          key={i}
          className="w-1.5 rounded-t-sm bg-gradient-to-t from-emerald-400 to-emerald-300 opacity-60 transition-all duration-500"
          style={{ height: `${h}%`, animationDelay: `${i * 80}ms` }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel component — redesigned with modern aesthetics
// ---------------------------------------------------------------------------

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
  const [error, setError] = useState<string | null>(null);
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [showRawArticles, setShowRawArticles] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    fetchTickerNewsReport(ticker, {
      company: companyName,
      maxArticles: 50,
      includeRaw: true,
    })
      .then((result) => {
        if (!cancelled) setReport(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to fetch news report");
      });
    return () => { cancelled = true; };
  }, [ticker, companyName]);

  const fetchNews = useCallback(async (forceRefresh = false) => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchTickerNewsReport(ticker, {
        company: companyName,
        maxArticles: 50,
        includeRaw: true,
        forceRefresh,
      });
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch news report");
    } finally {
      setLoading(false);
    }
  }, [ticker, companyName]);

  const sentimentCfg = SENTIMENT_CONFIG[report?.sentiment_overall?.toLowerCase() ?? ""] ?? SENTIMENT_CONFIG.neutral;
  const hasNews = report && !report.error;
  const activeCategories = CATEGORIES.filter((cat) => {
    const value = report?.[cat.key] as string | undefined;
    return value && value !== "No recent news found.";
  });

  return (
    <div className="bg-gradient-to-br from-white to-slate-50/80 border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
      {/* ── Header ── */}
      <div className="relative px-5 pt-5 pb-4 border-b border-slate-100 bg-white/90 backdrop-blur-sm">
        {/* Decorative top gradient bar */}
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-violet-400 via-teal-400 to-amber-400" />

        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            {/* Avatar circle */}
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-emerald-500 flex items-center justify-center text-white text-lg shadow-sm flex-shrink-0">
              📰
            </div>
            <div className="min-w-0">
              <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider truncate">
                AI News Summary
              </h3>
              <p className="text-[10px] text-slate-500 truncate">
                {report?.company_name ?? ticker}
                {report && <span className="ml-1.5">· {report.articles_scraped} articles analyzed</span>}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0 ml-3">
            {report?.generated_at && (
              <span className="text-[9px] text-slate-400 whitespace-nowrap">
                {new Date(report.generated_at).toLocaleTimeString()}
                {report.cached ? (
                  <span className="ml-1 text-amber-500 font-medium">(cached)</span>
                ) : (
                  <span className="ml-1 text-emerald-500 font-medium">(live)</span>
                )}
              </span>
            )}
            <button
              onClick={() => fetchNews(true)}
              disabled={loading}
              className="w-7 h-7 flex items-center justify-center rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-500 hover:text-slate-700 transition disabled:opacity-50 text-xs"
              title="Force refresh"
            >
              ↻
            </button>
            {onClose && (
              <button
                onClick={onClose}
                className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Summary headline with sparkline */}
        {hasNews && report.summary_headline && (
          <div className="mt-3 flex items-start gap-3 bg-gradient-to-br from-slate-50 to-white border border-slate-200 rounded-xl p-3.5 hover:shadow-sm transition-shadow">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-1">
                <div className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                <span className="text-[9px] uppercase tracking-wider text-teal-600 font-bold">Headline</span>
              </div>
              <p className="text-[11px] text-slate-700 leading-relaxed">
                {report.summary_headline}
              </p>
            </div>
            <MiniSparkline className="flex-shrink-0" />
          </div>
        )}
      </div>

      {/* ── Body ── */}
      <div className="p-5">
        {loading && !report && <LoadingSkeleton />}

        {error && !report && (
          <div className="flex items-center gap-3 bg-gradient-to-br from-red-50 to-white border border-red-200 rounded-xl p-4">
            <div className="w-8 h-8 rounded-full bg-red-100 flex items-center justify-center text-red-500 flex-shrink-0">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[11px] text-red-600 font-medium">{error}</p>
            </div>
            <button
              onClick={() => fetchNews()}
              className="px-3 py-1.5 text-[10px] font-bold uppercase bg-red-100 hover:bg-red-200 text-red-700 rounded-lg transition whitespace-nowrap"
            >
              Retry
            </button>
          </div>
        )}

        {hasNews && (
          <div className="space-y-4">
            {/* ── Sentiment + Risk row ── */}
            <div className="grid grid-cols-2 gap-3">
              {/* Sentiment */}
              <div className={`relative overflow-hidden rounded-xl border ${sentimentCfg.border} ${sentimentCfg.gradient} p-3.5 shadow-sm hover:shadow-md transition-all`}>
                {/* Decorative corner accent */}
                <div className="absolute -top-3 -right-3 w-12 h-12 rounded-full opacity-10 bg-current" />
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-sm">{sentimentCfg.icon}</span>
                  <span className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Market Sentiment</span>
                </div>
                <div className={`text-xl font-black ${sentimentCfg.text} flex items-center gap-2`}>
                  {sentimentCfg.label}
                </div>
              </div>

              {/* Risk Flags */}
              <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-gradient-to-br from-white to-slate-50 p-3.5 shadow-sm hover:shadow-md transition-all">
                <div className="absolute -top-3 -left-3 w-12 h-12 rounded-full opacity-5 bg-amber-400" />
                <div className="flex items-center gap-2 mb-1.5">
                  <svg className="w-3.5 h-3.5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                  </svg>
                  <span className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Risk Flags</span>
                </div>
                <div className="text-[11px] text-slate-700 leading-relaxed">
                  {report.risk_flags && report.risk_flags !== "None"
                    ? report.risk_flags
                    : <span className="text-emerald-600 font-medium flex items-center gap-1">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        No significant risks flagged
                      </span>}
                </div>
              </div>
            </div>

            {/* ── Category grid ── */}
            {activeCategories.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-1.5 h-1.5 rounded-full bg-gradient-to-br from-indigo-400 to-purple-500" />
                  <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">Intelligence Categories</span>
                  <span className="text-[9px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded-full font-medium">
                    {activeCategories.length}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                  {activeCategories.map((cat, idx) => {
                    const value = report[cat.key] as string;
                    const isExpanded = expandedCategory === cat.key;

                    return (
                      <div
                        key={cat.key}
                        onClick={() => setExpandedCategory(isExpanded ? null : cat.key)}
                        className={`group relative bg-white border-l-4 ${cat.accent} border border-slate-200 rounded-xl p-3.5 cursor-pointer transition-all duration-200 ${
                          isExpanded
                            ? "shadow-md -translate-y-0.5 ring-2 ring-slate-200"
                            : "hover:shadow-md hover:-translate-y-0.5"
                        }`}
                        style={{ animationDelay: `${idx * 50}ms` }}
                      >
                        {/* Top accent gradient line */}
                        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-slate-200 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

                        <div className="flex items-start justify-between mb-1.5">
                          <div className="flex items-center gap-1.5 min-w-0 flex-1">
                            <span className="text-[11px] flex-shrink-0">{cat.icon}</span>
                            <span className="text-[9px] font-bold text-slate-700 uppercase tracking-wider truncate">
                              {cat.label}
                            </span>
                          </div>
                          <svg
                            className={`w-3 h-3 text-slate-400 transition-transform duration-200 flex-shrink-0 mt-0.5 ${
                              isExpanded ? "rotate-180" : ""
                            }`}
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={2}
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                          </svg>
                        </div>

                        <p className={`text-[10px] text-slate-600 leading-relaxed transition-all ${
                          isExpanded ? "" : "line-clamp-2"
                        }`}>
                          {value}
                        </p>

                        {/* Expanded detail */}
                        {isExpanded && (
                          <div className="mt-2.5 pt-2.5 border-t border-slate-100">
                            <p className="text-[11px] text-slate-700 leading-relaxed whitespace-pre-wrap">
                              {value}
                            </p>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── Raw articles toggle ── */}
            {report.raw_articles && report.raw_articles.length > 0 && (
              <div className="pt-2">
                <button
                  onClick={() => setShowRawArticles(!showRawArticles)}
                  className="flex items-center gap-2 text-[10px] text-slate-500 hover:text-slate-700 transition-colors group"
                >
                  <div className="w-5 h-5 rounded bg-slate-100 group-hover:bg-slate-200 flex items-center justify-center transition-colors">
                    <svg
                      className={`w-3 h-3 transition-transform duration-200 ${showRawArticles ? "rotate-90" : ""}`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                    </svg>
                  </div>
                  <span className="font-medium">
                    {showRawArticles
                      ? "Hide raw articles"
                      : `Show ${report.raw_articles.length} scraped articles`}
                  </span>
                </button>

                {showRawArticles && (
                  <div className="mt-3 space-y-1.5 max-h-72 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100 bg-white">
                    {report.raw_articles.map((art, i) => (
                      <div key={i} className="px-3.5 py-2.5 hover:bg-slate-50 transition-colors">
                        <a
                          href={art.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] font-semibold text-slate-800 hover:text-teal-700 block leading-tight"
                        >
                          {art.title}
                        </a>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          <span className="text-[8px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium uppercase tracking-wider">
                            {art.source}
                          </span>
                          <span className="text-[8px] text-slate-400">·</span>
                          <span className="text-[8px] text-slate-500">{art.relevance}</span>
                          {art.published_at && (
                            <>
                              <span className="text-[8px] text-slate-400">·</span>
                              <span className="text-[8px] text-slate-500">
                                {new Date(art.published_at).toLocaleDateString("en-IN", {
                                  day: "numeric",
                                  month: "short",
                                  year: "numeric",
                                })}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {!loading && !report && !error && (
          <div className="flex flex-col items-center justify-center py-10 text-slate-400">
            <svg className="w-10 h-10 mb-2 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
            </svg>
            <p className="text-xs">No news data available for {ticker}</p>
          </div>
        )}
      </div>
    </div>
  );
}