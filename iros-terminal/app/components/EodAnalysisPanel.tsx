'use client';

import React, { useEffect, useState, useCallback } from 'react';

/* -------------------------------------------------------------------------- */
/*  Types for EOD report responses from the backend                          */
/* -------------------------------------------------------------------------- */

type MissDiagnostic = {
  isMiss: boolean;
  isHit?: boolean;
  exitReason: string;
  rootCause: string | null;
  factors: string[];
  rMultiple: number | null;
  movePct: number | null;
  gapToT1Pct: number | null;
  gapToT2Pct: number | null;
  stopUtilization: number | null;
  plannedRr: number | null;
  riskPerShare: number | null;
  maePct: number | null;
  mfePct: number | null;
  stopEff: number | null;
  falsePositive: boolean;
  holdingMins: number | null;
  source: 'LEVELS' | 'SCORECARD' | string;
  exitSource?: string;
};

type IntradayTrade = {
  symbol: string;
  direction: string;
  entryPrice: number;
  exitPrice: number;
  stopLoss?: number | null;
  target1?: number | null;
  target2?: number | null;
  exitReason: string;
  qty: number;
  deployedCapital: number;
  pnl: number;
  pnlPct: number | null;
  missAnalysis: string | null;
  missDiagnostic?: MissDiagnostic | null;
};

type IntradayReport = {
  date: string;
  capital: number;
  totalDeployed: number;
  totalPnl: number;
  remainingCapital: number;
  hitBreakdown: { T1_HIT: number; T2_HIT: number; SL_HIT: number; EOD_SQUAREOFF: number };
  hitRatePct: number;
  missCount?: number;
  missScorecardCoverage?: number;
  isMock?: boolean;
  fromCache?: boolean;
  cachedAt?: string;
  trades: IntradayTrade[];
};

type SwingPick = {
  symbol: string;
  direction: string;
  entryDate: string | null;
  daysHeld: number | null;
  dayBucket: number | null;
  status: string;
  entryPrice: number;
  refPrice930: number;
  currentPrice: number;
  stopLoss: number;
  target1: number;
  target2: number;
  qty: number;
  deployedCapital: number;
  pnl: number;
  pnlPct: number;
  alertsFired: unknown[];
};

type SwingReport = {
  date: string;
  totalPicks: number;
  totalDeployed: number;
  totalPnl: number;
  totalPnlPct: number | null;
  winCount: number;
  lossCount: number;
  bestPerformer: SwingPick | null;
  worstPerformer: SwingPick | null;
  pnlByDayBucket: Record<string, number>;
  picks: SwingPick[];
  isMock?: boolean;
  referenceDate?: string;
  referenceLabel?: string;
  fromCache?: boolean;
  cachedAt?: string;
};

/* -------------------------------------------------------------------------- */
/*  Helper: color classes for exit reasons                                    */
/* -------------------------------------------------------------------------- */
function exitReasonBadge(reason: string) {
  switch (reason) {
    case 'T2_HIT': return { bg: 'bg-emerald-100', txt: 'text-emerald-800', label: 'T2 ✓' };
    case 'T1_HIT': return { bg: 'bg-emerald-50', txt: 'text-emerald-700', label: 'T1 ✓' };
    case 'SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'SL ✗' };
    case 'EOD_SQUAREOFF': return { bg: 'bg-amber-100', txt: 'text-amber-800', label: 'EOD ∎' };
    default: return { bg: 'bg-slate-100', txt: 'text-slate-600', label: reason };
  }
}

function statusBadge(status: string) {
  switch (status) {
    case 'T2_HIT': return { bg: 'bg-emerald-100', txt: 'text-emerald-800', label: 'T2 ✓' };
    case 'T1_HIT': return { bg: 'bg-emerald-50', txt: 'text-emerald-700', label: 'T1 ✓' };
    case 'SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'SL ✗' };
    case 'NOT_TRIGGERED': return { bg: 'bg-slate-200', txt: 'text-slate-600', label: 'Not Triggered' };
    case 'OPEN': return { bg: 'bg-blue-100', txt: 'text-blue-800', label: 'Open ◇' };
    default: return { bg: 'bg-slate-100', txt: 'text-slate-600', label: status };
  }
}

function fmtMissNum(v: number | null | undefined, digits = 2, suffix = ''): string {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return `${Number(v).toFixed(digits)}${suffix}`;
}

