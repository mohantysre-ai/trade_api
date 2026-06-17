"use client";

import React, { useState } from "react";
import type { TerminalIntelligence } from "@/lib/market-api";
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

function DrawerStructuredReasoningOutput({ analysis }: { analysis?: DrawerAnalysis | null }) {
  if (!analysis) {
    return (
      <div className="bg-slate-50 border border-slate-300 border-[0.5px] rounded-xl p-4">
        <div className="text-slate-500 text-[10px]">Loading analysis...</div>
      </div>
    );
  }

  if (analysis.error) {
    return (
      <div className="bg-slate-50 border border-slate-300 border-[0.5px] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Structured Reasoning Output</h3>
            <p className="text-[10px] text-slate-500 mt-0.5">Gemini / Pydantic mapped payload from the live ingestion stream.</p>
          </div>
          <div className="text-[10px] text-slate-500">Unavailable</div>
        </div>
        <div className="text-slate-500 text-[10px]">
          {analysis.error}
        </div>
      </div>
    );
  }

  const gates = normalizeRecord(analysis.active_seven_ic_gates);
  const riskCalc = normalizeRecord(analysis.active_risk_calc);
  const factorHub = normalizeRecord(analysis.active_factor_hub);

  return (
    <div className="space-y-3">
      <div className="bg-slate-50 border border-slate-300 border-[0.5px] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Structured Reasoning Output</h3>
            <p className="text-[10px] text-slate-500 mt-0.5">Gemini / Pydantic mapped payload from the live ingestion stream.</p>
          </div>
          <div className="text-[10px] text-slate-500">Available</div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[10px] text-slate-700">
          <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
            <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">News Catalysts</div>
            <p className="text-[11px] text-slate-700 leading-relaxed">{analysis.news_catalysts_card ?? "Not produced."}</p>
          </div>
          <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
            <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Macro Anchors</div>
            <p className="text-[11px] text-slate-700 leading-relaxed">{analysis.macro_anchors_card ?? "Not produced."}</p>
          </div>
          <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
            <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Insider / Insti Activity</div>
            <p className="text-[11px] text-slate-700 leading-relaxed">{analysis.insider_insti_activity_card ?? "Not produced."}</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px] text-slate-700 mt-3">
          <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
            <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Structural Thesis</div>
            <p className="text-[10px] text-slate-600 leading-relaxed">
              <span className="text-slate-700">Why Interested: </span>
              {analysis.why_interested ?? "Not produced."}
            </p>
            <p className="text-[10px] text-slate-600 mt-1 leading-relaxed">
              <span className="text-slate-700">Forward Revenue: </span>
              {analysis.future_revenue_model ?? "Not produced."}
            </p>
          </div>
          <div className="bg-white border border-emerald-200 border-[0.5px] p-3 rounded-lg">
            <div className="text-[9px] uppercase tracking-wider text-emerald-700 mb-1">Risk Calc / Factor Hub</div>
            {Object.keys(riskCalc).length || Object.keys(factorHub).length ? (
              <div className="space-y-2">
                {Object.entries(riskCalc).map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3">
                    <span className="text-slate-500 uppercase tracking-wider text-[9px] whitespace-nowrap">{formatSnakeKey(label)}</span>
                    <span className="text-slate-700 text-right">{String(value)}</span>
                  </div>
                ))}
                {Object.entries(factorHub).map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3">
                    <span className="text-slate-500 uppercase tracking-wider text-[9px] whitespace-nowrap">{formatSnakeKey(label)}</span>
                    <span className="text-slate-700 text-right">{String(value)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-slate-500">Risk calc / factor data not available.</p>
            )}
          </div>
        </div>
      </div>

      <div className="bg-slate-50 border border-slate-200 rounded p-3">
        <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-2">IC Gates</div>
        {Object.keys(gates).length ? (
          <div className="space-y-3">
            {Object.entries(gates).map(([gate, value]) => (
              <div key={gate} className="border-b border-slate-200 last:border-0 pb-3 last:pb-0">
                <div className="text-[11px] font-bold text-slate-700 mb-1">{formatGateKey(gate)}</div>
                <div className="text-[12px] text-slate-700 leading-relaxed whitespace-pre-wrap">{String(value)}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-slate-400 text-[11px]">IC Gates data is not available for this ticker.</div>
        )}
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
};

type DrawerTab = "aiNews" | "analysis" | "icGates";

export default function RightDrawer({ open, onClose, content }: { open: boolean; onClose: () => void; content?: DrawerContent | null }) {
  const [activeTab, setActiveTab] = useState<DrawerTab>("aiNews");

  const analysis = content?.analysis;
  const stock = content?.stock;
  const ticker = stock?.ticker ?? "";

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
    if (rec.includes("BUY")) return "bg-emerald-50 text-emerald-800 border-emerald-200";
    if (rec.includes("SELL")) return "bg-red-50 text-red-800 border-red-200";
    if (rec.includes("HOLD")) return "bg-amber-50 text-amber-800 border-amber-200";
    if (rec.includes("AVOID")) return "bg-red-50 text-red-700 border-red-200";
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

  return (
    <div
      className={`fixed top-0 right-0 h-full w-full lg:w-2/5 bg-white border-l border-slate-200 shadow-xl transform ${
        open ? "translate-x-0" : "translate-x-full"
      } transition-transform duration-300 z-50 overflow-y-auto`}
    >
      {/* Header */}
      <div className="p-4 flex items-center justify-between border-b border-slate-200 sticky top-0 bg-white/95 z-10">
        <div>
          <h4 className="text-slate-900 font-bold">{stock?.ticker ?? "Deep Asset Analysis"}</h4>
          <p className="text-[10px] text-slate-500">{stock?.name ?? "Analysis Payload"}</p>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-900 text-lg">
          x
        </button>
      </div>

      {/* Tab navigation */}
      <div className="flex border-b border-slate-200 sticky top-[60px] bg-white/95 z-10">
        <button
          onClick={() => setActiveTab("aiNews")}
          className={`flex-1 py-2.5 text-[10px] font-bold uppercase tracking-wider transition relative ${
            activeTab === "aiNews" ? "text-teal-700" : "text-slate-400 hover:text-slate-600"
          }`}
        >
          AI News Summary
          {activeTab === "aiNews" && <span className="absolute inset-x-2 -bottom-px h-0.5 bg-teal-600 rounded-full" />}
        </button>
        <button
          onClick={() => setActiveTab("analysis")}
          className={`flex-1 py-2.5 text-[10px] font-bold uppercase tracking-wider transition relative ${
            activeTab === "analysis" ? "text-teal-700" : "text-slate-400 hover:text-slate-600"
          }`}
        >
          Terminal Analysis
          {activeTab === "analysis" && <span className="absolute inset-x-2 -bottom-px h-0.5 bg-teal-600 rounded-full" />}
        </button>
        <button
          onClick={() => setActiveTab("icGates")}
          className={`flex-1 py-2.5 text-[10px] font-bold uppercase tracking-wider transition relative ${
            activeTab === "icGates" ? "text-teal-700" : "text-slate-400 hover:text-slate-600"
          }`}
        >
          IC GATES & REASONING
          {activeTab === "icGates" && <span className="absolute inset-x-2 -bottom-px h-0.5 bg-teal-600 rounded-full" />}
        </button>
      </div>

      {/* Tab content */}
      <div className="p-4">
        {/* AI News Tab */}
        {activeTab === "aiNews" && (
          ticker ? (
            <AITickerNewsPanel
              ticker={ticker}
              companyName={stock?.name}
            />
          ) : (
            <div className="text-slate-400 text-center py-8 text-[11px]">
              Select a ticker from the Asset Matrix to view AI-powered news summary.
            </div>
          )
        )}

        {/* Analysis Tab */}
        {activeTab === "analysis" && (
          <div className="space-y-4">
            {(score || recommendation) && (
              <div className="grid grid-cols-2 gap-3">
                {score && (
                  <div className="bg-slate-50 p-3 rounded border border-slate-200">
                    <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1">Market Score</div>
                    <div className={`text-3xl font-black ${getScoreColor(score)}`}>{score}/10</div>
                  </div>
                )}
                {recommendation && (
                  <div className={`p-3 rounded border ${getRecommendationColor(recommendation)}`}>
                    <div className="text-[11px] uppercase tracking-wider mb-1 opacity-70">Recommendation</div>
                    <div className="text-2xl font-black">{recommendation}</div>
                  </div>
                )}
              </div>
            )}

            {newsSummary?.catalysts && (
              <div className="bg-slate-50 p-3 rounded border border-slate-200">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-2">Key Catalysts</div>
                <div className="text-[12px] text-slate-700 space-y-1 whitespace-pre-wrap">{newsSummary.catalysts}</div>
              </div>
            )}

            {newsSummary?.outlook && (
              <div className="bg-emerald-50 border border-emerald-200 p-3 rounded">
                <div className="text-[11px] text-emerald-700 uppercase tracking-wider mb-2">Actionable Outlook</div>
                <div className="text-[12px] text-emerald-800 leading-relaxed">{newsSummary.outlook}</div>
              </div>
            )}

            {newsSummary?.sector && (
              <div className="bg-amber-50 p-3 rounded border border-amber-200">
                <div className="text-[11px] text-amber-700 uppercase tracking-wider mb-2">Sector Watch</div>
                <div className="text-[12px] text-amber-800">{newsSummary.sector}</div>
              </div>
            )}

            {analysis && (
              <>
                <div className="border-t border-slate-200 pt-4">
                  <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-3">Terminal Intelligence Payload</div>

                  {analysis.why_interested && (
                    <div className="bg-slate-50 p-3 rounded border border-slate-200 mb-3">
                      <div className="text-[11px] text-slate-500 mb-1">Focus</div>
                      <div className="text-[12px] text-slate-800">{analysis.why_interested}</div>
                    </div>
                  )}

                  {analysis.forensic_screen_card && (
                    <div className="bg-slate-50 p-3 rounded border border-slate-200 mb-3">
                      <div className="text-[11px] text-slate-500 mb-1">Forensic Screen</div>
                      <div className="text-[12px] text-slate-700">{analysis.forensic_screen_card}</div>
                    </div>
                  )}

                  {analysis.active_factor_hub?.selection_reason && (
                    <div className="bg-slate-50 p-3 rounded border border-slate-200">
                      <div className="text-[11px] text-slate-500 mb-1">Selection Reason</div>
                      <div className="text-[12px] text-slate-700">{analysis.active_factor_hub.selection_reason}</div>
                    </div>
                  )}
                </div>

                <details className="bg-slate-50 p-3 rounded border border-slate-200">
                  <summary className="text-[11px] text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-700">
                    Raw JSON Payload
                  </summary>
                  <pre className="text-[10px] text-slate-600 mt-2 overflow-auto max-h-96 whitespace-pre-wrap break-words">
                    {JSON.stringify(analysis, null, 2)}
                  </pre>
                </details>
              </>
            )}

            {!analysis && (
              <div className="text-slate-400 text-center py-8 text-[11px]">
                Loading analysis...
              </div>
            )}
          </div>
        )}

        {activeTab === "icGates" && (
          <DrawerStructuredReasoningOutput analysis={analysis} />
        )}
      </div>
    </div>
  );
}