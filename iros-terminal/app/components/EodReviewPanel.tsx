'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchEodCounterfactuals,
  fetchEodDates,
  fetchEodProposals,
  fetchEodScorecards,
  fetchEodSummary,
  fetchEodTimeline,
  reviewEodProposal,
  runEodAnalysis,
  type EodCounterfactual,
  type EodMasterPayload,
  type EodProposalReviewAction,
  type EodStrategyProposal,
  type EodTimelineCandle,
  type EodTimelineEvent,
  type EodTimelinePayload,
  type EodTradeScorecard,
} from '@/lib/market-api';

const DASH = '—';

function fmtNum(v: number | null | undefined, digits = 2, suffix = ''): string {
  if (v == null || Number.isNaN(Number(v))) return DASH;
  return `${Number(v).toFixed(digits)}${suffix}`;
}

function fmtPct(v: number | null | undefined, digits = 2, signed = false): string {
  if (v == null || Number.isNaN(Number(v))) return DASH;
  const n = Number(v);
  const sign = signed && n > 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)}%`;
}

function fmtConf(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return DASH;
  const n = Number(v);
  const pct = n <= 1 ? n * 100 : n;
  return `${pct.toFixed(0)}%`;
}

/** TCA is unavailable when null or MODELED (desk honesty). */
function tcaDisplay(card: EodTradeScorecard): string {
  const tca = card.tca;
  if (tca == null) return DASH;
  if (String(tca.basis || '').toUpperCase() === 'MODELED') return DASH;
  const is = tca.implementation_shortfall_bps;
  if (is == null || Number.isNaN(Number(is))) return DASH;
  return fmtNum(is, 1);
}

function outcomeTone(outcome: string | null | undefined): string {
  const o = String(outcome || '').toUpperCase();
  switch (o) {
    case 'TARGET_HIT':
      return 'desk-pill--ok';
    case 'STOP_HIT':
      return 'desk-pill--danger';
    case 'NO_ENTRY':
      return 'desk-pill--muted';
    case 'TRAILED_EXIT':
      return 'desk-pill--info';
    case 'EOD_SQUAREOFF':
      return 'desk-pill--warn';
    default:
      return 'desk-pill--muted';
  }
}

function pnlClass(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return 'text-slate-500';
  if (Number(v) > 0) return 'text-emerald-600';
  if (Number(v) < 0) return 'text-red-500';
  return 'text-slate-500';
}

function regimeLabel(regime: string | null | undefined): string {
  if (!regime) return DASH;
  return String(regime).replace(/_/g, ' ');
}

function proposalDisabled(status: string): boolean {
  const s = status.toUpperCase();
  return s === 'INSUFFICIENT_SAMPLES' || s === 'APPROVED' || s === 'REJECTED';
}

function timelineCandles(payload: EodTimelinePayload | null): EodTimelineCandle[] {
  if (!payload) return [];
  if (Array.isArray(payload.candles) && payload.candles.length) return payload.candles;
  if (Array.isArray(payload.bars) && payload.bars.length) return payload.bars;
  if (Array.isArray(payload.ticks) && payload.ticks.length) return payload.ticks;
  return [];
}

function candleClose(c: EodTimelineCandle): number | null {
  const v = c.close;
  if (v == null || Number.isNaN(Number(v))) return null;
  return Number(v);
}

function candleTime(c: EodTimelineCandle): string {
  return String(c.ts || c.time || c.timestamp || '');
}

function eventTime(ev: EodTimelineEvent): string {
  return String(ev.ts || ev.time || ev.timestamp || '');
}

/* -------------------------------------------------------------------------- */
/*  KPI tile                                                                   */
/* -------------------------------------------------------------------------- */
function KpiTile({
  label,
  value,
  valueClass,
  hint,
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint?: string;
}) {
  return (
    <div className="desk-metric-tile min-w-0 overflow-hidden">
      <div className="desk-metric-label w-full min-w-0">{label}</div>
      <div className={`desk-metric-value tabular-nums w-full min-w-0 ${valueClass || ''}`}>{value}</div>
      {hint ? <div className="desk-metric-delta text-[9px] text-slate-500 w-full min-w-0">{hint}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Inline SVG 1-min replay                                                    */
/* -------------------------------------------------------------------------- */
function ReplayChart({
  candles,
  events,
  entry,
  stop,
  target,
}: {
  candles: EodTimelineCandle[];
  events: EodTimelineEvent[];
  entry: number | null | undefined;
  stop: number | null | undefined;
  target: number | null | undefined;
}) {
  const closes = candles.map(candleClose).filter((v): v is number => v != null);
  if (closes.length < 2) {
    return (
      <div className="flex min-h-[240px] sm:min-h-[320px] md:min-h-[400px] items-center justify-center text-[11px] text-slate-500">
        No 1-min replay series for this ticker
      </div>
    );
  }

  const levels = [entry, stop, target].filter((v): v is number => v != null && !Number.isNaN(v));
  const ymin = Math.min(...closes, ...levels);
  const ymax = Math.max(...closes, ...levels);
  const pad = (ymax - ymin) * 0.08 || 1;
  const y0 = ymin - pad;
  const y1 = ymax + pad;

  const W = 640;
  const H = 220;
  const L = 44;
  const R = 12;
  const T = 12;
  const B = 28;
  const plotW = W - L - R;
  const plotH = H - T - B;

  const xAt = (i: number) => L + (i / Math.max(closes.length - 1, 1)) * plotW;
  const yAt = (p: number) => T + ((y1 - p) / (y1 - y0)) * plotH;

  const path = closes
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i).toFixed(1)} ${yAt(p).toFixed(1)}`)
    .join(' ');

  const levelLine = (price: number | null | undefined, color: string, label: string) => {
    if (price == null || Number.isNaN(Number(price))) return null;
    const y = yAt(Number(price));
    return (
      <g key={label}>
        <line x1={L} y1={y} x2={W - R} y2={y} stroke={color} strokeWidth={1} strokeDasharray="4 3" opacity={0.85} />
        <text x={W - R - 2} y={y - 3} textAnchor="end" fontSize={9} fill={color}>
          {label} {Number(price).toFixed(2)}
        </text>
      </g>
    );
  };

  const eventMarkers = events
    .map((ev, idx) => {
      const price = ev.price;
      const t = eventTime(ev);
      if (price == null || Number.isNaN(Number(price))) return null;
      let i = -1;
      if (t) {
        i = candles.findIndex((c) => candleTime(c).startsWith(t.slice(0, 16)) || candleTime(c) === t);
      }
      if (i < 0) {
        // fall back: nearest close
        let best = 0;
        let bestDiff = Infinity;
        closes.forEach((c, ci) => {
          const d = Math.abs(c - Number(price));
          if (d < bestDiff) {
            bestDiff = d;
            best = ci;
          }
        });
        i = best;
      }
      const typ = String(ev.type || ev.event || ev.label || 'EVT').toUpperCase();
      let fill = 'var(--terminal-cyan)';
      if (typ.includes('STOP')) fill = 'var(--terminal-red)';
      else if (typ.includes('TARGET')) fill = 'var(--terminal-green)';
      else if (typ.includes('ENTRY') || typ.includes('TRIGGER')) fill = 'var(--terminal-amber)';
      return (
        <g key={`ev-${idx}`}>
          <circle cx={xAt(i)} cy={yAt(Number(price))} r={3.5} fill={fill} stroke="#0f1c2e" strokeWidth={1} />
          <title>{`${typ} @ ${Number(price).toFixed(2)} ${t}`}</title>
        </g>
      );
    })
    .filter(Boolean);

  const firstT = candleTime(candles[0]) || '';
  const lastT = candleTime(candles[candles.length - 1]) || '';

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="1-minute replay">
      <rect x={0} y={0} width={W} height={H} fill="transparent" />
      <line x1={L} y1={T} x2={L} y2={H - B} stroke="var(--terminal-line)" strokeWidth={1} />
      <line x1={L} y1={H - B} x2={W - R} y2={H - B} stroke="var(--terminal-line)" strokeWidth={1} />
      <path
        className="eod-replay-path"
        d={path}
        fill="none"
        stroke="var(--terminal-cyan)"
        strokeWidth={1.6}
      />
      {levelLine(entry, 'var(--terminal-amber)', 'ENTRY')}
      {levelLine(stop, 'var(--terminal-red)', 'STOP')}
      {levelLine(target, 'var(--terminal-green)', 'TGT')}
      {eventMarkers}
      <text x={L} y={H - 8} fontSize={9} fill="var(--fg-muted)">
        {firstT.slice(11, 16) || firstT.slice(-5) || DASH}
      </text>
      <text x={W - R} y={H - 8} textAnchor="end" fontSize={9} fill="var(--fg-muted)">
        {lastT.slice(11, 16) || lastT.slice(-5) || DASH}
      </text>
      <text x={4} y={yAt(y1) + 3} fontSize={8} fill="var(--fg-muted)">
        {y1.toFixed(1)}
      </text>
      <text x={4} y={yAt(y0) + 3} fontSize={8} fill="var(--fg-muted)">
        {y0.toFixed(1)}
      </text>
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/*  Counterfactual bars                                                        */
/* -------------------------------------------------------------------------- */
function CounterfactualBars({ rows }: { rows: EodCounterfactual[] }) {
  if (!rows.length) {
    return <div className="text-[11px] text-slate-500 py-3">No counterfactual scenarios</div>;
  }
  const deltas = rows.map((r) => Number(r.pnl_delta_vs_actual_pct ?? r.simulated_pnl_pct ?? 0));
  const maxAbs = Math.max(0.01, ...deltas.map((d) => Math.abs(d)));

  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const delta = row.pnl_delta_vs_actual_pct;
        const pnl = row.simulated_pnl_pct;
        const barVal = delta ?? pnl;
        const widthPct =
          barVal == null || Number.isNaN(Number(barVal))
            ? 0
            : (Math.abs(Number(barVal)) / maxAbs) * 100;
        const positive = barVal != null && Number(barVal) >= 0;
        return (
          <div key={row.scenario_name} className="grid grid-cols-[1fr_100px_72px] gap-2 items-center text-[10px]">
            <div className="min-w-0 truncate font-semibold text-slate-700" title={row.scenario_name}>
              {row.scenario_name}
            </div>
            <div className="h-2 rounded bg-slate-100 overflow-hidden">
              <div
                className={`eod-cf-bar h-full rounded ${positive ? 'bg-emerald-500/80' : 'bg-red-400/80'}`}
                style={{ width: `${Math.min(100, widthPct)}%` }}
              />
            </div>
            <div className={`tabular-nums text-right font-bold ${pnlClass(barVal)}`}>
              {fmtPct(barVal, 2, true)}
            </div>
          </div>
        );
      })}
      <div className="text-[9px] text-slate-500">Δ vs actual (or simulated PnL % when delta missing)</div>
    </div>
  );
}