function fmtMissSigned(v: number | null | undefined, digits = 2, suffix = ''): string {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)}${suffix}`;
}

function rootCauseTone(root: string | null | undefined): string {
  const r = String(root || '').toUpperCase();
  switch (r) {
    case 'ADVERSE_TRAJECTORY':
    case 'FAKE_BREAKOUT':
    case 'STOP_BEFORE_FOLLOWTHROUGH':
      return 'desk-pill--danger';
    case 'STALLED_TRADE':
      return 'desk-pill--warn';
    case 'PARTIAL_FOLLOWTHROUGH':
      return 'desk-pill--info';
    default:
      return 'desk-pill--muted';
  }
}

function OutcomeRow({ trade }: { trade: IntradayTrade }) {
  const d = trade.missDiagnostic!;
  const rBad = (d.rMultiple ?? 0) < 0;
  const exitTone =
    trade.exitReason === 'SL_HIT'
      ? 'desk-pill--danger'
      : trade.exitReason === 'EOD_SQUAREOFF'
        ? 'desk-pill--warn'
        : 'desk-pill--ok';
  return (
    <tr className="border-t border-slate-100 hover:bg-slate-50/80">
      <td className="px-2 py-1.5 font-bold text-slate-900">{trade.symbol}</td>
      <td className={`px-2 py-1.5 font-semibold ${trade.direction === 'LONG' ? 'text-emerald-700' : 'text-red-600'}`}>
        {trade.direction}
      </td>
      <td className="px-2 py-1.5">
        <span className={`desk-pill ${exitTone}`}>{trade.exitReason}</span>
      </td>
      <td className={`px-2 py-1.5 text-right tabular-nums font-bold ${rBad ? 'text-red-600' : 'text-emerald-700'}`}>
        {fmtMissSigned(d.rMultiple, 2, 'R')}
      </td>
      <td className={`px-2 py-1.5 text-right tabular-nums ${rBad ? 'text-red-600' : 'text-slate-700'}`}>
        {fmtMissSigned(d.movePct, 2, '%')}
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums text-slate-600">{fmtMissNum(d.maePct, 2)}</td>
      <td className="px-2 py-1.5 text-right tabular-nums text-slate-600">{fmtMissNum(d.mfePct, 2)}</td>
      <td className="px-2 py-1.5">
        <span className={`desk-pill ${rootCauseTone(d.rootCause)}`}>
          {(d.rootCause || '—').replace(/_/g, ' ')}
        </span>
      </td>
      <td className={`px-2 py-1.5 text-right tabular-nums font-bold ${trade.pnl >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
        {Math.abs(trade.pnl) < 1e-6 && trade.pnlPct != null
          ? fmtMissSigned(trade.pnlPct, 2, '%')
          : `${trade.pnl >= 0 ? '+' : ''}₹${trade.pnl.toFixed(0)}`}
      </td>
      <td className="px-2 py-1.5">
        <div className="flex max-w-[220px] flex-wrap gap-1">
          {d.falsePositive && <span className="desk-pill desk-pill--danger">FP</span>}
          {(d.factors || []).slice(0, 3).map((f) => (
            <span key={f} className="desk-pill desk-pill--muted" title={f}>
              {f.replace(/_/g, ' ').slice(0, 18)}
            </span>
          ))}
        </div>
      </td>
      <td className="px-2 py-1.5 font-bold text-slate-500">{d.source === 'SCORECARD' ? 'SC' : 'LVL'}</td>
    </tr>
  );
}

