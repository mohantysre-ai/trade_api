import React, { useMemo, useState, useEffect, useRef } from "react";
import { motion, useReducedMotion } from "motion/react";
import { LiveTickNumber } from "@/lib/desk-motion";
import { deskTransition } from "@/lib/motion-tokens";
import type { DeskIcSummary } from "@/lib/market-api";

type CriterionStatus = "PASS" | "FAIL" | "INSUFFICIENT";

type DeskIcCriterion = {
  id: string;
  label: string;
  status: CriterionStatus;
  detail: string;
  sourceFields?: string[];
};

type DeskIcPayload = {
  ticker?: string;
  deskDecision?: "APPROVE" | "REJECT" | "HOLD_FOR_DATA" | string;
  conviction?: number | null;
  oneLiner?: string | null;
  criteria?: DeskIcCriterion[] | unknown[];
  categoryScores?: {
    liquidity?: number;
    technical?: number;
    governance?: number;
    eventRisk?: number;
    portfolioFit?: number;
  };
  source?: string;
  llmUsed?: boolean;
  generatedAt?: string;
};

type ConfidenceCheckerPanelProps = {
  ticker?: string;
  companyName?: string;
  initialDeskIc?: (DeskIcSummary & {
    criteria?: unknown[];
    categoryScores?: Record<string, number>;
    llmUsed?: boolean;
    generatedAt?: string;
  }) | null;
};

const DESK_IC_FAST_MS = 15_000;
const DESK_IC_LLM_MS = 45_000;

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return true;
  return err instanceof Error && (err.name === "AbortError" || /aborted/i.test(err.message));
}

function deskAbortMessage(signal: AbortSignal, fallback: string): string {
  const reason = signal.reason;
  if (typeof reason === "string" && reason.trim() && !/without reason/i.test(reason)) {
    return reason;
  }
  if (reason instanceof Error && reason.message && !/without reason/i.test(reason.message)) {
    return reason.message;
  }
  return fallback;
}

function ConfidenceGauge({ score }: { score: number }) {
  const reduce = useReducedMotion();
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 80 ? "#22c55e" : score >= 60 ? "#E2A33D" : score >= 40 ? "#3b82f6" : "#ef4444";

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-[130px] h-[130px]">
        <svg width="130" height="130" className="transform -rotate-90 absolute inset-0">
          <circle cx="65" cy="65" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="8" />
          <motion.circle
            cx="65"
            cy="65"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={false}
            animate={{ strokeDashoffset: offset }}
            transition={deskTransition("gauge", reduce)}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span style={{ color }}>
            <LiveTickNumber value={score.toFixed(0)} className="text-3xl font-black leading-none" />
          </span>
          <span className="text-[9px] uppercase tracking-wider text-slate-400 mt-1">Conviction</span>
        </div>
      </div>
    </div>
  );
}

function CriterionRow({ label, status, detail }: { label: string; status: CriterionStatus; detail: string }) {
  const tone =
    status === "PASS"
      ? { ring: "bg-emerald-100 text-emerald-600", text: "text-emerald-700", badge: "bg-emerald-100 text-emerald-600" }
      : status === "FAIL"
        ? { ring: "bg-red-100 text-red-500", text: "text-red-700", badge: "bg-red-100 text-red-500" }
        : { ring: "bg-slate-100 text-slate-500", text: "text-slate-600", badge: "bg-slate-100 text-slate-500" };

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-slate-100 last:border-0">
      <div className={`mt-0.5 w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${tone.ring}`}>
        {status === "PASS" ? (
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none">
            <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : status === "FAIL" ? (
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none">
            <path d="M6 18L18 6M6 6l12 12" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <span className="text-[9px] font-black">—</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-bold ${tone.text}`}>{label}</span>
          <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${tone.badge}`}>{status}</span>
        </div>
        <p className="text-[10px] text-slate-500 mt-0.5 leading-relaxed">{detail || "—"}</p>
      </div>
    </div>
  );
}

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
        <span className="text-[10px] font-black" style={{ color }}>
          {pct.toFixed(0)}%
        </span>
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

function EmptyState() {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(20,184,166,0.12),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(99,102,241,0.10),transparent_36%)]" />
      <div className="relative flex min-h-[240px] sm:min-h-[320px] md:min-h-[360px] flex-col items-center justify-center p-8 text-center">
        <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl confidence-icon">
          <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none">
            <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h3 className="text-sm font-black uppercase tracking-wider text-slate-900">Confidence Checker</h3>
        <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">
          Select a stock from the Swing Portfolio / Asset Matrix to load Desk IC criteria.
        </p>
      </div>
    </div>
  );
}

const CATEGORY_META: { key: keyof NonNullable<DeskIcPayload["categoryScores"]>; label: string; color: string }[] = [
  { key: "liquidity", label: "Liquidity", color: "#f59e0b" },
  { key: "technical", label: "Technical", color: "#3b82f6" },
  { key: "governance", label: "Governance", color: "#06b6d4" },
  { key: "eventRisk", label: "Event risk", color: "#ef4444" },
  { key: "portfolioFit", label: "Portfolio fit", color: "#22c55e" },
];