export type EodReviewPanelProps = {
  embedded?: boolean;
  date?: string;
  onDateChange?: (date: string) => void;
  refreshToken?: number;
};

/* -------------------------------------------------------------------------- */
/*  Main panel                                                                 */
/* -------------------------------------------------------------------------- */
export default function EodReviewPanel({
  embedded = false,
  date: controlledDate,
  onDateChange,
  refreshToken = 0,
}: EodReviewPanelProps = {}) {
  const [dates, setDates] = useState<string[]>([]);
  const [localDate, setLocalDate] = useState('');
  const dateStr = controlledDate ?? localDate;
  const setDateStr = (v: string) => {
    onDateChange?.(v);
    if (controlledDate === undefined) setLocalDate(v);
  };
  const [summary, setSummary] = useState<EodMasterPayload | null>(null);
  const [scorecards, setScorecards] = useState<EodTradeScorecard[]>([]);
  const [proposals, setProposals] = useState<EodStrategyProposal[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<EodTimelinePayload | null>(null);
  const [counterfactuals, setCounterfactuals] = useState<EodCounterfactual[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewBusy, setReviewBusy] = useState<string | null>(null);
  const [runBusy, setRunBusy] = useState(false);

  const selected = useMemo(
    () => scorecards.find((c) => c.trade_id === selectedId) ?? null,
    [scorecards, selectedId]
  );

  const loadDates = useCallback(async () => {
    try {
      const list = await fetchEodDates();
      const sorted = [...list].sort((a, b) => b.localeCompare(a));
      setDates(sorted);
      if (controlledDate === undefined) {
        setLocalDate((prev) => prev || sorted[0] || new Date().toISOString().slice(0, 10));
      }
    } catch {
      setDates([]);
      if (controlledDate === undefined) {
        setLocalDate((prev) => prev || new Date().toISOString().slice(0, 10));
      }
    }
  }, [controlledDate]);

  const loadDay = useCallback(async (date: string) => {
    if (!date) return;
    setLoading(true);
    setError(null);
    try {
      const [sum, cards, props] = await Promise.all([
        fetchEodSummary(date).catch((err: Error) => {
          throw err;
        }),
        fetchEodScorecards(date).catch(() => [] as EodTradeScorecard[]),
        fetchEodProposals(date).catch(() => [] as EodStrategyProposal[]),
      ]);
      setSummary(sum);
      const mergedCards =
        cards.length > 0 ? cards : Array.isArray(sum.scorecards) ? sum.scorecards : [];
      const mergedProps =
        props.length > 0
          ? props
          : Array.isArray(sum.learning_proposals)
            ? sum.learning_proposals
            : [];
      setScorecards(mergedCards);
      setProposals(mergedProps);
      setSelectedId((prev) => {
        if (prev && mergedCards.some((c) => c.trade_id === prev)) return prev;
        return mergedCards[0]?.trade_id ?? null;
      });
    } catch (err) {
      setSummary(null);
      setScorecards([]);
      setProposals([]);
      setSelectedId(null);
      setTimeline(null);
      setCounterfactuals([]);
      setError(err instanceof Error ? err.message : 'Failed to load EOD review');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDates();
  }, [loadDates]);

  useEffect(() => {
    if (dateStr) void loadDay(dateStr);
  }, [dateStr, loadDay, refreshToken]);

  useEffect(() => {
    if (!dateStr || !selected) {
      setTimeline(null);
      setCounterfactuals([]);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void (async () => {
      try {
        const [tl, cf] = await Promise.all([
          fetchEodTimeline(dateStr, selected.ticker).catch(() => null),
          fetchEodCounterfactuals(dateStr, selected.trade_id).catch(() => [] as EodCounterfactual[]),
        ]);
        if (cancelled) return;
        setTimeline(tl);
        const fromEndpoint = cf.length > 0 ? cf : selected.counterfactuals || [];
        setCounterfactuals(fromEndpoint);
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dateStr, selected]);

  const onReview = async (proposalId: string, action: EodProposalReviewAction) => {
    if (!dateStr) return;
    setReviewBusy(proposalId);
    try {
      await reviewEodProposal(dateStr, proposalId, action);
      const refreshed = await fetchEodProposals(dateStr).catch(() => null);
      if (refreshed) setProposals(refreshed);
      else {
        setProposals((prev) =>
          prev.map((p) =>
            p.proposal_id === proposalId
              ? { ...p, status: action === 'APPROVE' ? 'APPROVED' : 'REJECTED' }
              : p
          )
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Review failed');
    } finally {
      setReviewBusy(null);
    }
  };

  const onRun = async () => {
    if (!dateStr) return;
    setRunBusy(true);
    setError(null);
    try {
      await runEodAnalysis(dateStr);
      await loadDates();
      await loadDay(dateStr);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'EOD run failed');
    } finally {
      setRunBusy(false);
    }
  };

  const exec = summary?.executive_summary;
  const commentary = summary?.pm_commentary;
  const candles = timelineCandles(timeline);
  const events: EodTimelineEvent[] =
    (Array.isArray(timeline?.events) && timeline.events.length > 0
      ? timeline.events
      : selected?.timeline_events) || [];

  return (
    <div className={`space-y-3 ${embedded ? 'eod-forensic-surface' : 'desk-panel-enter'}`}>
      {!embedded && (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-3 shadow-sm relative overflow-hidden">
        <div
          className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-teal-400 via-cyan-400 to-transparent pointer-events-none"
          aria-hidden
        />
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="desk-panel-title text-slate-900">EOD INSTITUTIONAL REVIEW</div>
            <div className="text-[10px] text-slate-500 mt-0.5">
              Post-close scorecards · replay · learning proposals
              {summary?.status ? ` · ${summary.status}` : ''}
              {summary?.generated_at ? ` · generated ${summary.generated_at}` : ''}
            </div>
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Date</span>
            {dates.length > 0 ? (
              <select
                value={dateStr}
                onChange={(e) => setDateStr(e.target.value)}
                className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
              >
                {dates.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="date"
                value={dateStr}
                onChange={(e) => setDateStr(e.target.value)}
                className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
              />
            )}
            <button
              type="button"
              onClick={() => void loadDay(dateStr)}
              disabled={loading || !dateStr}
              className="desk-btn-ghost px-3 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => void onRun()}
              disabled={runBusy || !dateStr}
              className="desk-btn-primary px-3 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
            >
              {runBusy ? 'Running…' : 'Run EOD'}
            </button>
          </div>
        </div>
      </div>
      )}

      {embedded && summary && (
        <div className="eod-desk__meta text-[10px] text-slate-500 px-0.5">
          {summary.status ? `${summary.status}` : ''}
          {summary.generated_at ? ` · generated ${summary.generated_at}` : ''}
        </div>
      )}

      {error && (
        <div className="desk-banner-warn p-2 rounded-lg text-[11px]">{error}</div>
      )}

      {loading && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-6 text-center text-[11px] text-slate-400 shadow-sm">
          Loading EOD review…
        </div>
      )}

      {!loading && !summary && !error && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-6 text-center text-[11px] text-slate-400 shadow-sm">
          No EOD artifacts for {dateStr || DASH}. Run the engine or pick another date.
        </div>
      )}

      {!loading && summary && (
        <>
          {/* KPI strip */}
          <div className="desk-metric-grid eod-kpi-strip grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-2">
            <KpiTile
              label="Overall Score"
              value={
                exec?.overall_institutional_score != null
                  ? `${fmtNum(exec.overall_institutional_score, 1)} / 10`
                  : DASH
              }
            />
            <KpiTile label="Win Rate" value={fmtPct(exec?.win_rate_pct)} />
            <KpiTile
              label="Net Return"
              value={fmtPct(exec?.net_strategy_return_pct, 2, true)}
              valueClass={pnlClass(exec?.net_strategy_return_pct)}
            />
            <KpiTile
              label="Avg R:R"
              value={
                exec?.average_risk_reward != null
                  ? `${fmtNum(exec.average_risk_reward, 2)}x`
                  : DASH
              }
            />
            <KpiTile label="Cap Efficiency" value={fmtPct(exec?.capital_efficiency_pct)} />
            <KpiTile
              label="Calibration ECE"
              value={fmtNum(exec?.expected_calibration_error, 3)}
              hint={
                exec?.brier_score != null ? `Brier ${fmtNum(exec.brier_score, 3)}` : 'FACTOR_SCORE conf'
              }
            />
            <KpiTile label="Regime" value={regimeLabel(exec?.market_regime)} />
          </div>

          {/* Panels A + B */}
          <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr] gap-3 eod-dynamic-grid">
            {/* Panel A */}
            <div className="eod-panel-card bg-white/80 border border-slate-200 rounded-xl overflow-hidden shadow-sm">
              <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between gap-2">
                <h3 className="desk-panel-title text-slate-900">Panel A · Scorecards & TCA</h3>
                <span className="desk-pill desk-pill--muted">{scorecards.length} trades</span>
              </div>
              {scorecards.length === 0 ? (
                <div className="p-6 text-center text-[11px] text-slate-400">No scorecards</div>
              ) : (
                <div className="overflow-x-auto desk-scroll-x max-h-[420px] overflow-y-auto">
                  <table className="w-full text-[10px]">
                    <thead className="sticky top-0 bg-slate-50 text-slate-500 uppercase tracking-wider">
                      <tr>
                        <th className="text-left px-2 py-2 font-bold">Ticker</th>
                        <th className="text-left px-2 py-2 font-bold">Side</th>
                        <th className="text-right px-2 py-2 font-bold">Conf</th>
                        <th className="text-left px-2 py-2 font-bold">Outcome</th>
                        <th className="text-right px-2 py-2 font-bold">PnL%</th>
                        <th className="text-right px-2 py-2 font-bold">TCA</th>
                        <th className="text-right px-2 py-2 font-bold">MAE%</th>
                        <th className="text-right px-2 py-2 font-bold">MFE%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scorecards.map((row) => {
                        const active = row.trade_id === selectedId;
                        return (
                          <tr
                            key={row.trade_id}
                            onClick={() => setSelectedId(row.trade_id)}
                            className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${
                              active ? 'bg-cyan-50/60' : ''
                            }`}
                          >
                            <td className="px-2 py-1.5 font-bold text-slate-900">{row.ticker}</td>
                            <td className="px-2 py-1.5">{row.direction || DASH}</td>
                            <td
                              className="px-2 py-1.5 text-right tabular-nums"
                              title={row.confidence_basis || 'FACTOR_SCORE'}
                            >
                              {fmtConf(row.confidence_score)}
                            </td>
                            <td className="px-2 py-1.5">
                              <span className={`desk-pill ${outcomeTone(row.outcome)}`}>
                                {row.outcome || DASH}
                              </span>
                            </td>
                            <td className={`px-2 py-1.5 text-right tabular-nums font-semibold ${pnlClass(row.realized_pnl_pct)}`}>
                              {fmtPct(row.realized_pnl_pct, 2, true)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-500" title="MODELED/null → —">
                              {tcaDisplay(row)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums">
                              {fmtNum(row.efficiency?.mae_pct)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums">
                              {fmtNum(row.efficiency?.mfe_pct)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Panel B */}
            <div className="eod-panel-card bg-white/80 border border-slate-200 rounded-xl overflow-hidden shadow-sm" style={{ animationDelay: '80ms' }}>
              <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between gap-2">
                <h3 className="desk-panel-title text-slate-900">Panel B · Replay & Counterfactual</h3>
                <span className="text-[10px] font-bold text-slate-600">
                  {selected ? selected.ticker : DASH}
                </span>
              </div>
              <div className="p-3 space-y-3">
                {!selected ? (
                  <div className="text-[11px] text-slate-500 py-8 text-center">Select a scorecard row</div>
                ) : detailLoading ? (
                  <div className="text-[11px] text-slate-400 py-8 text-center">Loading replay…</div>
                ) : (
                  <>
                    <ReplayChart
                      candles={candles}
                      events={events}
                      entry={selected.entry_price}
                      stop={selected.stop_loss}
                      target={selected.target_price}
                    />
                    <div>
                      <div className="text-[9px] uppercase tracking-wider font-bold text-slate-500 mb-2">
                        Exit model Δ
                      </div>
                      <CounterfactualBars rows={counterfactuals} />
                    </div>
                    {(selected.success_factors?.length || selected.failure_factors?.length) ? (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px]">
                        <div>
                          <div className="font-bold text-emerald-700 mb-1">Success factors</div>
                          <ul className="list-disc pl-4 text-slate-600 space-y-0.5">
                            {(selected.success_factors || []).map((f) => (
                              <li key={f}>{f}</li>
                            ))}
                            {!selected.success_factors?.length && <li className="list-none text-slate-400">{DASH}</li>}
                          </ul>
                        </div>
                        <div>
                          <div className="font-bold text-red-600 mb-1">Failure factors</div>
                          <ul className="list-disc pl-4 text-slate-600 space-y-0.5">
                            {(selected.failure_factors || []).map((f) => (
                              <li key={f}>{f}</li>
                            ))}
                            {!selected.failure_factors?.length && <li className="list-none text-slate-400">{DASH}</li>}
                          </ul>
                        </div>
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Panel C */}
          <div className="eod-panel-card bg-white/80 border border-slate-200 rounded-xl overflow-hidden shadow-sm" style={{ animationDelay: '140ms' }}>
            <div className="px-3 py-2 border-b border-slate-200">
              <h3 className="desk-panel-title text-slate-900">Panel C · Proposals & PM Commentary</h3>
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-0 divide-y xl:divide-y-0 xl:divide-x divide-slate-200">
              <div className="p-3 space-y-2">
                <div className="text-[9px] uppercase tracking-wider font-bold text-slate-500">
                  Learning proposals
                </div>
                {proposals.length === 0 ? (
                  <div className="text-[11px] text-slate-400 py-4">No proposals for this date</div>
                ) : (
                  proposals.map((p) => {
                    const insufficient = String(p.status).toUpperCase() === 'INSUFFICIENT_SAMPLES';
                    const disabled = proposalDisabled(String(p.status)) || reviewBusy === p.proposal_id;
                    return (
                      <div
                        key={p.proposal_id}
                        className={`rounded-lg border border-slate-200 p-2.5 ${
                          insufficient ? 'opacity-50 grayscale' : ''
                        }`}
                      >
                        <div className="flex flex-wrap items-start gap-2 justify-between">
                          <div className="min-w-0">
                            <div className="text-[11px] font-bold text-slate-900">
                              {p.parameter_name}
                            </div>
                            <div className="text-[10px] text-slate-600 mt-0.5">
                              {p.current_value ?? DASH} → {p.proposed_value ?? DASH}
                              {p.expected_pnl_uplift_pct != null
                                ? ` · uplift ${fmtPct(p.expected_pnl_uplift_pct, 1, true)}`
                                : ''}
                              {p.confidence_interval ? ` · CI ${p.confidence_interval}` : ''}
                            </div>
                          </div>
                          <span
                            className={`desk-pill ${
                              String(p.status).toUpperCase() === 'APPROVED'
                                ? 'desk-pill--ok'
                                : String(p.status).toUpperCase() === 'REJECTED'
                                  ? 'desk-pill--danger'
                                  : insufficient
                                    ? 'desk-pill--muted'
                                    : 'desk-pill--warn'
                            }`}
                          >
                            {p.status}
                          </span>
                        </div>
                        {String(p.status).toUpperCase() === 'PENDING_REVIEW' && (
                          <div className="flex gap-2 mt-2">
                            <button
                              type="button"
                              disabled={disabled}
                              onClick={() => void onReview(p.proposal_id, 'APPROVE')}
                              className="desk-btn-primary px-2.5 py-1 rounded-md text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              disabled={disabled}
                              onClick={() => void onReview(p.proposal_id, 'REJECT')}
                              className="desk-btn-ghost px-2.5 py-1 rounded-md text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
                            >
                              Reject
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>

              <div className="p-3 space-y-3">
                <div className="text-[9px] uppercase tracking-wider font-bold text-slate-500">
                  PM commentary
                </div>
                {!commentary ||
                (!commentary.executive_summary &&
                  !commentary.attribution_narrative &&
                  !commentary.execution_and_slippage_review &&
                  !(commentary.actionable_directives || []).length) ? (
                  <div className="text-[11px] text-slate-400 py-4">No PM commentary</div>
                ) : (
                  <>
                    {commentary.executive_summary && (
                      <section>
                        <div className="text-[10px] font-bold text-slate-700 mb-1">Executive summary</div>
                        <p className="text-[11px] text-slate-600 leading-relaxed whitespace-pre-wrap">
                          {commentary.executive_summary}
                        </p>
                      </section>
                    )}
                    {commentary.attribution_narrative && (
                      <section>
                        <div className="text-[10px] font-bold text-slate-700 mb-1">Attribution</div>
                        <p className="text-[11px] text-slate-600 leading-relaxed whitespace-pre-wrap">
                          {commentary.attribution_narrative}
                        </p>
                      </section>
                    )}
                    {commentary.execution_and_slippage_review && (
                      <section>
                        <div className="text-[10px] font-bold text-slate-700 mb-1">
                          Execution & slippage
                        </div>
                        <p className="text-[11px] text-slate-600 leading-relaxed whitespace-pre-wrap">
                          {commentary.execution_and_slippage_review}
                        </p>
                      </section>
                    )}
                    {(commentary.actionable_directives || []).length > 0 && (
                      <section>
                        <div className="text-[10px] font-bold text-slate-700 mb-1">
                          Actionable directives
                        </div>
                        <ul className="list-disc pl-4 text-[11px] text-slate-600 space-y-1">
                          {(commentary.actionable_directives || []).map((d) => (
                            <li key={d}>{d}</li>
                          ))}
                        </ul>
                      </section>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