function OutcomeTable({ rows }: { rows: IntradayTrade[] }) {
  return (
    <div className="overflow-x-auto desk-scroll-x">
      <table className="w-full text-[10px]">
        <thead className="sticky top-0 bg-slate-50 text-slate-500 uppercase tracking-wider">
          <tr>
            <th className="px-2 py-2 text-left font-bold">Ticker</th>
            <th className="px-2 py-2 text-left font-bold">Side</th>
            <th className="px-2 py-2 text-left font-bold">Exit</th>
            <th className="px-2 py-2 text-right font-bold">R</th>
            <th className="px-2 py-2 text-right font-bold">Move%</th>
            <th className="px-2 py-2 text-right font-bold">MAE</th>
            <th className="px-2 py-2 text-right font-bold">MFE</th>
            <th className="px-2 py-2 text-left font-bold">Why (root)</th>
            <th className="px-2 py-2 text-right font-bold">P&L</th>
            <th className="px-2 py-2 text-left font-bold">Flags</th>
            <th className="px-2 py-2 text-left font-bold">Src</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((trade) => (
            <OutcomeRow key={`${trade.symbol}-${trade.exitReason}`} trade={trade} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Replaces old Miss Analysis / target-hit prose cards with dense outcome tables. */
function OutcomeDesk({ trades, coverage, isMock }: {
  trades: IntradayTrade[];
  coverage?: number;
  isMock?: boolean;
}) {
  const misses = trades
    .filter((t) => t.missDiagnostic?.isMiss)
    .slice()
    .sort((a, b) => (a.missDiagnostic?.rMultiple ?? 0) - (b.missDiagnostic?.rMultiple ?? 0));
  const hits = trades
    .filter((t) => Boolean(t.missDiagnostic?.isHit) || (Boolean(t.missDiagnostic) && ['T1_HIT', 'T2_HIT'].includes(t.exitReason)))
    .slice()
    .sort((a, b) => (b.missDiagnostic?.rMultiple ?? 0) - (a.missDiagnostic?.rMultiple ?? 0));

  if (!misses.length && !hits.length) return null;

  return (
    <div className="eod-panel-card space-y-0 overflow-hidden rounded-xl border border-slate-300 border-[0.5px] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
        <span className="desk-panel-title text-slate-900">Outcome Desk</span>
        <span className="desk-pill desk-pill--danger">{misses.length} miss</span>
        <span className="desk-pill desk-pill--ok">{hits.length} target hit</span>
        {coverage != null && (
          <span className="desk-pill desk-pill--info" title="Scorecard-enriched legs">
            SC {coverage}
          </span>
        )}
        {isMock && <span className="desk-pill desk-pill--warn">MOCK</span>}
        <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-slate-400">
          Replaces Miss / Hit cards · Why = Root column
        </span>
      </div>

      {misses.length > 0 && (
        <div>
          <div className="border-b border-slate-100 bg-red-50/40 px-3 py-1.5 text-[9px] font-black uppercase tracking-wider text-red-700">
            Why miss · SL / EOD square-off
          </div>
          <OutcomeTable rows={misses} />
        </div>
      )}

      {hits.length > 0 && (
        <div>
          <div className="border-b border-slate-100 bg-emerald-50/40 px-3 py-1.5 text-[9px] font-black uppercase tracking-wider text-emerald-700">
            Why target hit · T1 / T2
          </div>
          <OutcomeTable rows={hits} />
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Single-number Sparkline (mini bar chart)                                  */
/* -------------------------------------------------------------------------- */
function MiniSparklineBar({ positive, width = 100 }: { positive: boolean; width?: number }) {
  const color = positive ? '#10b981' : '#ef4444';
  return (
    <svg className="w-full h-6" viewBox={`0 0 ${width} 20`} preserveAspectRatio="none">
      <rect x="0" y="8" width="20%" height="10" rx="1.5" fill={color} opacity="0.6" />
      <rect x="22%" y="5" width="20%" height="13" rx="1.5" fill={color} opacity="0.8" />
      <rect x="44%" y="2" width="20%" height="16" rx="1.5" fill={color} opacity="0.9" />
      <rect x="66%" y="6" width="20%" height="12" rx="1.5" fill={color} />
      <rect x="88%" y="0" width="12%" height="18" rx="1.5" fill={color} />
    </svg>
  );
}

export type EodAnalysisPanelProps = {
  embedded?: boolean;
  date?: string;
  swingDate?: string;
  onDateChange?: (date: string) => void;
  onSwingDateChange?: (date: string) => void;
  refreshToken?: number;
  /** When true, rebuild book reports (bypass cache). Default refresh uses cache. */
  forceBookRebuild?: boolean;
};

/* -------------------------------------------------------------------------- */
/*  EOD Analysis Panel — fetches both reports and renders a dashboard         */
/* -------------------------------------------------------------------------- */
export default function EodAnalysisPanel({
  embedded = false,
  date: controlledDate,
  swingDate: controlledSwingDate,
  onDateChange,
  onSwingDateChange,
  refreshToken = 0,
  forceBookRebuild = false,
}: EodAnalysisPanelProps = {}) {
  const [intraday, setIntraday] = useState<IntradayReport | null>(null);
  const [swing, setSwing] = useState<SwingReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [localDate, setLocalDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [localSwingDate, setLocalSwingDate] = useState('');

  const dateStr = controlledDate ?? localDate;
  const swingDateStr = controlledSwingDate ?? localSwingDate;

  const setDateStr = (v: string) => {
    onDateChange?.(v);
    if (controlledDate === undefined) setLocalDate(v);
  };
  const setSwingDateStr = (v: string) => {
    onSwingDateChange?.(v);
    if (controlledSwingDate === undefined) setLocalSwingDate(v);
  };

  const fetchReports = useCallback(async (opts?: { force?: boolean }) => {
    setLoading(true);
    setError(null);
    const force = opts?.force ?? forceBookRebuild;
    const buildQs = (d: string) => {
      const p = new URLSearchParams();
      if (d) p.set('date', d);
      if (force) p.set('force', 'true');
      const s = p.toString();
      return s ? `?${s}` : '';
    };
    const swingDate = swingDateStr || dateStr;
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 20_000);

    const loadOne = async <T,>(url: string, label: string): Promise<T | null> => {
      try {
        const res = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
        if (!res.ok) {
          const text = await res.text().catch(() => '');
          throw new Error(`${label} ${res.status}: ${text.slice(0, 160)}`);
        }
        return (await res.json()) as T;
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.name === 'AbortError'
              ? `${label} timed out (20s)`
              : err.message
            : `${label} failed`;
        setError((prev) => (prev ? `${prev} · ${msg}` : msg));
        return null;
      }
    };

    try {
      const [intraData, swingData] = await Promise.all([
        loadOne<IntradayReport>(`/api/reports/eod-intraday${buildQs(dateStr)}`, 'Intraday'),
        loadOne<SwingReport>(`/api/reports/eod-swing${buildQs(swingDate)}`, 'Swing'),
      ]);
      if (intraData) setIntraday(intraData);
      if (swingData) setSwing(swingData);
      if (!intraData && !swingData) {
        setError((prev) => prev || 'Book P&L failed to load');
      }
    } finally {
      window.clearTimeout(timer);
      setLoading(false);
    }
  }, [dateStr, swingDateStr, forceBookRebuild]);

  useEffect(() => { void fetchReports(); }, [fetchReports, refreshToken]);

  const noIntraday = intraday && (!intraday.trades || intraday.trades.length === 0);
  const noSwing = swing && (!swing.picks || swing.picks.length === 0);
  const fromCache = Boolean(intraday?.fromCache || swing?.fromCache);
  const showBody = Boolean(intraday || swing || error);

  return (
    <div className={`space-y-3 ${embedded ? 'eod-book-surface' : ''}`}>
      {!embedded && (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-3 shadow-sm relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-teal-400 via-cyan-400 to-transparent pointer-events-none" aria-hidden />
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Intraday Date</span>
            <input
              type="date"
              value={dateStr}
              onChange={(e) => setDateStr(e.target.value)}
              className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Swing Date</span>
            <input
              type="date"
              value={swingDateStr}
              onChange={(e) => setSwingDateStr(e.target.value)}
              className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
            />
          </div>
          {fromCache && <span className="desk-pill desk-pill--ok">BOOK · CACHED</span>}
          <button
            onClick={() => void fetchReports({ force: false })}
            disabled={loading}
            className="desk-btn-ghost ml-auto px-3 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
          >
            {loading ? 'LOADING...' : 'REFRESH'}
          </button>
          <button
            onClick={() => void fetchReports({ force: true })}
            disabled={loading}
            className="desk-btn-primary px-3 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
            title="Rebuild book reports and overwrite cache"
          >
            REBUILD
          </button>
        </div>
      </div>
      )}

      {embedded && (
        <div className="flex flex-wrap items-center gap-2 px-0.5">
          {fromCache && <span className="desk-pill desk-pill--ok">BOOK · CACHED</span>}
          {loading && <span className="text-[9px] text-slate-400">Loading book…</span>}
          <span className="text-[9px] text-slate-400">
            Swing date follows EOD date unless changed
          </span>
          <button
            type="button"
            onClick={() => void fetchReports({ force: false })}
            disabled={loading}
            className="desk-btn-ghost ml-auto rounded-md px-2 py-1 text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
          >
            Refresh book
          </button>
          <button
            type="button"
            onClick={() => void fetchReports({ force: true })}
            disabled={loading}
            className="desk-btn-ghost rounded-md px-2 py-1 text-[9px] font-black uppercase tracking-wider disabled:opacity-50"
          >
            Rebuild book
          </button>
        </div>
      )}

      {loading && !showBody && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-6 text-center text-[11px] text-slate-400 shadow-sm">
          Loading EOD reports…
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-3 text-[11px]">
          {error}
        </div>
      )}

      {(intraday || swing) && (
        <>
          {intraday && (
            <OutcomeDesk
              trades={intraday.trades}
              coverage={intraday.missScorecardCoverage}
              isMock={intraday.isMock}
            />
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 eod-dynamic-grid">
          {/* ── INTRADAY REPORT ── */}
          <div className="eod-panel-card bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-teal-50 to-teal-100/50 px-3 py-2 border-b border-slate-200">
              <h3 className="desk-panel-title text-teal-800">Intraday EOD Report</h3>
              <p className="text-[9px] text-teal-600">{intraday?.date ?? dateStr}</p>
            </div>

            {noIntraday ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">No archived intraday picks for this date.</div>
            ) : intraday ? (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Total P&L</div>
                    <div className={`desk-metric-value tabular-nums ${intraday.totalPnl >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                      {intraday.totalPnl >= 0 ? '+' : ''}₹{intraday.totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Deployed</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">₹{intraday.totalDeployed.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Remaining</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">₹{intraday.remainingCapital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Hit Rate</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">{intraday.hitRatePct}%</div>
                  </div>
                </div>

                {/* Hit breakdown */}
                <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-100 text-[9px]">
                  <span className="text-slate-500 uppercase tracking-wider font-bold">Breakdown:</span>
                  <span className="bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-bold">T2 {intraday.hitBreakdown.T2_HIT}</span>
                  <span className="bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded font-bold">T1 {intraday.hitBreakdown.T1_HIT}</span>
                  <span className="bg-red-100 text-red-800 px-1.5 py-0.5 rounded font-bold">SL {intraday.hitBreakdown.SL_HIT}</span>
                  <span className="bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-bold">EOD {intraday.hitBreakdown.EOD_SQUAREOFF}</span>
                </div>

                {/* Trades table */}
                <div className="overflow-x-auto desk-scroll-x">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="text-slate-500 uppercase tracking-wider border-b border-slate-100">
                        <th className="text-left px-2 py-1.5 font-bold">Symbol</th>
                        <th className="text-right px-2 py-1.5 font-bold">Entry</th>
                        <th className="text-right px-2 py-1.5 font-bold">Exit</th>
                        <th className="text-center px-2 py-1.5 font-bold">Result</th>
                        <th className="text-right px-2 py-1.5 font-bold">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {intraday.trades.map((trade, i) => {
                        const badge = exitReasonBadge(trade.exitReason);
                        return (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-2 py-1.5">
                              <span className={`font-bold ${trade.direction === 'LONG' ? 'text-emerald-700' : 'text-red-700'}`}>
                                {trade.symbol}
                              </span>
                              <span className="text-[8px] text-slate-400 ml-1">{trade.direction}</span>
                            </td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{trade.entryPrice}</td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{trade.exitPrice}</td>
                            <td className="text-center px-2 py-1.5">
                              <span className={`${badge.bg} ${badge.txt} px-1 py-0.5 rounded text-[9px] font-bold`}>{badge.label}</span>
                            </td>
                            <td className={`text-right px-2 py-1.5 font-bold tabular-nums ${trade.pnl >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                              {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl.toFixed(2)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="p-4 text-[11px] text-slate-400 text-center">No intraday data available.</div>
            )}
          </div>

          {/* ── SWING REPORT ── */}
          <div className="eod-panel-card bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden" style={{ animationDelay: '70ms' }}>
            <div className="bg-gradient-to-r from-indigo-50 to-indigo-100/50 px-3 py-2 border-b border-slate-200">
              <h3 className="desk-panel-title text-indigo-800">Swing EOD Report</h3>
              <p className="text-[9px] text-indigo-600">{swing?.date ?? dateStr}</p>
            </div>

            {noSwing ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">No picks in the fixed trade plan.</div>
            ) : swing ? (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Total P&L</div>
                    <div className={`desk-metric-value tabular-nums ${swing.totalPnl >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                      {swing.totalPnl >= 0 ? '+' : ''}₹{swing.totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Win / Loss</div>
                    <div className="desk-metric-value tabular-nums">
                      <span className="text-emerald-700">{swing.winCount}</span>
                      <span className="text-slate-400">/</span>
                      <span className="text-red-700">{swing.lossCount}</span>
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Total P&L %</div>
                    <div className={`desk-metric-value tabular-nums ${(swing.totalPnlPct ?? 0) >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                      {swing.totalPnlPct != null ? `${swing.totalPnlPct >= 0 ? '+' : ''}${swing.totalPnlPct}%` : 'N/A'}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Picks</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">{swing.totalPicks}</div>
                  </div>
                </div>

                {/* P&L by day bucket */}
                {Object.keys(swing.pnlByDayBucket).length > 0 && (
                  <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-100 text-[9px] flex-wrap">
                    <span className="text-slate-500 uppercase tracking-wider font-bold">P&L by Day:</span>
                    {Object.entries(swing.pnlByDayBucket).map(([bucket, pnl]) => (
                      <span key={bucket} className={`px-1.5 py-0.5 rounded font-bold ${pnl >= 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
                        Day {bucket}: {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}
                      </span>
                    ))}
                  </div>
                )}

                {/* Picks table */}
                <div className="overflow-x-auto desk-scroll-x">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="text-slate-500 uppercase tracking-wider border-b border-slate-100">
                        <th className="text-left px-2 py-1.5 font-bold">Symbol</th>
                        <th className="text-center px-2 py-1.5 font-bold">Status</th>
                        <th className="text-right px-2 py-1.5 font-bold">Entry</th>
                        <th className="text-right px-2 py-1.5 font-bold">Current</th>
                        <th className="text-center px-2 py-1.5 font-bold">Held</th>
                        <th className="text-right px-2 py-1.5 font-bold">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {swing.picks.map((pick, i) => {
                        const badge = statusBadge(pick.status);
                        return (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-2 py-1.5">
                              <span className={`font-bold ${pick.direction === 'LONG' ? 'text-emerald-700' : 'text-red-700'}`}>
                                {pick.symbol}
                              </span>
                              <span className="text-[8px] text-slate-400 ml-1">{pick.direction}</span>
                            </td>
                            <td className="text-center px-2 py-1.5">
                              <span className={`${badge.bg} ${badge.txt} px-1 py-0.5 rounded text-[9px] font-bold`}>{badge.label}</span>
                            </td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{pick.entryPrice}</td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{pick.currentPrice}</td>
                            <td className="text-center px-2 py-1.5 text-slate-500">
                              {pick.daysHeld != null ? `${pick.daysHeld}d` : '-'}
                              {pick.dayBucket != null && <span className="text-[8px] text-slate-400 ml-1">(D{pick.dayBucket})</span>}
                            </td>
                            <td className={`text-right px-2 py-1.5 font-bold tabular-nums ${pick.pnl >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                              {pick.pnl >= 0 ? '+' : ''}₹{pick.pnl.toFixed(2)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="p-4 text-[11px] text-slate-400 text-center">No swing data available.</div>
            )}
          </div>
        </div>
        </>
      )}

      {(intraday || swing) && (
        <>
          {/* Best / Worst performer cards */}
          {swing && (swing.bestPerformer || swing.worstPerformer) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {swing.bestPerformer && (
                <div className="bg-gradient-to-r from-emerald-50 to-white border border-emerald-200 rounded-xl p-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="desk-panel-title text-emerald-700">Best Performer</span>
                  </div>
                  <div className="flex items-end justify-between mt-1">
                    <div>
                      <span className="text-[16px] font-black text-slate-900">{swing.bestPerformer.symbol}</span>
                      <span className="text-[10px] text-slate-500 ml-1">{swing.bestPerformer.direction}</span>
                    </div>
                    <span className="text-[16px] font-black text-emerald-600 tabular-nums">+₹{swing.bestPerformer.pnl.toFixed(2)}</span>
                  </div>
                </div>
              )}
              {swing.worstPerformer && (
                <div className="bg-gradient-to-r from-red-50 to-white border border-red-200 rounded-xl p-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                    <span className="desk-panel-title text-red-700">Worst Performer</span>
                  </div>
                  <div className="flex items-end justify-between mt-1">
                    <div>
                      <span className="text-[16px] font-black text-slate-900">{swing.worstPerformer.symbol}</span>
                      <span className="text-[10px] text-slate-500 ml-1">{swing.worstPerformer.direction}</span>
                    </div>
                    <span className="text-[16px] font-black text-red-600 tabular-nums">₹{swing.worstPerformer.pnl.toFixed(2)}</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}