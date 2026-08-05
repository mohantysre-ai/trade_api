'use client';

import React, { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  fetchEodDates,
  fetchEodLlmStatus,
  fetchEodSummary,
  runEodAnalysis,
  runEodPmLlmOnce,
  type EodLlmStatus,
  type EodPmCommentary,
} from '@/lib/market-api';
import EodAnalysisPanel from './EodAnalysisPanel';
import EodReviewPanel from './EodReviewPanel';

type EodMode = 'book' | 'forensic' | 'full';

const MODES: { key: EodMode; label: string; hint: string }[] = [
  { key: 'book', label: 'Book P&L', hint: 'Intraday + swing day marks' },
  { key: 'forensic', label: 'Forensic', hint: 'Scorecards · replay · proposals' },
  { key: 'full', label: 'Full Desk', hint: 'Single pane — both layers' },
];

class EodPaneErrorBoundary extends Component<
  { title: string; children: ReactNode },
  { error: string | null }
> {
  state: { error: string | null } = { error: null };

  static getDerivedStateFromError(err: unknown) {
    return { error: err instanceof Error ? err.message : 'Pane failed to render' };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-[11px] text-red-800">
          <div className="font-black uppercase tracking-wider">{this.props.title} failed</div>
          <p className="mt-1 text-red-700">{this.state.error}</p>
          <button
            type="button"
            className="desk-btn-ghost mt-2 rounded-lg px-2 py-1 text-[9px] font-black uppercase"
            onClick={() => this.setState({ error: null })}
          >
            Retry pane
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

/** IST calendar + simple NSE close: weekday Mon–Fri and local minutes > 15:30. */
function getIstMarketState(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(now);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? '';
  const weekday = get('weekday'); // Sun Mon …
  let hour = Number(get('hour'));
  if (hour === 24) hour = 0;
  const minute = Number(get('minute'));
  const today = `${get('year')}-${get('month')}-${get('day')}`;
  const isWeekday = weekday !== 'Sat' && weekday !== 'Sun';
  const mins = hour * 60 + minute;
  const marketClosed = isWeekday && mins > 15 * 60 + 30;
  return { today, marketClosed, isWeekday };
}

const POST_CLOSE_POLL_MS = 45_000;

function PmMemoStrip({
  commentary,
  source,
  onOpenForensic,
}: {
  commentary: EodPmCommentary | null | undefined;
  source?: string | null;
  onOpenForensic: () => void;
}) {
  if (
    !commentary ||
    (!commentary.executive_summary &&
      !commentary.attribution_narrative &&
      !commentary.execution_and_slippage_review &&
      !(commentary.actionable_directives || []).length)
  ) {
    return null;
  }

  const directives = (commentary.actionable_directives || []).slice(0, 4);
  const src = String(source || commentary.source || '—').toUpperCase();

  return (
    <section className="eod-panel-card overflow-hidden rounded-xl border border-slate-300 border-[0.5px] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
        <h3 className="desk-panel-title text-slate-900">PM Memo</h3>
        <span className={`desk-pill ${src === 'LLM' ? 'desk-pill--ok' : 'desk-pill--muted'}`}>
          {src}
        </span>
        <button
          type="button"
          onClick={onOpenForensic}
          className="desk-btn-ghost ml-auto rounded-md px-2 py-1 text-[9px] font-black uppercase tracking-wider"
        >
          Open Forensic →
        </button>
      </div>
      <div className="grid grid-cols-1 gap-0 divide-y divide-slate-100 xl:grid-cols-2 xl:divide-x xl:divide-y-0">
        <div className="space-y-2 p-3">
          {commentary.executive_summary && (
            <div>
              <div className="mb-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-400">
                Executive
              </div>
              <p className="text-[11px] leading-snug text-slate-700 whitespace-pre-wrap">
                {commentary.executive_summary}
              </p>
            </div>
          )}
          {commentary.attribution_narrative && (
            <div>
              <div className="mb-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-400">
                Attribution
              </div>
              <p className="text-[11px] leading-snug text-slate-600 whitespace-pre-wrap">
                {commentary.attribution_narrative}
              </p>
            </div>
          )}
        </div>
        <div className="space-y-2 p-3">
          {commentary.execution_and_slippage_review && (
            <div>
              <div className="mb-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-400">
                Execution
              </div>
              <p className="text-[11px] leading-snug text-slate-600 whitespace-pre-wrap">
                {commentary.execution_and_slippage_review}
              </p>
            </div>
          )}
          {directives.length > 0 && (
            <div>
              <div className="mb-1 text-[9px] font-bold uppercase tracking-wider text-slate-400">
                Directives
              </div>
              <ul className="list-disc space-y-1 pl-4 text-[11px] text-slate-700">
                {directives.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export default function EodDeskPanel({
  refreshToken = 0,
}: {
  /** Bumped by top desk Refresh — reloads Book / LLM status without force. */
  refreshToken?: number;
}) {
  const [mode, setMode] = useState<EodMode>('book');
  const [dates, setDates] = useState<string[]>([]);
  const [dateStr, setDateStr] = useState(() => getIstMarketState().today);
  const [swingDateStr, setSwingDateStr] = useState(() => getIstMarketState().today);
  const [runBusy, setRunBusy] = useState(false);
  const [llmBusy, setLlmBusy] = useState(false);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [forceBookRebuild, setForceBookRebuild] = useState(false);
  const [postCloseAuto, setPostCloseAuto] = useState(false);
  const [llmStatus, setLlmStatus] = useState<EodLlmStatus | null>(null);
  const [pmCommentary, setPmCommentary] = useState<EodPmCommentary | null>(null);
  const forcedForDateRef = useRef<string | null>(null);

  const loadLlmStatus = useCallback(async (date: string) => {
    if (!date) {
      setLlmStatus(null);
      setPmCommentary(null);
      return;
    }
    try {
      const st = await fetchEodLlmStatus(date);
      setLlmStatus(st);
    } catch {
      setLlmStatus({
        date,
        has_artifacts: false,
        llm_done: false,
        llm_available: false,
        pm_source: null,
      });
    }
    try {
      const summary = await fetchEodSummary(date);
      setPmCommentary(summary?.pm_commentary ?? null);
      const source = summary?.pm_commentary?.source ?? null;
      if (String(source || '').toUpperCase() === 'LLM') {
        setLlmStatus((prev) =>
          prev
            ? { ...prev, llm_done: true, llm_available: false, pm_source: source, has_artifacts: true }
            : {
                date,
                has_artifacts: true,
                llm_done: true,
                llm_available: false,
                pm_source: source,
              }
        );
      }
    } catch {
      setPmCommentary(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await fetchEodDates();
        if (cancelled) return;
        const sorted = [...list].sort((a, b) => b.localeCompare(a));
        setDates(sorted);
        if (sorted[0]) setDateStr((prev) => prev || sorted[0]);
      } catch {
        /* keep local date */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void loadLlmStatus(dateStr);
  }, [dateStr, refreshKey, loadLlmStatus]);

  // Top desk Refresh — bump local key so Book / status reload without force rebuild.
  useEffect(() => {
    if (refreshToken > 0) {
      setForceBookRebuild(false);
      setRefreshKey((k) => k + 1);
    }
  }, [refreshToken]);

  // After 15:30 IST on weekdays: one force rebuild, then poll book/forensic every ~45s (no PM LLM).
  useEffect(() => {
    let pollId: number | undefined;

    const stopPoll = () => {
      if (pollId != null) {
        window.clearInterval(pollId);
        pollId = undefined;
      }
    };

    const startPoll = () => {
      if (pollId != null) return;
      pollId = window.setInterval(() => {
        const { today, marketClosed } = getIstMarketState();
        if (!(marketClosed && dateStr === today)) {
          setPostCloseAuto(false);
          stopPoll();
          return;
        }
        // Cache polls only — never force, never PM LLM
        setForceBookRebuild(false);
        setRefreshKey((k) => k + 1);
      }, POST_CLOSE_POLL_MS);
    };

    const evaluate = () => {
      const { today, marketClosed } = getIstMarketState();
      const active = marketClosed && dateStr === today;
      setPostCloseAuto(active);
      if (!active) {
        stopPoll();
        return;
      }
      // Serve cached book immediately. Symbol-mismatch rebuild happens server-side
      // on force=false. Avoid auto force=true (Yahoo marks) — it hung the UI at 20s.
      if (forcedForDateRef.current !== today) {
        forcedForDateRef.current = today;
        setForceBookRebuild(false);
        setRefreshKey((k) => k + 1);
      }
      startPoll();
    };

    evaluate();
    // Detect crossing 15:30 while the desk stays open
    const watchId = window.setInterval(evaluate, 60_000);

    return () => {
      stopPoll();
      window.clearInterval(watchId);
    };
  }, [dateStr]);

  const onRefresh = useCallback(() => {
    // Read-only reload — never triggers LLM
    setRunMsg(null);
    setForceBookRebuild(false);
    setRefreshKey((k) => k + 1);
  }, []);

  const onRun = useCallback(async () => {
    if (!dateStr) return;
    setRunBusy(true);
    setRunMsg(null);
    try {
      // After close (or viewing today), force rebuild so locked INTRADAY/SWING
      // baskets replace any stale morning book cache — never invents picks.
      const { today, marketClosed } = getIstMarketState();
      const force = marketClosed && dateStr === today;
      const result = (await runEodAnalysis(dateStr, { force })) as {
        skipped?: boolean;
        reason?: string;
        llm_used?: boolean;
        status?: string;
      };
      const list = await fetchEodDates().catch(() => [] as string[]);
      const sorted = [...list].sort((a, b) => b.localeCompare(a));
      setDates(sorted);
      setForceBookRebuild(true);
      setRefreshKey((k) => k + 1);
      window.setTimeout(() => setForceBookRebuild(false), 500);
      if (result?.skipped && !force) {
        setRunMsg(`Cached artifacts · ${dateStr} · no LLM`);
      } else {
        setRunMsg(
          `Engine ${result?.status || (force ? 'rebuilt' : 'done')} · ${dateStr} · ${force ? 'force book' : 'deterministic'}`
        );
      }
    } catch (err) {
      setRunMsg(err instanceof Error ? err.message : 'EOD run failed');
    } finally {
      setRunBusy(false);
    }
  }, [dateStr]);

  const onPmLlm = useCallback(async () => {
    if (!dateStr) return;
    setLlmBusy(true);
    setRunMsg(null);
    try {
      const result = await runEodPmLlmOnce(dateStr);
      setRefreshKey((k) => k + 1);
      await loadLlmStatus(dateStr);
      if (result.commentary) {
        setPmCommentary(result.commentary as EodPmCommentary);
      }
      if (result.skipped && result.reason === 'llm_already_cached_for_day') {
        setRunMsg(`PM LLM already cached for ${dateStr} · see PM Memo below`);
        setMode('forensic');
      } else if (result.llm_used) {
        setRunMsg(`PM LLM generated once for ${dateStr} · see PM Memo below`);
        setMode('forensic');
      } else {
        setRunMsg(
          `PM LLM · ${result.reason || 'done'} · source ${result.pm_source || '—'}`
        );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'PM LLM failed';
      setRunMsg(
        msg.includes('404') || /not found/i.test(msg)
          ? 'Backend missing /api/eod/pm-llm — restart Market API (port 8000), then retry'
          : msg
      );
    } finally {
      setLlmBusy(false);
    }
  }, [dateStr, loadLlmStatus]);

  const modeIndex = MODES.findIndex((m) => m.key === mode);
  const llmDone = Boolean(llmStatus?.llm_done);
  const llmAvailable = Boolean(llmStatus?.llm_available) || (!llmDone && Boolean(dateStr));
  const busy = runBusy || llmBusy;

  return (
    <div className="eod-desk space-y-3" data-mode={mode}>
      <header className="eod-desk__chrome relative overflow-hidden rounded-xl border border-slate-300 border-[0.5px] bg-white p-3 shadow-sm">
        <div className="eod-desk__sheen pointer-events-none absolute inset-0" aria-hidden />
        <div className="relative flex flex-wrap items-center gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="eod-desk__live-dot" aria-hidden />
              <h2 className="desk-panel-title text-slate-900 tracking-[0.14em]">EOD DESK</h2>
              {llmDone ? (
                <span className="desk-pill desk-pill--ok" title="PM commentary LLM already stored for this date">
                  PM LLM · CACHED
                </span>
              ) : (
                <span className="desk-pill desk-pill--muted" title="Optional once-per-day LLM for PM commentary">
                  PM LLM · OFF
                </span>
              )}
              {postCloseAuto && (
                <span
                  className="desk-pill desk-pill--info"
                  title="Weekday after 15:30 IST — Book P&L auto-refetches ~45s (no PM LLM)"
                >
                  POST-CLOSE · AUTO
                </span>
              )}
            </div>
            <p className="mt-0.5 text-[10px] text-slate-500">
              {postCloseAuto
                ? 'After close: Book auto-polls ~45s. Rebuild refreshes marks + fills missing outcome narratives (no full LLM reburn). PM LLM never on Refresh.'
                : 'Refresh never calls LLM · Rebuild fills missing narratives · PM LLM at most 1×/day then cache · Rotate locks via Swing/Intraday panels'}
            </p>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Date</span>
              {dates.length > 0 ? (
                <select
                  value={dateStr}
                  onChange={(e) => {
                    const next = e.target.value;
                    setDateStr(next);
                    setSwingDateStr(next);
                  }}
                  className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-teal-300"
                >
                  {[dateStr, ...dates.filter((d) => d !== dateStr)]
                    .filter((d, i, a) => a.indexOf(d) === i)
                    .map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                </select>
              ) : (
                <input
                  type="date"
                  value={dateStr}
                  onChange={(e) => {
                    const next = e.target.value;
                    setDateStr(next);
                    setSwingDateStr(next);
                  }}
                  className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-teal-300"
                />
              )}
            </label>
            {(mode === 'book' || mode === 'full') && (
              <label className="flex items-center gap-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Swing</span>
                <input
                  type="date"
                  value={swingDateStr}
                  onChange={(e) => setSwingDateStr(e.target.value)}
                  className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-teal-300"
                />
              </label>
            )}
            <button
              type="button"
              onClick={onRefresh}
              disabled={busy}
              className="desk-btn-ghost rounded-lg px-3 py-1.5 text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => void onRun()}
              disabled={busy || !dateStr}
              className="desk-btn-ghost rounded-lg px-3 py-1.5 text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
              title="Deterministic engine — no LLM"
            >
              {runBusy ? 'Running…' : 'Run EOD'}
            </button>
            <button
              type="button"
              onClick={() => void onPmLlm()}
              disabled={busy || !dateStr || llmDone}
              className="desk-btn-primary rounded-lg px-3 py-1.5 text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
              title={
                llmDone
                  ? 'Already generated for this date — using cache'
                  : 'Generate PM commentary with LLM once for this date'
              }
            >
              {llmBusy ? 'PM LLM…' : llmDone ? 'PM LLM · DONE' : 'PM LLM · 1×'}
            </button>
          </div>
        </div>

        {runMsg && (
          <div className="eod-desk__toast relative mt-2 text-[11px] text-slate-600">{runMsg}</div>
        )}
        {!llmDone && llmAvailable && (
          <div className="relative mt-1.5 text-[9px] text-slate-400">
            Optional: press <span className="font-bold text-slate-600">PM LLM · 1×</span> once.
            After that, Refresh / Run EOD stay on cache.
          </div>
        )}
        {llmDone && !pmCommentary && (
          <div className="relative mt-1.5 text-[9px] text-amber-600">
            PM LLM marked done but memo not in summary — press Refresh.
          </div>
        )}
      </header>

      {/* Always-visible PM memo (not only Forensic) */}
      <PmMemoStrip
        commentary={pmCommentary}
        source={llmStatus?.pm_source || pmCommentary?.source}
        onOpenForensic={() => setMode('forensic')}
      />

      <div
        className="eod-desk__modes relative grid grid-cols-3 gap-1 rounded-xl border border-slate-200 bg-slate-50/80 p-1"
        role="tablist"
        aria-label="EOD desk modes"
      >
        <div
          className="eod-desk__pill pointer-events-none absolute top-1 bottom-1 left-1 rounded-lg bg-white shadow-sm ring-1 ring-cyan-400/40"
          style={{
            width: 'calc((100% - 0.5rem) / 3)',
            transform: `translateX(calc(${modeIndex} * 100% + ${modeIndex} * 0.25rem))`,
          }}
          aria-hidden
        />
        {MODES.map((m) => {
          const active = mode === m.key;
          return (
            <button
              key={m.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setMode(m.key)}
              className={`eod-desk__mode-btn relative z-[1] rounded-lg px-1.5 sm:px-2 py-2 min-h-11 text-left transition-colors ${
                active ? 'text-slate-900' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <div className="text-[9px] sm:text-[10px] font-black uppercase tracking-[0.12em] truncate">{m.label}</div>
              <div className="mt-0.5 hidden text-[9px] text-slate-400 sm:block">{m.hint}</div>
            </button>
          );
        })}
      </div>

      <div className="eod-desk__stage space-y-3" key={mode}>
        {(mode === 'book' || mode === 'full') && (
          <section
            className="eod-desk__pane eod-desk__pane--book"
            style={{ animationDelay: '0ms' }}
            aria-label="Book P&L"
          >
            {mode === 'full' && (
              <div className="eod-desk__section-label mb-2 flex items-center gap-2">
                <span className="eod-desk__section-index">01</span>
                <span className="desk-panel-title text-teal-800">Book P&L</span>
                <span className="h-px flex-1 bg-gradient-to-r from-teal-300/60 to-transparent" />
              </div>
            )}
            <EodPaneErrorBoundary title="Book P&L">
              <EodAnalysisPanel
                embedded
                date={dateStr}
                swingDate={swingDateStr}
                onDateChange={setDateStr}
                onSwingDateChange={setSwingDateStr}
                refreshToken={refreshKey}
                forceBookRebuild={forceBookRebuild}
              />
            </EodPaneErrorBoundary>
          </section>
        )}

        {(mode === 'forensic' || mode === 'full') && (
          <section
            className="eod-desk__pane eod-desk__pane--forensic"
            style={{ animationDelay: mode === 'full' ? '90ms' : '0ms' }}
            aria-label="Institutional forensics"
          >
            {mode === 'full' && (
              <div className="eod-desk__section-label mb-2 flex items-center gap-2">
                <span className="eod-desk__section-index">02</span>
                <span className="desk-panel-title text-cyan-800">Forensic Review</span>
                <span className="h-px flex-1 bg-gradient-to-r from-cyan-300/60 to-transparent" />
              </div>
            )}
            <EodPaneErrorBoundary title="Forensic Review">
              <EodReviewPanel
                embedded
                date={dateStr}
                onDateChange={setDateStr}
                refreshToken={refreshKey}
              />
            </EodPaneErrorBoundary>
          </section>
        )}
      </div>
    </div>
  );
}
