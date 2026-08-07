'use client';

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { LiveTickNumber } from '@/lib/desk-motion';

/* -------------------------------------------------------------------------- */
/*  Types for EOD report responses from the backend                          */
/* -------------------------------------------------------------------------- */

type MissDiagnostic = {
  isMiss: boolean;
  isHit?: boolean;
  isSkip?: boolean;
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
  source: 'LEVELS' | 'SCORECARD' | 'SKIP' | string;
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
  pnl: number | null;
  pnlPct: number | null;
  missAnalysis: string | null;
  missDiagnostic?: MissDiagnostic | null;
  outcomeNarrative?: string | null;
  deskIcSummary?: { decision?: string; conviction?: number; oneLiner?: string } | null;
  /** Live overlay (session only) — not from book cache */
  markLive?: boolean;
  pnlKind?: 'realised' | 'unrealised';
  /** Scale-trail state fields — from backend SCALE_TRAIL mode */
  remainingQty?: number | null;
  effectiveStop?: number | null;
  exitState?: {
    legsFilled?: number[];
    remainingQty?: number | null;
    effectiveStop?: number | null;
    realizedPnl?: number | null;
    unrealizedPnl?: number | null;
    rMultiple?: number | null;
    closed?: boolean;
  } | null;
  exitPlan?: { mode?: string; legs?: { r?: number }[] } | null;
  scaleTrail?: boolean;
  scaleProgress?: string | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  rMultiple?: number | null;
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
  hitCount?: number;
  missScorecardCoverage?: number;
  isMock?: boolean;
  symbolSource?: string;
  deskCounts?: { swing?: number; intradayLong?: number; intradayShort?: number; total?: number };
  fromCache?: boolean;
  cachedAt?: string;
  attribution?: {
    locked?: number;
    triggered?: number;
    skipped?: number;
    wins?: number;
    losses?: number;
    deployed?: number;
  };
  dayLessons?: string[];
  trades: IntradayTrade[];
};

type SwingPick = {
  symbol: string;
  direction: string;
  entryDate: string | null;
  daysHeld: number | null;
  dayBucket: number | null;
  status: string;
  exitReason?: string;
  entryPrice: number;
  refPrice930: number;
  currentPrice: number | null;
  stopLoss: number;
  target1: number;
  target2: number;
  qty: number;
  deployedCapital: number;
  pnl: number | null;
  pnlPct: number | null;
  alertsFired: unknown[];
  skipped?: boolean;
  missDiagnostic?: MissDiagnostic | null;
  outcomeNarrative?: string | null;
  deskIcSummary?: { decision?: string; conviction?: number; oneLiner?: string } | null;
  analysis?: string | null;
  markLive?: boolean;
  pnlKind?: 'realised' | 'unrealised';
  /** Scale-trail state — from backend SCALE_TRAIL mode */
  remainingQty?: number | null;
  effectiveStop?: number | null;
  exitPlan?: { mode?: string; legs?: { r?: number }[] } | null;
  exitState?: {
    legsFilled?: Array<number | { r?: number | string }>;
    remainingQty?: number | null;
    effectiveStop?: number | null;
    realizedPnl?: number | null;
    unrealizedPnl?: number | null;
    rMultiple?: number | null;
    closed?: boolean;
  } | null;
  scaleTrail?: boolean;
  scaleProgress?: string | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  rMultiple?: number | null;
};

type SwingReport = {
  date: string;
  totalPicks: number;
  activePicks?: number;
  skippedNotTriggered?: number;
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
  symbolSource?: string;
  deskCounts?: { swing?: number; intradayLong?: number; intradayShort?: number; total?: number };
  referenceDate?: string;
  referenceLabel?: string;
  fromCache?: boolean;
  cachedAt?: string;
  attribution?: {
    locked?: number;
    triggered?: number;
    skipped?: number;
    wins?: number;
    losses?: number;
    deployed?: number;
  };
  dayLessons?: string[];
  rotation?: string;
  source?: string;
};

/* -------------------------------------------------------------------------- */
/*  Helper: color classes for exit reasons                                    */
/* -------------------------------------------------------------------------- */
function exitReasonBadge(reason: string) {
  switch (reason) {
    case 'T2_HIT': return { bg: 'bg-emerald-100', txt: 'text-emerald-800', label: 'T2 ✓' };
    case 'T1_HIT': return { bg: 'bg-emerald-50', txt: 'text-emerald-700', label: 'T1 ✓' };
    case 'SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'SL ✗' };
    case 'TRAIL_SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'TRAIL ✗' };
    case 'EOD_SQUAREOFF': return { bg: 'bg-amber-100', txt: 'text-amber-800', label: 'EOD ∎' };
    case 'PARTIAL_SCALE': return { bg: 'bg-amber-100', txt: 'text-amber-800', label: 'PARTIAL ⟳' };
    default: return { bg: 'bg-slate-100', txt: 'text-slate-600', label: reason };
  }
}

function statusBadge(status: string) {
  switch (status) {
    case 'T2_HIT': return { bg: 'bg-emerald-100', txt: 'text-emerald-800', label: 'T2 ✓' };
    case 'T1_HIT': return { bg: 'bg-emerald-50', txt: 'text-emerald-700', label: 'T1 ✓' };
    case 'SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'SL ✗' };
    case 'TRAIL_SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'TRAIL ✗' };
    case 'PARTIAL_SCALE': return { bg: 'bg-amber-100', txt: 'text-amber-800', label: 'PARTIAL ⟳' };
    case 'NOT_TRIGGERED': return { bg: 'bg-slate-200', txt: 'text-slate-600', label: 'Not Triggered' };
    case 'OPEN': return { bg: 'bg-blue-100', txt: 'text-blue-800', label: 'Open ◇' };
    case 'NO_MARK': return { bg: 'bg-slate-200', txt: 'text-slate-600', label: 'No mark' };
    case 'SESSION CLOSED': return { bg: 'bg-slate-200', txt: 'text-slate-700', label: 'Closed' };
    case 'EOD_SQUAREOFF': return { bg: 'bg-amber-100', txt: 'text-amber-800', label: 'EOD ∎' };
    default: return { bg: 'bg-slate-100', txt: 'text-slate-600', label: status };
  }
}

function ScaleExitCell({
  scaleTrail,
  scaleProgress,
  exitPlan,
  exitState,
  effectiveStop,
  remainingQty,
  qty,
}: {
  scaleTrail?: boolean;
  scaleProgress?: string | null;
  exitPlan?: { mode?: string } | null;
  exitState?: { remainingQty?: number | null; effectiveStop?: number | null } | null;
  effectiveStop?: number | null;
  remainingQty?: number | null;
  qty?: number | null;
}) {
  const isScale = Boolean(scaleTrail || exitPlan?.mode === 'SCALE_TRAIL' || scaleProgress);
  if (!isScale) {
    return <span className="text-[8px] text-slate-400 font-bold uppercase">BINARY</span>;
  }
  const rem = exitState?.remainingQty ?? remainingQty;
  const trail = exitState?.effectiveStop ?? effectiveStop;
  return (
    <div className="flex flex-col items-start gap-0.5 min-w-[9rem]">
      <span className="text-[8px] font-mono tabular-nums text-slate-700 whitespace-nowrap">
        {scaleProgress || 'SCALE_TRAIL'}
      </span>
      <span className="text-[7px] text-amber-700 font-bold tabular-nums">
        {rem != null ? `rem ${rem}${qty != null ? `/${qty}` : ''}` : null}
        {trail != null ? `${rem != null ? ' · ' : ''}trail SL ${Number(trail).toFixed(2)}` : null}
      </span>
    </div>
  );
}

