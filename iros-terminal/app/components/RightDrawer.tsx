"use client";

import React, { useState } from "react";
import type { AITickerNewsReport, TerminalIntelligence } from "@/lib/market-api";
import AITickerNewsPanel from "./AITickerNewsPanel";

type DrawerAnalysis = TerminalIntelligence & {
  error?: string;
  active_seven_ic_gates?: unknown;
  active_risk_calc?: unknown;
  active_factor_hub?: unknown;
};

function normalizeRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      return {};
    }
  }

  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }

  return {};
}

function formatSnakeKey(key: string) {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatGateKey(key: string) {
  const labels: Record<string, string> = {
    q1_fund_buying: "Q1 — Fund Buying",
    q2_liquidity_delivery: "Q2 — Liquidity Delivery",
    q3_catalyst_validation: "Q3 — Catalyst Validation",
    q4_bear_thesis: "Q4 — Bear Thesis",
    q5_risk_reward: "Q5 — Risk / Reward",
    q6_quantitative_milestone: "Q6 — Quantitative Milestone",
    q7_governance_gate: "Q7 — Governance Gate",
  };

  return labels[key] ?? formatSnakeKey(key);
}

// Unique color palette for key-value pairs to make each key distinct
const KEY_COLORS = [
  { label: "text-violet-600", dot: "bg-violet-500" },
  { label: "text-cyan-600", dot: "bg-cyan-500" },
  { label: "text-rose-600", dot: "bg-rose-500" },
  { label: "text-amber-600", dot: "bg-amber-500" },
  { label: "text-lime-600", dot: "bg-lime-500" },
  { label: "text-fuchsia-600", dot: "bg-fuchsia-500" },
  { label: "text-teal-600", dot: "bg-teal-500" },
  { label: "text-orange-600", dot: "bg-orange-500" },
  { label: "text-sky-600", dot: "bg-sky-500" },
  { label: "text-pink-600", dot: "bg-pink-500" },
  { label: "text-indigo-600", dot: "bg-indigo-500" },
  { label: "text-emerald-600", dot: "bg-emerald-500" },
];

function getKeyColor(index: number) {
  return KEY_COLORS[index % KEY_COLORS.length];
}

// Unique gradient border colors for gate cards
const GATE_BORDER_COLORS = [
  "border-l-violet-500",
  "border-l-blue-500",
  "border-l-cyan-500",
  "border-l-teal-500",
  "border-l-amber-500",
  "border-l-rose-500",
  "border-l-fuchsia-500",
];

function getGateBorderColor(index: number) {
  return GATE_BORDER_COLORS[index % GATE_BORDER_COLORS.length];
}

function getGateBadgeColor(index: number) {
  const colors = [
    "bg-violet-100 text-violet-700 border-violet-200",
    "bg-blue-100 text-blue-700 border-blue-200",
    "bg-cyan-100 text-cyan-700 border-cyan-200",
    "bg-teal-100 text-teal-700 border-teal-200",
    "bg-amber-100 text-amber-700 border-amber-200",
    "bg-rose-100 text-rose-700 border-rose-200",
    "bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200",
  ];
  return colors[index % colors.length];
}

function DrawerStructuredReasoningOutput({ analysis }: { analysis?: DrawerAnalysis | null }) {
  if (!analysis) {
    return (
      <div className="bg-gradient-to-br from-slate-50 to-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-slate-300 animate-pulse" />
          <div className="text-slate-400 text-sm">Loading structured analysis...</div>
        </div>
      </div>
    );
  }

  if (analysis.error) {
    return (
      <div className="bg-gradient-to-br from-red-50 to-white border border-red-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-red-400" />
            <h3 className="text-xs font-bold text-red-700 uppercase tracking-wider">Structured Reasoning Output</h3>
          </div>
          <span className="text-[10px] bg-red-100 text-red-600 px-2 py-0.5 rounded-full font-medium">Unavailable</span>
        </div>
        <p className="text-xs text-red-500 ml-4">{analysis.error}</p>
      </div>
    );
  }

  const gates = normalizeRecord(analysis.active_seven_ic_gates);
  const riskCalc = normalizeRecord(analysis.active_risk_calc);
  const factorHub = normalizeRecord(analysis.active_factor_hub);

  return (
    <div className="space-y-4">
      {/* Main Structured Reasoning Section */}
      <div className="bg-gradient-to-br from-slate-50 to-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        {/* Section Header */}
        <div className="flex items-center justify-between px-5 py-3.5 bg-white border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="w-2.5 h-2.5 rounded-full bg-gradient-to-br from-teal-400 to-emerald-500 shadow-sm" />
            <h3 className="text-[11px] font-bold text-slate-700 uppercase tracking-wider">Structured Reasoning Output</h3>
          </div>
          <span className="text-[10px] bg-gradient-to-r from-emerald-50 to-teal-50 text-emerald-600 px-2.5 py-0.5 rounded-full font-medium border border-emerald-200 shadow-sm">
            Live
          </span>
        </div>

        {/* Three Card Grid */}
        <div className="p-4 sm:p-5">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* News Catalysts */}
            <div className="group bg-white border-l-2 border-l-violet-400 border border-slate-200 rounded-lg p-3.5 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200">
              <div className="flex items-center gap-1.5 mb-2">
                <div className="w-1.5 h-1.5 rounded-full bg-violet-400" />
                <span className="text-[9px] uppercase tracking-wider text-violet-600 font-semibold">News Catalysts</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">{analysis.news_catalysts_card ?? <span className="text-slate-400 italic">Not produced.</span>}</p>
            </div>

            {/* Macro Anchors */}
            <div className="group bg-white border-l-2 border-l-cyan-400 border border-slate-200 rounded-lg p-3.5 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200">
              <div className="flex items-center gap-1.5 mb-2">
                <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                <span className="text-[9px] uppercase tracking-wider text-cyan-600 font-semibold">Macro Anchors</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">{analysis.macro_anchors_card ?? <span className="text-slate-400 italic">Not produced.</span>}</p>
            </div>

            {/* Insider / Insti Activity */}
            <div className="group bg-white border-l-2 border-l-rose-400 border border-slate-200 rounded-lg p-3.5 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200">
              <div className="flex items-center gap-1.5 mb-2">
                <div className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                <span className="text-[9px] uppercase tracking-wider text-rose-600 font-semibold">Insider / Insti Activity</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">{analysis.insider_insti_activity_card ?? <span className="text-slate-400 italic">Not produced.</span>}</p>
            </div>
          </div>

          {/* Structural Thesis + Risk Calc / Factor Hub */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
            {/* Structural Thesis - full width */}
            <div className="md:col-span-2 bg-white border-l-2 border-l-amber-400 border border-slate-200 rounded-lg p-4 hover:shadow-md transition-all duration-200">
              <div className="flex items-center gap-1.5 mb-3">
                <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                <span className="text-[9px] uppercase tracking-wider text-amber-600 font-semibold">Structural Thesis</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="bg-gradient-to-br from-amber-50/50 to-white rounded-lg p-3 border border-amber-100/50">
                  <span className="text-[9px] uppercase tracking-wider text-amber-600 font-bold block mb-1">Why Interested</span>
                  <p className="text-xs text-slate-700 leading-relaxed">{analysis.why_interested ?? <span className="text-slate-400 italic">Not produced.</span>}</p>
                </div>
                <div className="bg-gradient-to-br from-teal-50/50 to-white rounded-lg p-3 border border-teal-100/50">
                  <span className="text-[9px] uppercase tracking-wider text-teal-600 font-bold block mb-1">Forward Revenue</span>
                  <p className="text-xs text-slate-700 leading-relaxed">{analysis.future_revenue_model ?? <span className="text-slate-400 italic">Not produced.</span>}</p>
                </div>
              </div>
            </div>

            {/* Risk Calc / Factor Hub */}
            <div className="md:col-span-2 bg-white border border-slate-200 rounded-lg overflow-hidden hover:shadow-md transition-all duration-200">
              <div className="bg-gradient-to-r from-slate-50 to-white px-4 py-2.5 border-b border-slate-100">
                <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">Risk Calc / Factor Hub</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-0">
                {/* Risk Calc */}
                <div className="p-4 border-r-0 md:border-r border-slate-100">
                  <div className="flex items-center gap-1.5 mb-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
                    <span className="text-[9px] uppercase tracking-wider text-violet-600 font-bold">Risk Calc</span>
                  </div>
                  {Object.keys(riskCalc).length ? (
                    <div className="space-y-1">
                      {Object.entries(riskCalc).map(([label, value], idx) => {
                        const isRiskFlag = label.toLowerCase() === 'risk_flag' || label.toLowerCase() === 'risk_flag_value';
                        const color = getKeyColor(idx);
                        return (
                          <div
                            key={label}
                            className={`flex items-center justify-between gap-2 py-1.5 px-2 rounded-md transition-colors ${
                              isRiskFlag ? 'bg-red-50 border border-red-100' : 'hover:bg-slate-50'
                            }`}
                          >
                            <span className="flex items-center gap-1.5">
                              <span className={`w-1 h-1 rounded-full ${color.dot} flex-shrink-0`} />
                              <span className={`text-[9px] uppercase tracking-wider ${isRiskFlag ? 'text-red-600 font-bold' : color.label}`}>
                                {formatSnakeKey(label)}
                              </span>
                            </span>
                            <span className={`text-xs font-semibold truncate ml-2 ${
                              isRiskFlag
                                ? 'text-red-600 uppercase tracking-wider animate-pulse'
                                : 'text-slate-700'
                            }`}>
                              {String(value)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 italic">No risk calc data available.</p>
                  )}
                </div>

                {/* Factor Hub */}
                <div className="p-4">
                  <div className="flex items-center gap-1.5 mb-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-[9px] uppercase tracking-wider text-emerald-600 font-bold">Factor Hub</span>
                  </div>
                  {Object.keys(factorHub).length ? (
                    <div className="space-y-1">
                      {Object.entries(factorHub).map(([label, value], idx) => {
                        const color = getKeyColor(idx + 5);
                        return (
                          <div key={label} className="py-1.5 px-2 rounded-md hover:bg-emerald-50/50 transition-colors">
                            <div className="flex items-center gap-1.5 mb-0.5">
                              <span className={`w-1 h-1 rounded-full ${color.dot} flex-shrink-0`} />
                              <span className={`text-[9px] uppercase tracking-wider ${color.label}`}>
                                {formatSnakeKey(label)}
                              </span>
                            </div>
                            <div className="text-xs text-slate-600 leading-relaxed pl-3.5">{String(value)}</div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 italic">No factor hub data available.</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* IC Gates Section */}
      <div className="bg-gradient-to-br from-slate-50 to-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-5 py-3.5 bg-white border-b border-slate-100">
          <div className="w-2 h-2 rounded-full bg-gradient-to-br from-indigo-400 to-purple-500 shadow-sm" />
          <h3 className="text-[11px] font-bold text-slate-700 uppercase tracking-wider">IC Gates</h3>
          {Object.keys(gates).length > 0 && (
            <span className="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full font-medium">
              {Object.keys(gates).length}
            </span>
          )}
        </div>
        <div className="p-4 sm:p-5">
          {Object.keys(gates).length ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(gates).map(([gate, value], idx) => (
                <div
                  key={gate}
                  className={`bg-white border-l-4 ${getGateBorderColor(idx)} border border-slate-200 rounded-lg p-3.5 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${getGateBadgeColor(idx)}`}>
                      {formatGateKey(gate)}
                    </span>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">{String(value)}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
              </svg>
              IC Gates data is not available for this ticker.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

type DrawerContent = {
  stock?: {
    ticker?: string;
    name?: string;
  } | null;
  analysis?: DrawerAnalysis | null;
  tickerNews?: AITickerNewsReport | null;
};

type DrawerTab = "aiNews" | "analysis";

export default function RightDrawer({ open, onClose, content }: { open: boolean; onClose: () => void; content?: DrawerContent | null }) {
  const [activeTab, setActiveTab] = useState<DrawerTab>("aiNews");

  const analysis = content?.analysis;
  const stock = content?.stock;
  const ticker = stock?.ticker ?? "";
  const tickerNews = content?.tickerNews;

  React.useEffect(() => {
    if (!ticker) return;
    const id = window.requestAnimationFrame(() => setActiveTab("aiNews"));
    return () => window.cancelAnimationFrame(id);
  }, [ticker]);

  const parseNewsSummary = (text: string | undefined) => {
    if (!text) return null;
    const sections: Record<string, string> = {};
    const lines = text.split("\n");
    let currentSection = "";
    let sectionContent: string[] = [];

    for (const line of lines) {
      if (line.includes("KEY CATALYSTS:")) {
        currentSection = "catalysts";
      } else if (line.includes("ACTIONABLE OUTLOOK:")) {
        if (currentSection && sectionContent.length) {
          sections[currentSection] = sectionContent.join("\n").trim();
        }
        currentSection = "outlook";
        sectionContent = [];
      } else if (line.includes("SECTOR WATCH:")) {
        if (currentSection && sectionContent.length) {
          sections[currentSection] = sectionContent.join("\n").trim();
        }
        currentSection = "sector";
        sectionContent = [];
      } else if (line.includes("MARKET SCORE:")) {
        if (currentSection && sectionContent.length) {
          sections[currentSection] = sectionContent.join("\n").trim();
        }
        currentSection = "score";
        sectionContent = [];
      } else if (line.includes("RECOMMENDATION:")) {
        if (currentSection && sectionContent.length) {
          sections[currentSection] = sectionContent.join("\n").trim();
        }
        currentSection = "recommendation";
        sectionContent = [];
      } else if (line.trim()) {
        sectionContent.push(line);
      }
    }

    if (currentSection && sectionContent.length) {
      sections[currentSection] = sectionContent.join("\n").trim();
    }

    return sections;
  };

  const newsSummary = parseNewsSummary(analysis?.news_catalysts_card);
  const score = newsSummary?.score?.match(/\d+/)?.[0];
  const recommendation = newsSummary?.recommendation?.trim().toUpperCase();

  const getRecommendationColor = (rec: string | undefined) => {
    if (!rec) return "bg-slate-100 text-slate-600 border-slate-200";
    if (rec.includes("BUY")) return "bg-gradient-to-br from-emerald-50 to-white text-emerald-800 border-emerald-300";
    if (rec.includes("SELL")) return "bg-gradient-to-br from-red-50 to-white text-red-800 border-red-300";
    if (rec.includes("HOLD")) return "bg-gradient-to-br from-amber-50 to-white text-amber-800 border-amber-300";
    if (rec.includes("AVOID")) return "bg-gradient-to-br from-red-50 to-white text-red-700 border-red-200";
    return "bg-slate-100 text-slate-600 border-slate-200";
  };

  const getScoreColor = (s: string | undefined) => {
    if (!s) return "text-slate-400";
    const num = parseInt(s, 10);
    if (num >= 8) return "text-emerald-600";
    if (num >= 6) return "text-amber-600";
    if (num >= 4) return "text-slate-600";
    return "text-red-600";
  };

  const getScoreRingColor = (s: string | undefined) => {
    if (!s) return "stroke-slate-300";
    const num = parseInt(s, 10);
    if (num >= 8) return "stroke-emerald-500";
    if (num >= 6) return "stroke-amber-500";
    if (num >= 4) return "stroke-slate-500";
    return "stroke-red-500";
  };

  return (
    <div
      className={`fixed top-0 right-0 h-full w-full lg:w-[42%] xl:w-[40%] 2xl:w-[36%] bg-white border-l border-slate-200 shadow-2xl transform ${
        open ? "translate-x-0" : "translate-x-full"
      } transition-transform duration-300 ease-out z-50 overflow-y-auto`}
    >
      {/* Header */}
      <div className="sticky top-0 z-20 bg-white/90 backdrop-blur-md border-b border-slate-200">
        <div className="px-5 py-3.5 flex items-center justify-between">
          <div className="min-w-0 flex-1">
            <h4 className="text-sm font-bold text-slate-900 truncate">{stock?.ticker ?? "Deep Asset Analysis"}</h4>
            <p className="text-[11px] text-slate-500 truncate">{stock?.name ?? "Analysis Payload"}</p>
          </div>
          <button
            onClick={onClose}
            className="ml-3 w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-all text-sm"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tab navigation */}
        <div className="flex px-5">
          <button
            onClick={() => setActiveTab("aiNews")}
            className={`relative py-2.5 px-1 text-[10px] font-bold uppercase tracking-wider transition-all duration-200 mr-6 ${
              activeTab === "aiNews"
                ? "text-teal-700"
                : "text-slate-400 hover:text-slate-600"
            }`}
          >
            AI News Summary
            {activeTab === "aiNews" && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 bg-gradient-to-r from-teal-500 to-emerald-500 rounded-full" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("analysis")}
            className={`relative py-2.5 px-1 text-[10px] font-bold uppercase tracking-wider transition-all duration-200 ${
              activeTab === "analysis"
                ? "text-teal-700"
                : "text-slate-400 hover:text-slate-600"
            }`}
          >
            Terminal Analysis
            {activeTab === "analysis" && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 bg-gradient-to-r from-teal-500 to-emerald-500 rounded-full" />
            )}
          </button>
        </div>
      </div>

      {/* Tab content */}
      <div className="p-5">
         {/* AI News Tab */}
         {activeTab === "aiNews" && (
           ticker ? (
             <AITickerNewsPanel
               ticker={ticker}
               companyName={stock?.name}
               initialReport={tickerNews ?? null}
             />
           ) : (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <svg className="w-12 h-12 mb-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
              </svg>
              <p className="text-xs">Select a ticker from the Asset Matrix</p>
              <p className="text-[10px] mt-0.5">to view AI-powered news summary.</p>
            </div>
          )
        )}

        {/* Analysis Tab */}
        {activeTab === "analysis" && (
          <div className="space-y-4">
            {/* Score & Recommendation Cards */}
            {(score || recommendation) && (
              <div className="grid grid-cols-2 gap-3">
                {score && (
                  <div className="bg-gradient-to-br from-white to-slate-50 p-4 rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow">
                    <div className="flex items-center gap-1.5 mb-2">
                      <div className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                      <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Market Score</span>
                    </div>
                    <div className="flex items-baseline gap-1">
                      <span className={`text-3xl font-black ${getScoreColor(score)}`}>{score}</span>
                      <span className="text-sm font-medium text-slate-400">/10</span>
                    </div>
                    {/* Mini ring indicator */}
                    <div className="mt-2 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${getScoreColor(score).replace('text-', 'bg-')}`}
                        style={{ width: `${parseInt(score, 10) * 10}%` }}
                      />
                    </div>
                  </div>
                )}
                {recommendation && (
                  <div className={`p-4 rounded-xl border shadow-sm hover:shadow-md transition-all ${getRecommendationColor(recommendation)}`}>
                    <div className="flex items-center gap-1.5 mb-2">
                      <div className="w-1.5 h-1.5 rounded-full opacity-60 bg-current" />
                      <span className="text-[10px] uppercase tracking-wider font-semibold opacity-70">Signal</span>
                    </div>
                    <div className="text-2xl font-black">{recommendation}</div>
                  </div>
                )}
              </div>
            )}

            {/* Key Catalysts */}
            {newsSummary?.catalysts && (
              <div className="bg-gradient-to-br from-white to-slate-50 p-4 rounded-xl border border-slate-200 shadow-sm">
                <div className="flex items-center gap-1.5 mb-2.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-violet-400" />
                  <span className="text-[10px] text-violet-600 uppercase tracking-wider font-bold">Key Catalysts</span>
                </div>
                <div className="text-xs text-slate-600 leading-relaxed space-y-1 whitespace-pre-wrap">{newsSummary.catalysts}</div>
              </div>
            )}

            {/* Actionable Outlook */}
            {newsSummary?.outlook && (
              <div className="bg-gradient-to-br from-emerald-50 to-white border-l-2 border-l-emerald-400 border border-emerald-200 p-4 rounded-xl shadow-sm">
                <div className="flex items-center gap-1.5 mb-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  <span className="text-[10px] text-emerald-700 uppercase tracking-wider font-bold">Actionable Outlook</span>
                </div>
                <div className="text-xs text-emerald-800 leading-relaxed">{newsSummary.outlook}</div>
              </div>
            )}

            {/* Sector Watch */}
            {newsSummary?.sector && (
              <div className="bg-gradient-to-br from-amber-50 to-white border-l-2 border-l-amber-400 border border-amber-200 p-4 rounded-xl shadow-sm">
                <div className="flex items-center gap-1.5 mb-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  <span className="text-[10px] text-amber-700 uppercase tracking-wider font-bold">Sector Watch</span>
                </div>
                <div className="text-xs text-amber-800 leading-relaxed">{newsSummary.sector}</div>
              </div>
            )}

            {/* Terminal Intelligence Payload */}
            {analysis && (
              <>
                <div className="border-t border-slate-100 pt-5">
                  <div className="flex items-center gap-2 mb-4">
                    <div className="w-2 h-2 rounded-full bg-gradient-to-br from-slate-400 to-slate-500 shadow-sm" />
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Terminal Intelligence Payload</span>
                  </div>

                  <div className="grid grid-cols-1 gap-3">
                    {analysis.why_interested && (
                      <div className="bg-gradient-to-br from-white to-slate-50 border-l-4 border-l-teal-400 border border-slate-200 rounded-lg p-3.5 hover:shadow-md transition-all">
                        <span className="text-[9px] uppercase tracking-wider text-teal-600 font-bold block mb-1">Focus</span>
                        <p className="text-xs text-slate-700 leading-relaxed">{analysis.why_interested}</p>
                      </div>
                    )}

                    {analysis.forensic_screen_card && (
                      <div className="bg-gradient-to-br from-white to-slate-50 border-l-4 border-l-cyan-400 border border-slate-200 rounded-lg p-3.5 hover:shadow-md transition-all">
                        <span className="text-[9px] uppercase tracking-wider text-cyan-600 font-bold block mb-1">Forensic Screen</span>
                        <p className="text-xs text-slate-600 leading-relaxed">{analysis.forensic_screen_card}</p>
                      </div>
                    )}

                    {analysis.active_factor_hub?.selection_reason && (
                      <div className="bg-gradient-to-br from-white to-slate-50 border-l-4 border-l-indigo-400 border border-slate-200 rounded-lg p-3.5 hover:shadow-md transition-all">
                        <span className="text-[9px] uppercase tracking-wider text-indigo-600 font-bold block mb-1">Selection Reason</span>
                        <p className="text-xs text-slate-600 leading-relaxed">{analysis.active_factor_hub.selection_reason}</p>
                      </div>
                    )}
                  </div>
                </div>

                <DrawerStructuredReasoningOutput analysis={analysis} />

                {/* Raw JSON details */}
                <details className="group bg-gradient-to-br from-slate-50 to-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
                  <summary className="flex items-center gap-2 px-4 py-3 text-[11px] text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-700 hover:bg-slate-100/50 transition-colors font-semibold">
                    <svg className="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                    Raw JSON Payload
                  </summary>
                  <pre className="text-[10px] text-slate-500 p-4 pt-2 overflow-auto max-h-96 whitespace-pre-wrap break-words bg-slate-900/5 font-mono leading-relaxed">
                    {JSON.stringify(analysis, null, 2)}
                  </pre>
                </details>
              </>
            )}

            {!analysis && (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                <div className="w-8 h-8 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin mb-3" />
                <p className="text-xs">Loading analysis...</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}