export default function ConfidenceCheckerPanel({ ticker, companyName, initialDeskIc }: ConfidenceCheckerPanelProps) {
  const normalizedTicker = ticker?.trim().toUpperCase();
  const [activeView, setActiveView] = useState<"widget" | "dashboard">("dashboard");
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  const [loadingDashboard, setLoadingDashboard] = useState(false);
  const [enrichingLlm, setEnrichingLlm] = useState(false);
  const [deskIc, setDeskIc] = useState<DeskIcPayload | null>(initialDeskIc ?? null);
  const [deskError, setDeskError] = useState<string | null>(null);
  const initialDeskIcRef = useRef(initialDeskIc);
  initialDeskIcRef.current = initialDeskIc;

  useEffect(() => {
    setDeskIc(initialDeskIcRef.current ?? null);
    setDeskError(null);
  }, [normalizedTicker]);

  useEffect(() => {
    if (initialDeskIc) setDeskIc(initialDeskIc);
  }, [normalizedTicker, initialDeskIc?.generatedAt, initialDeskIc?.deskDecision]);

  useEffect(() => {
    if (activeView !== "dashboard" || !normalizedTicker) return;
    let cancelled = false;
    const fastController = new AbortController();
    const llmController = new AbortController();
    const fastTimer = window.setTimeout(
      () => fastController.abort("Desk IC snapshot timed out"),
      DESK_IC_FAST_MS,
    );
    const llmTimer = window.setTimeout(
      () => llmController.abort("Desk IC LLM timed out"),
      DESK_IC_LLM_MS,
    );

    const loadDeskIc = async () => {
      const hasCached = Boolean(initialDeskIcRef.current);
      setDeskError(null);
      if (!hasCached) setLoadingDashboard(true);

      try {
        const fastRes = await fetch(`/api/desk-ic?ticker=${encodeURIComponent(normalizedTicker)}&fast=1`, {
          cache: "no-store",
          signal: fastController.signal,
        });
        const fastData = await fastRes.json();
        if (cancelled) return;
        if (fastRes.ok && fastData?.deskIc) {
          const next = fastData.deskIc as DeskIcPayload;
          setDeskIc(next);
          if (next.llmUsed) return;
        } else if (!hasCached) {
          setDeskError(String(fastData?.error || fastData?.detail || `Desk IC unavailable (${fastRes.status})`));
        }
      } catch (err) {
        if (cancelled) return;
        if (isAbortError(err)) {
          if (!hasCached && fastController.signal.reason !== "unmount") {
            setDeskError(deskAbortMessage(fastController.signal, "Desk IC snapshot timed out"));
          }
        } else if (!hasCached) {
          setDeskError(err instanceof Error ? err.message : "Desk IC fetch failed");
        }
      } finally {
        if (!cancelled) setLoadingDashboard(false);
      }

      if (cancelled) return;

      setEnrichingLlm(true);
      try {
        const llmRes = await fetch(`/api/desk-ic?ticker=${encodeURIComponent(normalizedTicker)}`, {
          cache: "no-store",
          signal: llmController.signal,
        });
        const llmData = await llmRes.json();
        if (cancelled) return;
        if (llmRes.ok && llmData?.deskIc) {
          setDeskIc(llmData.deskIc as DeskIcPayload);
        }
      } catch (err) {
        if (cancelled || isAbortError(err)) return;
      } finally {
        if (!cancelled) setEnrichingLlm(false);
      }
    };

    void loadDeskIc();
    return () => {
      cancelled = true;
      fastController.abort("unmount");
      llmController.abort("unmount");
      window.clearTimeout(fastTimer);
      window.clearTimeout(llmTimer);
    };
  }, [activeView, normalizedTicker]);

  const widgetUrl = useMemo(() => {
    if (!normalizedTicker) return "";
    return `https://trendlyne.com/web-widget/checklist-widget/Poppins/${encodeURIComponent(normalizedTicker)}`;
  }, [normalizedTicker]);

  if (!normalizedTicker) return <EmptyState />;

  const criteria = (deskIc?.criteria ?? []) as DeskIcCriterion[];
  const decision = String(deskIc?.deskDecision || "").toUpperCase();
  const passCount = criteria.filter((c) => c.status === "PASS").length;
  const totalCriteria = criteria.length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 bg-slate-100 rounded-xl p-1">
        <button
          onClick={() => setActiveView("dashboard")}
          className={`flex-1 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all ${
            activeView === "dashboard" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
          }`}
        >
          Desk IC
        </button>
        <button
          onClick={() => setActiveView("widget")}
          className={`flex-1 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all ${
            activeView === "widget" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
          }`}
        >
          Trendlyne Widget
        </button>
      </div>

      {activeView === "widget" && (
        <div className="relative w-full overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_10%,rgba(20,184,166,0.16),transparent_34%),radial-gradient(circle_at_85%_20%,rgba(99,102,241,0.12),transparent_32%),radial-gradient(circle_at_50%_100%,rgba(245,158,11,0.10),transparent_38%)]" />
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-400 via-teal-400 to-indigo-500" />
          <div className="relative p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <div className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl confidence-icon">
                  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none">
                    <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
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
              </a>
            </div>
            <div className="relative w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-inner">
              {!loaded && !errored && (
                <div className="flex flex-col items-center justify-center gap-4 bg-white min-h-[240px] sm:min-h-[320px] md:min-h-[400px]">
                  <p className="text-xs font-black uppercase tracking-[0.3em] text-emerald-600">Loading checklist</p>
                </div>
              )}
              {errored && (
                <div className="relative z-10 flex flex-col items-center justify-center gap-3 p-6 text-center min-h-[240px]">
                  <p className="text-xs font-bold uppercase tracking-wider text-amber-700">Widget Unavailable</p>
                  <a href={widgetUrl} target="_blank" rel="noopener noreferrer" className="rounded-full bg-amber-500 px-4 py-2 text-[11px] font-black text-white">
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
                className="min-h-[240px] sm:min-h-[320px] md:min-h-[400px] h-[min(70dvh,500px)] md:h-[500px] w-full bg-white"
              />
            </div>
          </div>
        </div>
      )}

      {activeView === "dashboard" && (
        <div className="space-y-3">
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] font-semibold leading-relaxed text-slate-700">
            DESK IC · {deskIc?.llmUsed ? "LLM" : deskIc ? "DETERMINISTIC" : loadingDashboard ? "LOADING" : deskError ? "FAILED" : "—"} — fact-grounded criteria only. Soft gate:
            REJECT flags the name; quant floors still control lock eligibility. Missing fields show INSUFFICIENT — never invented PASS.
            {enrichingLlm && (
              <span className="ml-1 text-amber-700">· LLM enrichment running (partial shown)</span>
            )}
          </div>

          {loadingDashboard && !deskIc && (
            <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-xs text-slate-500">
              Running Desk IC for {normalizedTicker}…
            </div>
          )}

          {!loadingDashboard && deskError && !deskIc && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-[11px] text-amber-900">
              {deskError}
            </div>
          )}

          {!loadingDashboard && deskIc && (
            <>
              <div className="rounded-2xl bg-gradient-to-br from-emerald-50 via-white to-teal-50 border border-emerald-200/50 shadow-sm p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2.5">
                    <div className="h-8 w-8 rounded-lg confidence-icon flex items-center justify-center shadow-sm">
                      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none">
                        <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div>
                      <div className="text-sm font-black text-slate-900">{companyName ?? normalizedTicker}</div>
                      <div className="text-[9px] text-slate-500 uppercase tracking-wider">
                        {normalizedTicker} · {decision || "—"}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`text-[9px] uppercase tracking-wider font-bold px-2 py-0.5 rounded border ${
                        decision === "APPROVE"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : decision === "REJECT"
                            ? "bg-red-50 text-red-700 border-red-200"
                            : "bg-amber-50 text-amber-800 border-amber-200"
                      }`}
                    >
                      {decision || "—"}
                    </span>
                  </div>
                </div>
                {deskIc.oneLiner && (
                  <p className="text-[11px] text-slate-600 mb-2 leading-relaxed">{deskIc.oneLiner}</p>
                )}
                <div className="flex justify-center py-1">
                  <ConfidenceGauge score={typeof deskIc.conviction === "number" ? deskIc.conviction : 0} />
                </div>
              </div>

              <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4 space-y-2.5">
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600 mb-2">Category scores</div>
                {CATEGORY_META.map((cat) => (
                  <CategoryBar
                    key={cat.key}
                    label={cat.label}
                    score={Number(deskIc.categoryScores?.[cat.key] ?? 0)}
                    color={cat.color}
                  />
                ))}
              </div>

              <div className="rounded-2xl bg-white border border-slate-200 shadow-sm p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Desk IC criteria</span>
                  <span className="ml-auto text-[9px] text-slate-500 font-semibold">
                    {passCount}/{totalCriteria || "—"} pass
                  </span>
                </div>
                {(deskIc.criteria || []).length === 0 ? (
                  <p className="text-[11px] text-slate-500">— No criteria returned</p>
                ) : (
                  criteria.map((criterion) => (
                    <CriterionRow
                      key={criterion.id}
                      label={criterion.label}
                      status={
                        criterion.status === "PASS" || criterion.status === "FAIL" || criterion.status === "INSUFFICIENT"
                          ? criterion.status
                          : "INSUFFICIENT"
                      }
                      detail={criterion.detail}
                    />
                  ))
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
