"use client";

import React, { useCallback, useEffect, useState } from "react";
import type { AITickerNewsReport } from "@/lib/market-api";
import { fetchTickerNewsReport } from "@/lib/market-api";

// ---------------------------------------------------------------------------
// Category configuration
// ---------------------------------------------------------------------------

const CATEGORIES: Array<{
  key: keyof AITickerNewsReport;
  label: string;
  icon: string;
  color: string;
}> = [
  { key: "insider_activity", label: "Insider Activity", icon: "🔒", color: "border-l-purple-500" },
  { key: "institutional_activity", label: "Institutional Activity", icon: "🏦", color: "border-l-blue-500" },
  { key: "order_book_block_deals", label: "Order Book / Block Deals", icon: "📋", color: "border-l-cyan-500" },
  { key: "future_expansion_capex", label: "Future Expansion / Capex", icon: "🚀", color: "border-l-emerald-500" },
  { key: "auditor_changes", label: "Auditor Changes", icon: "🔍", color: "border-l-amber-500" },
  { key: "dividend_news", label: "Dividend / Buyback / Bonus", icon: "💰", color: "border-l-green-500" },
  { key: "new_orders_contracts", label: "New Orders / Contracts", icon: "📝", color: "border-l-teal-500" },
  { key: "earnings_results", label: "Earnings / Results", icon: "📊", color: "border-l-indigo-500" },
  { key: "management_changes", label: "Management Changes", icon: "👔", color: "border-l-orange-500" },
  { key: "regulatory_filings", label: "Regulatory Filings", icon: "⚖️", color: "border-l-red-500" },
];

const SENTIMENT_CONFIG: Record<string, { label: string; bg: string; text: string; border: string }> = {
  bullish: { label: "Bullish", bg: "bg-emerald-50", text: "text-emerald-800", border: "border-emerald-200" },
  neutral: { label: "Neutral", bg: "bg-slate-50", text: "text-slate-700", border: "border-slate-200" },
  bearish: { label: "Bearish", bg: "bg-red-50", text: "text-red-800", border: "border-red-200" },
};

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-4 bg-slate-200 rounded w-3/4" />
      <div className="h-3 bg-slate-200 rounded w-1/2" />
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-20 bg-slate-100 rounded" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel component
// ---------------------------------------------------------------------------

