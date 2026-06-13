"use client";

import React from "react";
import type { SelectionMeta, TerminalIntelligence } from "@/lib/market-api";

type DrawerAnalysis = TerminalIntelligence & {
  selectionMeta?: SelectionMeta;
  error?: string;
};

type DrawerContent = {
  stock?: {
    ticker?: string;
    name?: string;
  } | null;
  analysis?: DrawerAnalysis | null;
};

export default function RightDrawer({ open, onClose, content }: { open: boolean; onClose: () => void; content?: DrawerContent | null }) {
  const analysis = content?.analysis;
  const stock = content?.stock;

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
      <div className="p-4 flex items-center justify-between border-b border-slate-200 sticky top-0 bg-white/95">
        <div>
          <h4 className="text-slate-900 font-bold">{stock?.ticker ?? "Deep Asset Analysis"}</h4>
          <p className="text-[10px] text-slate-500">{stock?.name ?? "Analysis Payload"}</p>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-900 text-lg">
          x
        </button>
      </div>

      <div className="p-4 space-y-4">
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

              {analysis.selectionMeta && (
                <div className="bg-slate-50 p-3 rounded border border-slate-200 mb-3 text-[12px] text-slate-700">
                  <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1">Selection Basis</div>
                  <div className="font-bold text-slate-900 capitalize">{analysis.selectionMeta.mode}</div>
                  <div className="mt-1 text-slate-600">{analysis.selectionMeta.reason}</div>
                  <div className="mt-1 text-slate-400">Data date: {analysis.selectionMeta.dataDate}</div>
                </div>
              )}

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

        {!analysis && <div className="text-slate-400 text-center py-8">Loading analysis...</div>}
      </div>
    </div>
  );
}