function fmtInr(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n > 0 ? '+' : '';
  return `${sign}₹${n.toFixed(digits)}`;
}

function pnlTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return 'text-slate-500';
  return Number(v) >= 0 ? 'text-emerald-600' : 'text-red-500';
}

const CLOSED_EXIT = new Set(['T1_HIT', 'T2_HIT', 'SL_HIT', 'TRAIL_SL_HIT']);
// PARTIAL_SCALE is intentionally excluded — the runner is still live (not fully closed).

function isClosedBookLeg(exitReason: string | null | undefined): boolean {
  return CLOSED_EXIT.has(String(exitReason || '').toUpperCase());
}

function mtmPnl(direction: string, entry: number, mark: number, qty: number): number {
  const sign = String(direction || 'LONG').toUpperCase() === 'SHORT' ? -1 : 1;
  return sign * (mark - entry) * qty;
}

function istCalendarToday(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

type LivePriceRow = {
  symbol?: string;
  direction?: string;
  currentPrice?: number | null;
  ltp?: number | null;
  entryPrice?: number | null;
  approxQty?: number | null;
  status?: string | null;
  closed?: boolean | null;
  remainingQty?: number | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  outcome?: { hitLevel?: string | null; ltp?: number | null; pctChange?: number | null; scaleTrail?: boolean; label?: string | null; pnl?: number | null } | null;
  exitPlan?: { mode?: string } | null;
  exitState?: { remainingQty?: number | null; effectiveStop?: number | null; realizedPnl?: number | null; unrealizedPnl?: number | null; closed?: boolean } | null;
};

type LiveMark = {
  ltp: number;
  hitLevel: string | null;
  remainingQty?: number | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  closed?: boolean | null;
  status?: string | null;
};

type LiveMarksState = {
  marketOpen: boolean;
  updatedAt: string | null;
  byKey: Record<string, LiveMark>;
  bySymbol: Record<string, number>;
};

function markKey(symbol: string, direction?: string | null): string {
  return `${String(symbol || '').toUpperCase()}|${String(direction || 'LONG').toUpperCase()}`;
}

function isLiveHardClose(mark: LiveMark | null | undefined): boolean {
  if (!mark) return false;
  const hit = String(mark.hitLevel || '').toLowerCase();
  const status = String(mark.status || '').toUpperCase();
  if (hit === 'sl' || hit === 't1' || hit === 't2') return true;
  if (status.includes('STOP') || status.includes('TRAIL STOP') || status.includes('TARGET 1') || status.includes('TARGET 2')) {
    return true;
  }
  return Boolean(mark.closed) && !(Number(mark.remainingQty) > 0);
}

function exitReasonFromHit(hit: string | null | undefined, fallback: string): string {
  const h = String(hit || '').toLowerCase();
  if (h === 't2') return 'T2_HIT';
  if (h === 't1') return 'T1_HIT';
  if (h === 'sl') return 'SL_HIT';
  if (h === 'partial') return 'PARTIAL_SCALE';
  return fallback;
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
  const ic = trade.deskIcSummary?.decision;
  return (
    <>
      <tr className="border-t border-slate-100 hover:bg-slate-50/80">
        <td className="px-2 py-1.5 font-bold text-slate-900">
          {trade.symbol}
          {ic && (
            <span
              className={`ml-1 desk-pill ${
                ic === 'APPROVE' ? 'desk-pill--ok' : ic === 'REJECT' ? 'desk-pill--danger' : 'desk-pill--warn'
              }`}
              title={trade.deskIcSummary?.oneLiner || ic}
            >
              IC {ic}
            </span>
          )}
        </td>
        <td className={`px-2 py-1.5 font-semibold ${trade.direction === 'LONG' ? 'text-emerald-700' : 'text-red-600'}`}>
          {trade.direction}
        </td>
        <td className="px-2 py-1.5 text-right tabular-nums text-slate-700">{trade.qty ?? '—'}</td>
        <td className="px-2 py-1.5">
          <span className={`desk-pill ${exitTone}`}>{trade.exitReason}</span>
        </td>
        <td className={`px-2 py-1.5 text-right tabular-nums font-bold ${rBad ? 'text-red-600' : 'text-emerald-700'}`}>
          {fmtMissSigned(d.rMultiple, 2, 'R')}
        </td>
        <td className={`px-2 py-1.5 text-right tabular-nums ${rBad ? 'text-red-600' : 'text-slate-700'}`}>
          {fmtMissSigned(d.movePct, 2, '%')}
        </td>
        <td className="hidden sm:table-cell px-2 py-1.5 text-right tabular-nums text-slate-600">{fmtMissNum(d.maePct, 2)}</td>
        <td className="hidden sm:table-cell px-2 py-1.5 text-right tabular-nums text-slate-600">{fmtMissNum(d.mfePct, 2)}</td>
        <td className="hidden sm:table-cell px-2 py-1.5">
          <span className={`desk-pill ${rootCauseTone(d.rootCause)}`}>
            {(d.rootCause || '—').replace(/_/g, ' ')}
          </span>
        </td>
        <td className={`px-2 py-1.5 text-right tabular-nums font-bold ${pnlTone(trade.pnl ?? trade.pnlPct)}`}>
          {trade.pnl == null
            ? fmtMissSigned(trade.pnlPct, 2, '%')
            : Math.abs(trade.pnl) < 1e-6 && trade.pnlPct != null
              ? fmtMissSigned(trade.pnlPct, 2, '%')
              : fmtInr(trade.pnl, 0)}
        </td>
        <td className="hidden sm:table-cell px-2 py-1.5">
          <div className="flex max-w-[220px] flex-wrap gap-1">
            {d.falsePositive && <span className="desk-pill desk-pill--danger">FP</span>}
            {(d.factors || []).slice(0, 3).map((f) => (
              <span key={f} className="desk-pill desk-pill--muted" title={f}>
                {f.replace(/_/g, ' ').slice(0, 18)}
              </span>
            ))}
          </div>
        </td>
        <td className="hidden sm:table-cell px-2 py-1.5 font-bold text-slate-500">{d.source === 'SCORECARD' ? 'SC' : 'LVL'}</td>
      </tr>
      {trade.outcomeNarrative && (
        <tr className="bg-slate-50/60">
          <td colSpan={12} className="px-3 py-1.5 text-[10px] leading-snug text-slate-600">
            <span className="font-black uppercase tracking-wider text-slate-400 mr-1">Why</span>
            {trade.outcomeNarrative}
          </td>
        </tr>
      )}
    </>
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
            <th className="px-2 py-2 text-right font-bold">Qty</th>
            <th className="px-2 py-2 text-left font-bold">Exit</th>
            <th className="px-2 py-2 text-right font-bold">R</th>
            <th className="px-2 py-2 text-right font-bold">Move%</th>
            <th className="hidden sm:table-cell px-2 py-2 text-right font-bold">MAE</th>
            <th className="hidden sm:table-cell px-2 py-2 text-right font-bold">MFE</th>
            <th className="hidden sm:table-cell px-2 py-2 text-left font-bold">Why (root)</th>
            <th className="px-2 py-2 text-right font-bold">P&L</th>
            <th className="hidden sm:table-cell px-2 py-2 text-left font-bold">Flags</th>
            <th className="hidden sm:table-cell px-2 py-2 text-left font-bold">Src</th>
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
function OutcomeDesk({ trades, coverage, isMock, symbolSource, bookLabel = 'Intraday' }: {
  trades: IntradayTrade[];
  coverage?: number;
  isMock?: boolean;
  symbolSource?: string;
  bookLabel?: string;
}) {
  const misses = trades
    .filter((t) => t.missDiagnostic?.isMiss)
    .slice()
    .sort((a, b) => (a.missDiagnostic?.rMultiple ?? 0) - (b.missDiagnostic?.rMultiple ?? 0));
  const hits = trades
    .filter((t) => Boolean(t.missDiagnostic?.isHit) || (Boolean(t.missDiagnostic) && ['T1_HIT', 'T2_HIT'].includes(t.exitReason)))
    .slice()
    .sort((a, b) => (b.missDiagnostic?.rMultiple ?? 0) - (a.missDiagnostic?.rMultiple ?? 0));
  const skips = trades
    .filter((t) => Boolean(t.missDiagnostic?.isSkip) || ['NOT_TRIGGERED', 'NO_MARK'].includes(t.exitReason))
    .slice()
    .sort((a, b) => a.symbol.localeCompare(b.symbol));

  if (!misses.length && !hits.length && !skips.length) return null;

  return (
    <div className="eod-panel-card space-y-0 overflow-hidden rounded-xl border border-slate-300 border-[0.5px] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
        <span className="desk-panel-title text-slate-900">Outcome Desk · {bookLabel}</span>
        <span className="desk-pill desk-pill--danger">{misses.length} miss</span>
        <span className="desk-pill desk-pill--ok">{hits.length} target hit</span>
        {skips.length > 0 && (
          <span className="desk-pill desk-pill--muted">{skips.length} skip</span>
        )}
        {coverage != null && (
          <span className="desk-pill desk-pill--info" title="Scorecard-enriched legs">
            SC {coverage}
          </span>
        )}
        {symbolSource && !isMock && (
          <span className="desk-pill desk-pill--info" title="Locked desk symbol source">
            {symbolSource}
          </span>
        )}
        {isMock && <span className="desk-pill desk-pill--warn">MOCK</span>}
        <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-slate-400">
          {bookLabel} lock · diagnostics first · narrative on rebuild
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

      {skips.length > 0 && (
        <div>
          <div className="border-b border-slate-100 bg-slate-100/80 px-3 py-1.5 text-[9px] font-black uppercase tracking-wider text-slate-600">
            Skipped · not triggered (excluded from P&L)
          </div>
          <OutcomeTable rows={skips} />
        </div>
      )}
    </div>
  );
}

function AttributionStrip({
  attribution,
  label,
}: {
  attribution?: SwingReport['attribution'] | IntradayReport['attribution'];
  label: string;
}) {
  if (!attribution) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 border-b border-slate-100 text-[9px]">
      <span className="font-black uppercase tracking-wider text-slate-500">{label}</span>
      <span className="desk-pill desk-pill--info">Locked {attribution.locked ?? '—'}</span>
      <span className="desk-pill desk-pill--ok">Triggered {attribution.triggered ?? '—'}</span>
      <span className="desk-pill desk-pill--muted">Skipped {attribution.skipped ?? 0}</span>
      <span className="desk-pill desk-pill--ok">Wins {attribution.wins ?? '—'}</span>
      <span className="desk-pill desk-pill--danger">Losses {attribution.losses ?? '—'}</span>
      <span className="desk-pill desk-pill--info">
        Deployed{' '}
        {attribution.deployed != null
          ? `₹${Number(attribution.deployed).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
          : '—'}
      </span>
    </div>
  );
}

function DayLessonsStrip({ lessons }: { lessons?: string[] }) {
  if (!lessons?.length) return null;
  return (
    <div className="mx-3 mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[9px] font-black uppercase tracking-wider text-slate-500 mb-1">Day lessons</div>
      <ul className="list-disc pl-4 space-y-0.5 text-[10px] text-slate-700">
        {lessons.slice(0, 5).map((l, i) => (
          <li key={i}>{l}</li>
        ))}
      </ul>
    </div>
  );
}

function PortfolioDist({
  title,
  rows,
  totalDeployed,
}: {
  title: string;
  rows: { symbol: string; deployed: number; qty: number; pnl: number | null; pnlPct: number | null }[];
  totalDeployed: number;
}) {
  if (!rows.length) return null;
  const total = totalDeployed > 0 ? totalDeployed : rows.reduce((s, r) => s + (r.deployed || 0), 0);
  return (
    <div className="border-t border-slate-100 px-3 py-2">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="text-[9px] font-black uppercase tracking-wider text-slate-500">{title}</span>
        <span className="desk-pill desk-pill--info">
          Deployed {total > 0 ? `₹${total.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
        </span>
        <span className="text-[9px] text-slate-400">{rows.length} names</span>
      </div>
      <div className="overflow-x-auto desk-scroll-x">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="text-slate-500 uppercase tracking-wider border-b border-slate-100">
              <th className="text-left px-1 py-1 font-bold">Symbol</th>
              <th className="text-right px-1 py-1 font-bold">Qty</th>
              <th className="text-right px-1 py-1 font-bold">Deployed</th>
              <th className="text-right px-1 py-1 font-bold">Weight</th>
              <th className="text-right px-1 py-1 font-bold">P&L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const w = total > 0 && r.deployed > 0 ? (r.deployed / total) * 100 : null;
              return (
                <tr key={r.symbol} className="border-b border-slate-50">
                  <td className="px-1 py-1 font-bold text-slate-800">{r.symbol}</td>
                  <td className="px-1 py-1 text-right tabular-nums text-slate-700">{r.qty || '—'}</td>
                  <td className="px-1 py-1 text-right tabular-nums text-slate-700">
                    {r.deployed > 0 ? `₹${r.deployed.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="px-1 py-1 text-right tabular-nums text-slate-500">
                    {w != null ? `${w.toFixed(1)}%` : '—'}
                  </td>
                  <td className={`px-1 py-1 text-right tabular-nums font-bold ${pnlTone(r.pnl ?? r.pnlPct)}`}>
                    {r.pnl != null ? fmtInr(r.pnl, 0) : fmtMissSigned(r.pnlPct, 2, '%')}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
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
  const [liveMarks, setLiveMarks] = useState<LiveMarksState | null>(null);
  const liveBusy = useRef(false);

  const dateStr = controlledDate ?? localDate;
  const swingDateStr = controlledSwingDate ?? localSwingDate;
  const isTodayBook = dateStr === istCalendarToday();

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
    // Prefer explicit opts.force — parent may clear forceBookRebuild without re-fetching
    const force = Boolean(opts?.force);
    const buildQs = (d: string) => {
      const p = new URLSearchParams();
      if (d) p.set('date', d);
      if (force) p.set('force', 'true');
      const s = p.toString();
      return s ? `?${s}` : '';
    };
    const swingDate = swingDateStr || dateStr;
    const ctrl = new AbortController();
    // Cache loads are fast; force rebuild may fetch close marks — allow up to 60s
    const timer = window.setTimeout(() => ctrl.abort(), force ? 60_000 : 20_000);

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
              ? `${label} timed out (${force ? '60s' : '20s'})`
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
  }, [dateStr, swingDateStr]);

  // forceBookRebuild is read only when refreshToken/date triggers — parent may clear it without a second fetch
  useEffect(() => {
    void fetchReports({ force: forceBookRebuild });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot force paired with refreshToken
  }, [fetchReports, refreshToken]);

  // Market-hours live marks — overlay LTP / MTM without rewriting book cache
  useEffect(() => {
    if (!isTodayBook) {
      setLiveMarks(null);
      return;
    }
    let cancelled = false;

    const loadLive = async () => {
      if (liveBusy.current) return;
      liveBusy.current = true;
      try {
        const [lpRes, swingRes, intraRes] = await Promise.all([
          fetch('/api/live-prices', { cache: 'no-store' }),
          fetch('/api/swing-session?live=1', { cache: 'no-store' }),
          fetch('/api/intraday-session', { cache: 'no-store' }),
        ]);
        const lp = lpRes.ok ? await lpRes.json() : null;
        const sw = swingRes.ok ? await swingRes.json() : null;
        const intra = intraRes.ok ? await intraRes.json() : null;
        if (cancelled) return;

        const byKey: LiveMarksState['byKey'] = {};
        const bySymbol: LiveMarksState['bySymbol'] = {};

        const ingestPlan = (rows: LivePriceRow[] | undefined, fallbackDir: string) => {
          for (const row of rows || []) {
            const sym = String(row.symbol || '').toUpperCase();
            if (!sym) continue;
            const ltp = Number(row.currentPrice ?? row.ltp ?? row.outcome?.ltp);
            if (!Number.isFinite(ltp) || ltp <= 0) continue;
            const dir = String(row.direction || fallbackDir).toUpperCase();
            const hit = row.outcome?.hitLevel != null ? String(row.outcome.hitLevel) : null;
            byKey[markKey(sym, dir)] = {
              ltp,
              hitLevel: hit,
              remainingQty: row.remainingQty ?? row.exitState?.remainingQty ?? null,
              realizedPnl: row.realizedPnl ?? row.exitState?.realizedPnl ?? null,
              unrealizedPnl: row.unrealizedPnl ?? row.exitState?.unrealizedPnl ?? null,
              closed: row.closed ?? row.exitState?.closed ?? null,
              status: row.status ?? row.outcome?.label ?? null,
            };
            bySymbol[sym] = ltp;
          }
        };
        ingestPlan(lp?.long as LivePriceRow[] | undefined, 'LONG');
        ingestPlan(lp?.short as LivePriceRow[] | undefined, 'SHORT');

        const ingestSession = (rows: LivePriceRow[] | undefined, fallbackDir: string) => {
          for (const row of rows || []) {
            const sym = String(row.symbol || '').toUpperCase();
            if (!sym) continue;
            const ltp = Number(row.currentPrice ?? row.ltp);
            if (!Number.isFinite(ltp) || ltp <= 0) continue;
            bySymbol[sym] = ltp;
            const dir = String(row.direction || fallbackDir).toUpperCase();
            const key = markKey(sym, dir);
            const prev = byKey[key];
            byKey[key] = {
              ltp,
              hitLevel: prev?.hitLevel ?? null,
              remainingQty: row.remainingQty ?? row.exitState?.remainingQty ?? prev?.remainingQty ?? null,
              realizedPnl: row.realizedPnl ?? row.exitState?.realizedPnl ?? prev?.realizedPnl ?? null,
              unrealizedPnl: row.unrealizedPnl ?? row.exitState?.unrealizedPnl ?? prev?.unrealizedPnl ?? null,
              closed: row.closed ?? row.exitState?.closed ?? prev?.closed ?? null,
              status: row.status ?? prev?.status ?? null,
            };
          }
        };
        ingestSession([...(sw?.long || []), ...(sw?.short || [])] as LivePriceRow[], 'LONG');
        ingestSession(
          [...(intra?.long || []), ...(intra?.short || []), ...(intra?.locked?.long || []), ...(intra?.locked?.short || [])] as LivePriceRow[],
          'LONG',
        );

        const marketOpen = Boolean(lp?.marketOpen);
        setLiveMarks({
          marketOpen,
          updatedAt: typeof lp?.updatedAt === 'string' ? lp.updatedAt : new Date().toISOString(),
          byKey,
          bySymbol,
        });
      } catch {
        /* keep last good marks */
      } finally {
        liveBusy.current = false;
      }
    };

    void loadLive();
    const id = window.setInterval(() => {
      void loadLive();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [isTodayBook]);

  const liveActive = Boolean(isTodayBook && liveMarks && (liveMarks.marketOpen || Object.keys(liveMarks.bySymbol).length > 0));

  const displayIntraday = useMemo(() => {
    if (!intraday) return null;
    if (!liveActive || !liveMarks) return intraday;

    let realised = 0;
    let unrealised = 0;
    const trades = (intraday.trades || []).map((t) => {
      const sym = String(t.symbol || '').toUpperCase();
      const dir = String(t.direction || 'LONG').toUpperCase();
      const live = liveMarks.byKey[markKey(sym, dir)] || (liveMarks.bySymbol[sym] != null
        ? { ltp: liveMarks.bySymbol[sym], hitLevel: null as string | null }
        : null);

      const closedBook = isClosedBookLeg(t.exitReason);
      // SCALE_TRAIL / exitState: prefer live-prices economics while market is open.
      // Stale book often has EOD_SQUAREOFF closed rem=0 — that must not freeze LIVE MTM.
      if (t.exitPlan?.mode === 'SCALE_TRAIL' || t.exitState != null) {
        const state = t.exitState;
        const reason = String(t.exitReason || '').toUpperCase();
        const hardHitBook = isClosedBookLeg(reason);
        const entry = Number(t.entryPrice) || 0;
        const qty = Number(t.qty) || 0;

        if (!live) {
          const realized = Number(state?.realizedPnl ?? t.realizedPnl ?? 0);
          const unrealized = hardHitBook ? 0 : Number(state?.unrealizedPnl ?? t.unrealizedPnl ?? 0);
          const pnl = realized + unrealized;
          realised += realized;
          unrealised += unrealized;
          return {
            ...t,
            pnl: state != null || t.realizedPnl != null ? pnl : t.pnl,
            markLive: false,
            pnlKind: hardHitBook ? ('realised' as const) : ('unrealised' as const),
          };
        }

        const liveHard = isLiveHardClose(live);
        if (liveHard || (hardHitBook && !(Number(live.remainingQty) > 0) && !liveMarks.marketOpen)) {
          const realized = Number(state?.realizedPnl ?? t.realizedPnl ?? t.pnl ?? 0);
          realised += realized;
          return {
            ...t,
            markLive: false,
            pnlKind: 'realised' as const,
            pnl: realized,
          };
        }

        const exitPrice = live.ltp;
        let remQty = Number(live.remainingQty);
        if (!Number.isFinite(remQty)) {
          remQty = Math.max(0, Number(state?.remainingQty ?? t.remainingQty ?? 0));
        }
        // Soft book square during market hours: remount open qty from live / full size
        if (liveMarks.marketOpen && remQty <= 0 && !liveHard && (reason === 'EOD_SQUAREOFF' || reason === 'PARTIAL_SCALE' || !hardHitBook)) {
          remQty = qty;
        }

        let realized =
          live.realizedPnl != null && Number.isFinite(Number(live.realizedPnl))
            ? Number(live.realizedPnl)
            : remQty > 0 && liveMarks.marketOpen && (reason === 'EOD_SQUAREOFF' || Boolean(state?.closed))
              ? 0
              : Number(state?.realizedPnl ?? t.realizedPnl ?? 0);

        let unrealized =
          live.unrealizedPnl != null && Number.isFinite(Number(live.unrealizedPnl))
            ? Number(live.unrealizedPnl)
            : remQty > 0 && entry > 0
              ? mtmPnl(dir, entry, exitPrice, remQty)
              : 0;

        const pnl = realized + unrealized;
        realised += realized;
        unrealised += unrealized;
        const stillOpen = remQty > 0 || !liveHard;
        return {
          ...t,
          exitPrice,
          exitReason: liveHard ? exitReasonFromHit(live.hitLevel, reason) : stillOpen && reason === 'EOD_SQUAREOFF' ? 'EOD_SQUAREOFF' : reason,
          exitState: {
            ...(state || {}),
            unrealizedPnl: unrealized,
            realizedPnl: realized,
            remainingQty: remQty,
            closed: !stillOpen,
          },
          remainingQty: remQty,
          realizedPnl: realized,
          unrealizedPnl: unrealized,
          pnl,
          pnlPct: entry > 0 && qty > 0 ? (pnl / (entry * qty)) * 100 : t.pnlPct,
          markLive: stillOpen,
          pnlKind: stillOpen ? ('unrealised' as const) : ('realised' as const),
        };
      }
      if (closedBook && !live?.hitLevel) {
        const pnl = t.pnl ?? 0;
        realised += pnl;
        return { ...t, markLive: false, pnlKind: 'realised' as const };
      }

      if (live) {
        const reason = exitReasonFromHit(live.hitLevel, closedBook ? t.exitReason : 'EOD_SQUAREOFF');
        const closedLive = isClosedBookLeg(reason);
        let exitPrice = t.exitPrice;
        if (closedLive) {
          if (reason === 'T2_HIT' && t.target2 != null) exitPrice = Number(t.target2);
          else if (reason === 'T1_HIT' && t.target1 != null) exitPrice = Number(t.target1);
          else if (reason === 'SL_HIT' && t.stopLoss != null) exitPrice = Number(t.stopLoss);
          else exitPrice = live.ltp;
        } else {
          exitPrice = live.ltp;
        }
        const entry = Number(t.entryPrice) || 0;
        const qty = Number(t.qty) || 0;
        const pnl = mtmPnl(dir, entry, exitPrice, qty);
        const pnlPct = entry > 0 ? (mtmPnl(dir, entry, exitPrice, 1) / entry) * 100 : null;
        if (closedLive) realised += pnl;
        else unrealised += pnl;
        return {
          ...t,
          exitPrice,
          exitReason: reason,
          pnl,
          pnlPct,
          markLive: !closedLive,
          pnlKind: closedLive ? ('realised' as const) : ('unrealised' as const),
        };
      }

      const pnl = t.pnl ?? 0;
      if (closedBook) realised += pnl;
      else unrealised += pnl;
      return {
        ...t,
        markLive: false,
        pnlKind: closedBook ? ('realised' as const) : ('unrealised' as const),
      };
    });

    return {
      ...intraday,
      trades,
      totalPnl: realised + unrealised,
      remainingCapital: (intraday.capital || 0) - (intraday.totalDeployed || 0) + realised + unrealised,
      liveRealisedPnl: realised,
      liveUnrealisedPnl: unrealised,
      liveOverlay: true,
    } as IntradayReport & {
      liveRealisedPnl: number;
      liveUnrealisedPnl: number;
      liveOverlay: boolean;
    };
  }, [intraday, liveActive, liveMarks]);

  const displaySwing = useMemo(() => {
    if (!swing) return null;
    if (!liveActive || !liveMarks) return swing;

    let realised = 0;
    let unrealised = 0;
    const picks = (swing.picks || []).map((p) => {
      if (p.skipped) {
        return { ...p, markLive: false, pnlKind: 'realised' as const };
      }
      const sym = String(p.symbol || '').toUpperCase();
      const dir = String(p.direction || 'LONG').toUpperCase();
      const live =
        liveMarks.byKey[markKey(sym, dir)] ||
        (liveMarks.bySymbol[sym] != null
          ? ({ ltp: liveMarks.bySymbol[sym], hitLevel: null } as LiveMark)
          : null);
      const liveLtp = live?.ltp ?? null;
      const closedBook = isClosedBookLeg(p.exitReason);
      const liveHard = isLiveHardClose(live);
      // Book EOD_SQUAREOFF / status containing HIT (TRAIL) — don't treat soft EOD as hard.
      const hardClosed = liveHard || (closedBook && !(Number(live?.remainingQty) > 0));

      if (hardClosed && liveLtp == null) {
        const pnl = p.pnl ?? 0;
        realised += pnl;
        return { ...p, markLive: false, pnlKind: 'realised' as const };
      }

      if (liveLtp != null && !hardClosed) {
        const entry = Number(p.entryPrice) || 0;
        const qty = Number(p.qty) || 0;
        const state = p.exitState;
        const reason = String(p.exitReason || '').toUpperCase();
        const isScale = Boolean(p.exitPlan?.mode === 'SCALE_TRAIL' || state != null || p.scaleTrail);
        if (isScale || liveMarks.marketOpen) {
          let remQty = Number(live?.remainingQty);
          if (!Number.isFinite(remQty)) {
            remQty = Math.max(0, Number(state?.remainingQty ?? p.remainingQty ?? 0));
          }
          if (liveMarks.marketOpen && remQty <= 0 && (reason === 'EOD_SQUAREOFF' || Boolean(state?.closed))) {
            remQty = qty;
          }
          let realized =
            live?.realizedPnl != null && Number.isFinite(Number(live.realizedPnl))
              ? Number(live.realizedPnl)
              : remQty > 0 && liveMarks.marketOpen && (reason === 'EOD_SQUAREOFF' || Boolean(state?.closed))
                ? 0
                : Number(state?.realizedPnl ?? p.realizedPnl ?? 0);
          let unrealized =
            live?.unrealizedPnl != null && Number.isFinite(Number(live.unrealizedPnl))
              ? Number(live.unrealizedPnl)
              : remQty > 0 && entry > 0
                ? mtmPnl(dir, entry, liveLtp, remQty)
                : 0;
          const pnl = realized + unrealized;
          const stillOpen = remQty > 0;
          realised += realized;
          unrealised += unrealized;
          return {
            ...p,
            currentPrice: liveLtp,
            exitState: {
              ...(state || {}),
              unrealizedPnl: unrealized,
              realizedPnl: realized,
              remainingQty: remQty,
              closed: !stillOpen,
            },
            remainingQty: remQty,
            realizedPnl: realized,
            unrealizedPnl: unrealized,
            pnl,
            pnlPct: entry > 0 && qty > 0 ? (pnl / (entry * qty)) * 100 : p.pnlPct,
            markLive: stillOpen,
            pnlKind: stillOpen ? ('unrealised' as const) : ('realised' as const),
          };
        }
        const pnl = mtmPnl(dir, entry, liveLtp, qty);
        const pnlPct = entry > 0 ? (mtmPnl(dir, entry, liveLtp, 1) / entry) * 100 : null;
        unrealised += pnl;
        return {
          ...p,
          currentPrice: liveLtp,
          pnl,
          pnlPct,
          markLive: true,
          pnlKind: 'unrealised' as const,
        };
      }

      const pnl = p.pnl ?? 0;
      if (hardClosed || closedBook) realised += pnl;
      else unrealised += pnl;
      return {
        ...p,
        markLive: false,
        pnlKind: hardClosed || closedBook ? ('realised' as const) : ('unrealised' as const),
      };
    });

    return {
      ...swing,
      picks,
      totalPnl: realised + unrealised,
      liveRealisedPnl: realised,
      liveUnrealisedPnl: unrealised,
      liveOverlay: true,
    } as SwingReport & {
      liveRealisedPnl: number;
      liveUnrealisedPnl: number;
      liveOverlay: boolean;
    };
  }, [swing, liveActive, liveMarks]);

  const noIntraday = displayIntraday && (!displayIntraday.trades || displayIntraday.trades.length === 0);
  const noSwing = displaySwing && (!displaySwing.picks || displaySwing.picks.length === 0);
  const fromCache = Boolean(intraday?.fromCache || swing?.fromCache);
  const showBody = Boolean(displayIntraday || displaySwing || error);

  return (
    <div className={`space-y-3 ${embedded ? 'eod-book-surface' : ''}`}>
      {!embedded && (
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-3 shadow-sm relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-teal-400 via-cyan-400 to-transparent pointer-events-none" aria-hidden />
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">Intraday Date</span>
            <input
              type="date"
              value={dateStr}
              onChange={(e) => setDateStr(e.target.value)}
              className="min-h-11 text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">Swing Date</span>
            <input
              type="date"
              value={swingDateStr}
              onChange={(e) => setSwingDateStr(e.target.value)}
              className="min-h-11 text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
            />
          </div>
          {fromCache && <span className="desk-pill desk-pill--ok">BOOK · CACHED</span>}
          {liveActive && liveMarks?.marketOpen && (
            <span className="desk-pill desk-pill--ok inline-flex items-center gap-1.5">
              <span className="desk-breathe-dot" aria-hidden />
              LIVE MARKS
            </span>
          )}
          {liveActive && liveMarks && !liveMarks.marketOpen && (
            <span className="desk-pill desk-pill--warn">SESSION MARKS</span>
          )}
          <button
            onClick={() => void fetchReports({ force: false })}
            disabled={loading}
            className="desk-btn-ghost ml-auto min-h-11 px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-wider disabled:opacity-50"
          >
            {loading ? 'LOADING...' : 'REFRESH'}
          </button>
          <button
            onClick={() => void fetchReports({ force: true })}
            disabled={loading}
            className="desk-btn-primary min-h-11 px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-wider disabled:opacity-50"
            title="Rebuild marks/cache; fills missing outcome narratives only (does not reburn existing LLM text)"
          >
            REBUILD
          </button>
        </div>
      </div>
      )}

      {embedded && (
        <div className="flex flex-wrap items-center gap-2 px-0.5">
          {fromCache && <span className="desk-pill desk-pill--ok">BOOK · CACHED</span>}
          {liveActive && liveMarks?.marketOpen && (
            <span className="desk-pill desk-pill--ok inline-flex items-center gap-1.5">
              <span className="desk-breathe-dot" aria-hidden />
              LIVE MARKS · 2s
            </span>
          )}
          {loading && <span className="text-[9px] text-slate-400">Loading book…</span>}
          <span className="text-[9px] text-slate-400">
            Swing date follows EOD date unless changed
          </span>
          <button
            type="button"
            onClick={() => void fetchReports({ force: false })}
            disabled={loading}
            className="desk-btn-ghost ml-auto min-h-11 rounded-md px-2 py-1 text-[11px] font-black uppercase tracking-wider disabled:opacity-50"
          >
            Refresh book
          </button>
          <button
            type="button"
            onClick={() => void fetchReports({ force: true })}
            disabled={loading}
            className="desk-btn-ghost min-h-11 rounded-md px-2 py-1 text-[11px] font-black uppercase tracking-wider disabled:opacity-50"
            title="Rebuild marks/cache; fills missing outcome narratives only"
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

      {(displayIntraday || displaySwing) && (
        <>
          {(() => {
            const i = displayIntraday?.deskCounts;
            const s = displaySwing?.deskCounts;
            if (!i && !s) return null;
            const swingN = Math.max(s?.swing ?? 0, i?.swing ?? 0);
            const intraL = Math.max(i?.intradayLong ?? 0, s?.intradayLong ?? 0);
            const intraS = Math.max(i?.intradayShort ?? 0, s?.intradayShort ?? 0);
            const total = swingN + intraL + intraS;
            const expectOk = total >= 20;
            return (
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-300 border-[0.5px] bg-slate-50 px-3 py-2 text-[10px]">
                <span className="font-black uppercase tracking-wider text-slate-600">Locked desk for EOD</span>
                <span className="desk-pill desk-pill--info">Swing {swingN}</span>
                <span className="desk-pill desk-pill--ok">Intra L {intraL}</span>
                <span className="desk-pill desk-pill--danger">Intra S {intraS}</span>
                <span className={`desk-pill ${expectOk ? 'desk-pill--ok' : 'desk-pill--warn'}`}>
                  Total {total}{expectOk ? '' : ' / expect ~20+'}
                </span>
                {!expectOk && (
                  <span className="text-amber-700">
                    Expect Matrix swing lock + Intra 5 buy / 5 sell after adopt.
                  </span>
                )}
              </div>
            );
          })()}

          {displayIntraday && (
            <OutcomeDesk
              trades={displayIntraday.trades}
              coverage={displayIntraday.missScorecardCoverage}
              isMock={displayIntraday.isMock}
              symbolSource={displayIntraday.symbolSource}
              bookLabel="Intraday"
            />
          )}

          {displaySwing && (
            <OutcomeDesk
              trades={(displaySwing.picks || [])
                .filter((p) => p.missDiagnostic)
                .map((p) => ({
                  symbol: p.symbol,
                  direction: p.direction,
                  entryPrice: p.entryPrice,
                  exitPrice: p.currentPrice ?? p.entryPrice,
                  stopLoss: p.stopLoss,
                  target1: p.target1,
                  target2: p.target2,
                  exitReason: p.exitReason || p.status,
                  qty: p.qty,
                  deployedCapital: p.deployedCapital,
                  pnl: p.pnl,
                  pnlPct: p.pnlPct,
                  missAnalysis: null,
                  missDiagnostic: p.missDiagnostic,
                  outcomeNarrative: p.outcomeNarrative,
                  deskIcSummary: p.deskIcSummary,
                }))}
              isMock={displaySwing.isMock}
              symbolSource={displaySwing.symbolSource}
              bookLabel="Swing"
            />
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 eod-dynamic-grid">
          {/* ── INTRADAY REPORT ── */}
          <div className="eod-panel-card bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-teal-50 to-teal-100/50 px-3 py-2 border-b border-slate-200">
              <h3 className="desk-panel-title text-teal-800">Intraday EOD Report</h3>
              <p className="text-[9px] text-teal-600">
                {displayIntraday?.date ?? dateStr}
                {displayIntraday?.symbolSource ? ` · ${displayIntraday.symbolSource}` : ''}
                {displayIntraday?.isMock ? ' · MOCK' : ''}
                {liveActive && liveMarks?.marketOpen ? ' · LIVE MTM' : ''}
              </p>
            </div>

            {noIntraday ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">No archived intraday picks for this date.</div>
            ) : displayIntraday ? (
              <>
                <AttributionStrip attribution={displayIntraday.attribution} label="Fill / skip" />
                <DayLessonsStrip lessons={displayIntraday.dayLessons} />
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Total P&L</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone(displayIntraday.totalPnl)}`}>
                      <LiveTickNumber value={fmtInr(displayIntraday.totalPnl, 2)} />
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Realised</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displayIntraday as { liveRealisedPnl?: number }).liveRealisedPnl ?? (liveActive ? 0 : displayIntraday.totalPnl))}`}>
                      {fmtInr(
                        (displayIntraday as { liveRealisedPnl?: number }).liveRealisedPnl ??
                          (liveActive ? 0 : displayIntraday.totalPnl),
                        2,
                      )}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Unrealised</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displayIntraday as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? null)}`}>
                      {liveActive
                        ? fmtInr((displayIntraday as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? 0, 2)
                        : '—'}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Deployed</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">₹{displayIntraday.totalDeployed.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-2 gap-2 px-3 pb-2">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Hit Rate</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">{displayIntraday.hitRatePct}%</div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Remaining</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">₹{displayIntraday.remainingCapital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                  </div>
                </div>

                <PortfolioDist
                  title="Intraday portfolio balance"
                  totalDeployed={displayIntraday.totalDeployed || 0}
                  rows={(displayIntraday.trades || []).map((t) => ({
                    symbol: String(t.symbol || ''),
                    qty: t.qty || 0,
                    deployed: t.deployedCapital || 0,
                    pnl: t.pnl,
                    pnlPct: t.pnlPct,
                  }))}
                />

                {/* Hit breakdown */}
                <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-100 text-[11px] sm:text-[9px] overflow-x-auto desk-scroll-x flex-nowrap">
                  <span className="shrink-0 text-slate-500 uppercase tracking-wider font-bold">Breakdown:</span>
                  <span className="shrink-0 bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-bold">T2 {displayIntraday.hitBreakdown?.T2_HIT ?? 0}</span>
                  <span className="shrink-0 bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded font-bold">T1 {displayIntraday.hitBreakdown?.T1_HIT ?? 0}</span>
                  <span className="shrink-0 bg-red-100 text-red-800 px-1.5 py-0.5 rounded font-bold">SL {displayIntraday.hitBreakdown?.SL_HIT ?? 0}</span>
                  <span className="shrink-0 bg-red-50 text-red-700 px-1.5 py-0.5 rounded font-bold">TRAIL {(displayIntraday.hitBreakdown as { TRAIL_SL_HIT?: number })?.TRAIL_SL_HIT ?? 0}</span>
                  <span className="shrink-0 bg-amber-50 text-amber-800 px-1.5 py-0.5 rounded font-bold">PARTIAL {(displayIntraday.hitBreakdown as { PARTIAL_SCALE?: number })?.PARTIAL_SCALE ?? 0}</span>
                  <span className="shrink-0 bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-bold">EOD {displayIntraday.hitBreakdown?.EOD_SQUAREOFF ?? 0}</span>
                </div>

                {/* Trades table */}
                <div className="overflow-x-auto desk-scroll-x">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="text-slate-500 uppercase tracking-wider border-b border-slate-100">
                        <th className="text-left px-2 py-1.5 font-bold">Symbol</th>
                        <th className="text-right px-2 py-1.5 font-bold">Qty</th>
                        <th className="text-right px-2 py-1.5 font-bold">Entry</th>
                        <th className="text-right px-2 py-1.5 font-bold">Mark / Exit</th>
                        <th className="hidden sm:table-cell text-left px-2 py-1.5 font-bold">Scale / Trail</th>
                        <th className="text-center px-2 py-1.5 font-bold">Result</th>
                        <th className="text-right px-2 py-1.5 font-bold">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayIntraday.trades.map((trade, i) => {
                        const badge = exitReasonBadge(trade.exitReason);
                        return (
                          <tr key={`${trade.symbol}-${trade.direction}-${i}`} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-2 py-1.5">
                              <span className={`font-bold ${trade.direction === 'LONG' ? 'text-emerald-700' : 'text-red-700'}`}>
                                {trade.symbol}
                              </span>
                              <span className="text-[8px] text-slate-400 ml-1">{trade.direction}</span>
                              {trade.pnlKind === 'unrealised' && (
                                <span className="ml-1 text-[7px] font-black uppercase text-cyan-600">U</span>
                              )}
                              {trade.pnlKind === 'realised' && (
                                <span className="ml-1 text-[7px] font-black uppercase text-slate-400">R</span>
                              )}
                            </td>
                            <td className="text-right px-2 py-1.5 tabular-nums text-slate-700">
                              {trade.exitState?.remainingQty != null ? (
                                <span title="rem qty / total">
                                  {trade.exitState.remainingQty}/{trade.qty ?? '—'}
                                </span>
                              ) : (trade.qty ?? '—')}
                            </td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{trade.entryPrice}</td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">
                              {trade.markLive ? (
                                <LiveTickNumber value={trade.exitPrice} />
                              ) : (
                                trade.exitPrice
                              )}
                            </td>
                            <td className="hidden sm:table-cell px-2 py-1.5">
                              <ScaleExitCell
                                scaleTrail={trade.scaleTrail}
                                scaleProgress={trade.scaleProgress}
                                exitPlan={trade.exitPlan}
                                exitState={trade.exitState}
                                effectiveStop={trade.effectiveStop}
                                remainingQty={trade.remainingQty}
                                qty={trade.qty}
                              />
                            </td>
                            <td className="text-center px-2 py-1.5">
                              <span className={`${badge.bg} ${badge.txt} px-1 py-0.5 rounded text-[9px] font-bold`}>{badge.label}</span>
                            </td>
                            <td className={`text-right px-2 py-1.5 font-bold tabular-nums ${pnlTone(trade.pnl)}`}>
                              {trade.pnl == null
                                ? (trade.pnlPct != null ? fmtMissSigned(trade.pnlPct, 2, '%') : '—')
                                : trade.markLive
                                  ? <LiveTickNumber value={fmtInr(trade.pnl, 2)} />
                                  : fmtInr(trade.pnl, 2)}
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
              <p className="text-[9px] text-indigo-600">
                {displaySwing?.date ?? dateStr}
                {displaySwing?.symbolSource ? ` · ${displaySwing.symbolSource}` : ''}
                {displaySwing?.isMock ? ' · MOCK' : ''}
                {' · Asset Matrix swing lock (not intradAy)'}
                {liveActive && liveMarks?.marketOpen ? ' · LIVE MTM' : ''}
              </p>
            </div>

            {noSwing ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">
                No locked swing portfolio. Lock swing from Asset Matrix BUY set first.
              </div>
            ) : displaySwing ? (
              <>
                <AttributionStrip attribution={displaySwing.attribution} label="Fill / skip" />
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Total P&L</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone(displaySwing.totalPnl || displaySwing.totalPnlPct)}`}>
                      {displaySwing.totalPnl != null && Math.abs(Number(displaySwing.totalPnl)) >= 0.005
                        ? <LiveTickNumber value={fmtInr(displaySwing.totalPnl, 2)} />
                        : displaySwing.totalPnlPct != null
                          ? fmtMissSigned(displaySwing.totalPnlPct, 2, '%')
                          : '—'}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Realised</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displaySwing as { liveRealisedPnl?: number }).liveRealisedPnl ?? null)}`}>
                      {liveActive
                        ? fmtInr((displaySwing as { liveRealisedPnl?: number }).liveRealisedPnl ?? 0, 2)
                        : '—'}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Unrealised</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displaySwing as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? null)}`}>
                      {liveActive
                        ? fmtInr((displaySwing as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? 0, 2)
                        : '—'}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Win / Loss</div>
                    <div className="desk-metric-value tabular-nums">
                      <span className="text-emerald-700">{displaySwing.winCount}</span>
                      <span className="text-slate-400">/</span>
                      <span className="text-red-700">{displaySwing.lossCount}</span>
                    </div>
                  </div>
                </div>

                <DayLessonsStrip lessons={displaySwing.dayLessons} />

                <PortfolioDist
                  title="Swing portfolio balance"
                  totalDeployed={displaySwing.totalDeployed || 0}
                  rows={(displaySwing.picks || []).map((p) => ({
                    symbol: p.symbol,
                    qty: p.qty || 0,
                    deployed: p.deployedCapital || 0,
                    pnl: p.pnl,
                    pnlPct: p.pnlPct,
                  }))}
                />

                {/* P&L by day bucket */}
                {displaySwing.pnlByDayBucket && Object.keys(displaySwing.pnlByDayBucket).length > 0 && (
                  <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-100 text-[11px] sm:text-[9px] overflow-x-auto desk-scroll-x flex-nowrap">
                    <span className="shrink-0 text-slate-500 uppercase tracking-wider font-bold">P&L by Day:</span>
                    {Object.entries(displaySwing.pnlByDayBucket).map(([bucket, pnl]) => (
                      <span key={bucket} className={`shrink-0 px-1.5 py-0.5 rounded font-bold ${Number(pnl) >= 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
                        Day {bucket}: {fmtInr(Number(pnl), 0)}
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
                        <th className="text-right px-2 py-1.5 font-bold">Qty</th>
                        <th className="text-right px-2 py-1.5 font-bold">Entry</th>
                        <th className="text-right px-2 py-1.5 font-bold">Mark</th>
                        <th className="hidden sm:table-cell text-left px-2 py-1.5 font-bold">Scale / Trail</th>
                        <th className="hidden sm:table-cell text-right px-2 py-1.5 font-bold">Deployed</th>
                        <th className="text-right px-2 py-1.5 font-bold">P&L</th>
                        <th className="hidden sm:table-cell text-right px-2 py-1.5 font-bold">%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displaySwing.picks.map((pick, i) => {
                        const badge = statusBadge(pick.status);
                        return (
                          <tr key={`${pick.symbol}-${i}`} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-2 py-1.5">
                              <span className={`font-bold ${pick.direction === 'LONG' ? 'text-emerald-700' : 'text-red-700'}`}>
                                {pick.symbol}
                              </span>
                              <span className="text-[8px] text-slate-400 ml-1">{pick.direction}</span>
                              {pick.pnlKind === 'unrealised' && (
                                <span className="ml-1 text-[7px] font-black uppercase text-cyan-600">U</span>
                              )}
                              {pick.pnlKind === 'realised' && !pick.skipped && (
                                <span className="ml-1 text-[7px] font-black uppercase text-slate-400">R</span>
                              )}
                            </td>
                            <td className="text-center px-2 py-1.5">
                              <span className={`${badge.bg} ${badge.txt} px-1 py-0.5 rounded text-[9px] font-bold`}>{badge.label}</span>
                            </td>
                            <td className="text-right px-2 py-1.5 tabular-nums text-slate-700">
                              {pick.exitState?.remainingQty != null
                                ? `${pick.exitState.remainingQty}/${pick.qty || '—'}`
                                : (pick.qty || '—')}
                            </td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{pick.entryPrice}</td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">
                              {pick.markLive && pick.currentPrice != null ? (
                                <LiveTickNumber value={pick.currentPrice} />
                              ) : (
                                pick.currentPrice ?? '—'
                              )}
                            </td>
                            <td className="hidden sm:table-cell px-2 py-1.5">
                              <ScaleExitCell
                                scaleTrail={pick.scaleTrail}
                                scaleProgress={pick.scaleProgress}
                                exitPlan={pick.exitPlan}
                                exitState={pick.exitState}
                                effectiveStop={pick.effectiveStop}
                                remainingQty={pick.remainingQty}
                                qty={pick.qty}
                              />
                            </td>
                            <td className="hidden sm:table-cell text-right px-2 py-1.5 tabular-nums text-slate-600">
                              {pick.deployedCapital
                                ? `₹${Number(pick.deployedCapital).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
                                : '—'}
                            </td>
                            <td className={`text-right px-2 py-1.5 font-bold tabular-nums ${pnlTone(pick.pnl ?? pick.pnlPct)}`}>
                              {pick.pnl != null
                                ? (pick.markLive ? <LiveTickNumber value={fmtInr(pick.pnl, 2)} /> : fmtInr(pick.pnl, 2))
                                : '—'}
                            </td>
                            <td className={`hidden sm:table-cell text-right px-2 py-1.5 font-bold tabular-nums ${pnlTone(pick.pnlPct)}`}>
                              {fmtMissSigned(pick.pnlPct, 2, '%')}
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

      {(displayIntraday || displaySwing) && (
        <>
          {/* Best / Worst performer cards */}
          {displaySwing && (displaySwing.bestPerformer || displaySwing.worstPerformer) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {displaySwing.bestPerformer && (
                <div className="bg-gradient-to-r from-emerald-50 to-white border border-emerald-200 rounded-xl p-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="desk-panel-title text-emerald-700">Best Performer · Swing</span>
                  </div>
                  <div className="flex items-end justify-between mt-1">
                    <div>
                      <span className="text-[16px] font-black text-slate-900">{displaySwing.bestPerformer.symbol}</span>
                      <span className="text-[10px] text-slate-500 ml-1">{displaySwing.bestPerformer.direction}</span>
                      <div className="text-[9px] text-slate-500 tabular-nums">
                        Qty {displaySwing.bestPerformer.qty || '—'}
                        {displaySwing.bestPerformer.deployedCapital
                          ? ` · ₹${Number(displaySwing.bestPerformer.deployedCapital).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
                          : ''}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-[16px] font-black tabular-nums ${pnlTone(displaySwing.bestPerformer.pnl ?? displaySwing.bestPerformer.pnlPct)}`}>
                        {displaySwing.bestPerformer.pnl != null
                          ? fmtInr(displaySwing.bestPerformer.pnl, 2)
                          : fmtMissSigned(displaySwing.bestPerformer.pnlPct, 2, '%')}
                      </div>
                      <div className={`text-[10px] font-bold tabular-nums ${pnlTone(displaySwing.bestPerformer.pnlPct)}`}>
                        {fmtMissSigned(displaySwing.bestPerformer.pnlPct, 2, '%')}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {displaySwing.worstPerformer && (
                <div className="bg-gradient-to-r from-red-50 to-white border border-red-200 rounded-xl p-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                    <span className="desk-panel-title text-red-700">Worst Performer · Swing</span>
                  </div>
                  <div className="flex items-end justify-between mt-1">
                    <div>
                      <span className="text-[16px] font-black text-slate-900">{displaySwing.worstPerformer.symbol}</span>
                      <span className="text-[10px] text-slate-500 ml-1">{displaySwing.worstPerformer.direction}</span>
                      <div className="text-[9px] text-slate-500 tabular-nums">
                        Qty {displaySwing.worstPerformer.qty || '—'}
                        {displaySwing.worstPerformer.deployedCapital
                          ? ` · ₹${Number(displaySwing.worstPerformer.deployedCapital).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
                          : ''}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-[16px] font-black tabular-nums ${pnlTone(displaySwing.worstPerformer.pnl ?? displaySwing.worstPerformer.pnlPct)}`}>
                        {displaySwing.worstPerformer.pnl != null
                          ? fmtInr(displaySwing.worstPerformer.pnl, 2)
                          : fmtMissSigned(displaySwing.worstPerformer.pnlPct, 2, '%')}
                      </div>
                      <div className={`text-[10px] font-bold tabular-nums ${pnlTone(displaySwing.worstPerformer.pnlPct)}`}>
                        {fmtMissSigned(displaySwing.worstPerformer.pnlPct, 2, '%')}
                      </div>
                    </div>
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