export default function AITickerNewsPanel({
  ticker,
  companyName,
  onClose,
}: {
  ticker: string;
  companyName?: string;
  onClose?: () => void;
}) {
  const [report, setReport] = useState<AITickerNewsReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [showRawArticles, setShowRawArticles] = useState(false);

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

  useEffect(() => {
    if (!ticker) {
      const id = window.requestAnimationFrame(() => {
        setReport(null);
        setError(null);
      });
      return () => window.cancelAnimationFrame(id);
    }

    let cancelled = false;
    const id = window.requestAnimationFrame(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
    });

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
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(id);
    };
  }, [ticker, companyName]);

  const sentimentCfg = SENTIMENT_CONFIG[report?.sentiment_overall?.toLowerCase() ?? ""] ?? SENTIMENT_CONFIG.neutral;
  const hasNews = report && !report.error;

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-100">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📰</span>
            <div>
              <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                AI News Summary
              </h3>
              <p className="text-[10px] text-slate-500">
                {report?.company_name ?? ticker} · {report?.articles_scraped ?? 0} articles analyzed
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {report?.generated_at && (
              <span className="text-[9px] text-slate-400">
                {new Date(report.generated_at).toLocaleTimeString()}
                {report.cached ? " (cached)" : ""}
              </span>
            )}
            <button
              onClick={() => fetchNews(true)}
              disabled={loading}
              className="px-2 py-1 text-[10px] font-bold uppercase bg-slate-100 hover:bg-slate-200 text-slate-600 rounded transition disabled:opacity-50"
              title="Force refresh"
            >
              ↻
            </button>
            {onClose && (
              <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-sm">
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Summary headline */}
        {hasNews && report.summary_headline && (
          <div className="mt-2 text-[11px] text-slate-700 leading-relaxed bg-slate-50 p-2 rounded border border-slate-100">
            <span className="font-semibold">Headline: </span>
            {report.summary_headline}
          </div>
        )}
      </div>

      {/* Body */}
      <div className="p-4">
        {loading && !report && <LoadingSkeleton />}

        {error && !report && (
          <div className="text-[11px] text-red-600 bg-red-50 border border-red-200 p-3 rounded">
            {error}
            <button
              onClick={() => fetchNews()}
              className="ml-2 underline hover:no-underline"
            >
              Retry
            </button>
          </div>
        )}

        {hasNews && (
          <div className="space-y-3">
            {/* Sentiment + Risk row */}
            <div className="grid grid-cols-2 gap-3">
              <div className={`p-3 rounded border ${sentimentCfg.border} ${sentimentCfg.bg}`}>
                <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">Market Sentiment</div>
                <div className={`text-lg font-black ${sentimentCfg.text}`}>{sentimentCfg.label}</div>
              </div>
              <div className="p-3 rounded border border-slate-200 bg-slate-50">
                <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">Risk Flags</div>
                <div className="text-[11px] text-slate-700">
                  {report.risk_flags && report.risk_flags !== "None"
                    ? report.risk_flags
                    : "No significant risks flagged"}
                </div>
              </div>
            </div>

            {/* Category grid */}
            <div className="space-y-2">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">
                Intelligence Categories
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {CATEGORIES.map((cat) => {
                  const value = report[cat.key] as string | undefined;
                  if (!value || value === "No recent news found.") return null;

                  return (
                    <div
                      key={cat.key}
                      className={`bg-slate-50 border border-slate-100 rounded-lg p-2.5 border-l-4 ${cat.color.replace("border-l-", "border-l-")} cursor-pointer hover:bg-slate-100 transition`}
                      onClick={() =>
                        setExpandedCategory(expandedCategory === cat.key ? null : cat.key)
                      }
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className="text-[10px]">{cat.icon}</span>
                        <span className="text-[9px] font-bold text-slate-600 uppercase tracking-wider">
                          {cat.label}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-700 leading-relaxed line-clamp-2">
                        {value}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Expanded category detail */}
            {expandedCategory && report[expandedCategory as keyof AITickerNewsReport] && (
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">
                    {CATEGORIES.find((c) => c.key === expandedCategory)?.label ?? expandedCategory}
                  </span>
                  <button
                    onClick={() => setExpandedCategory(null)}
                    className="text-[10px] text-slate-400 hover:text-slate-700"
                  >
                    Close
                  </button>
                </div>
                <p className="text-[11px] text-slate-700 leading-relaxed whitespace-pre-wrap">
                  {String(report[expandedCategory as keyof AITickerNewsReport])}
                </p>
              </div>
            )}

            {/* Raw articles toggle */}
            {report.raw_articles && report.raw_articles.length > 0 && (
              <div className="mt-3">
                <button
                  onClick={() => setShowRawArticles(!showRawArticles)}
                  className="text-[10px] text-slate-500 hover:text-slate-700 underline underline-offset-2"
                >
                  {showRawArticles
                    ? "Hide raw articles"
                    : `Show ${report.raw_articles.length} scraped articles`}
                </button>

                {showRawArticles && (
                  <div className="mt-2 space-y-1.5 max-h-60 overflow-y-auto">
                    {report.raw_articles.map((art, i) => (
                      <div key={i} className="text-[10px] text-slate-600 bg-white border border-slate-100 p-2 rounded hover:bg-slate-50">
                        <a
                          href={art.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-medium text-slate-800 hover:text-teal-700 block truncate"
                        >
                          {art.title}
                        </a>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[9px] text-slate-400">{art.source}</span>
                          <span className="text-[8px] text-slate-300">·</span>
                          <span className="text-[9px] text-slate-400">{art.relevance}</span>
                          {art.published_at && (
                            <>
                              <span className="text-[8px] text-slate-300">·</span>
                              <span className="text-[9px] text-slate-400">
                                {new Date(art.published_at).toLocaleDateString()}
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
          <div className="text-[11px] text-slate-400 text-center py-6">
            No news data available for {ticker}
          </div>
        )}
      </div>
    </div>
  );
}