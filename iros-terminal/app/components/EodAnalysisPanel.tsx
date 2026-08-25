'use client';

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { LiveTickNumber } from '@/lib/desk-motion';
import { subscribeLiveDesk, type LiveDeskSnapshot } from '@/lib/live-desk';

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
  economicR?: number | null;
  pathR?: number | null;
  movePct: number | null;
  gapToT1Pct: number | null;
  gapToT2Pct: number | null;
  stopUtilization: number | null;
  plannedRr: number | null;
  riskPerShare: number | null;
  maePct: number | null;
  mfePct: number | null;
  mfeR?: number | null;
  maeR?: number | null;
  stopEff: number | null;
  falsePositive: boolean;
  holdingMins: number | null;
  source: 'LEVELS' | 'SCORECARD' | 'SKIP' | string;
  exitSource?: string;
};

type TradeLineage = {
  source?: string | null;
  filterStage?: string | null;
  score?: number | null;
  scoreComponents?: Record<string, unknown> | null;
  lockRank?: number | null;
  selectionReason?: string | null;
  verdict?: string | null;
  sector?: string | null;
  levelsSource?: string | null;
  triggeredAt?: string | null;
  executedFills?: unknown;
  exitPathTag?: string | null;
  triggerSource?: string | null;
};

type IntradayTrade = {
  symbol: string;
  direction: string;
  entryPrice: number;
  exitPrice: number | null;
  stopLoss?: number | null;
  target1?: number | null;
  target2?: number | null;
  exitReason: string;
  qty: number;
  deployedCapital: number;
  plannedCapital?: number | null;
  pnl: number | null;
  pnlPct: number | null;
  missAnalysis: string | null;
  missDiagnostic?: MissDiagnostic | null;
  outcomeNarrative?: string | null;
  deskIcSummary?: { decision?: string; conviction?: number; oneLiner?: string } | null;
  /** Live overlay (session only) — not from book cache */
  markLive?: boolean;
  pnlKind?: 'realised' | 'unrealised' | 'skipped';
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
    economicR?: number | null;
    pathR?: number | null;
    profitGuardActive?: boolean | null;
    initialStop?: number | null;
    closed?: boolean;
  } | null;
  exitPlan?: { mode?: string; notes?: string[]; policyVersion?: string; legs?: { r?: number }[] } | null;
  scaleTrail?: boolean;
  scaleProgress?: string | null;
  deskProgress?: string | null;
  deskExitLabel?: string | null;
  executionStatus?: string | null;
  outcomeBucket?: string | null;
  skipped?: boolean;
  mfeR?: number | null;
  maeR?: number | null;
  economicR?: number | null;
  pathR?: number | null;
  effectiveStopR?: number | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  rMultiple?: number | null;
  riskPerShare?: number | null;
  lineage?: TradeLineage | null;
};

type IntradayReport = {
  date: string;
  capital: number;
  totalDeployed: number;
  totalPnl: number | null;
  remainingCapital: number;
  hitBreakdown: { T1_HIT: number; T2_HIT: number; SL_HIT: number; EOD_SQUAREOFF: number };
  hitRatePct: number;
  missCount?: number;
  hitCount?: number;
  missScorecardCoverage?: number;
  isMock?: boolean;
  symbolSource?: string;
  archiveStatus?: string;
  executionPolicy?: string;
  executionBasis?: string;
  marketPhase?: string;
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
  exitPrice?: number | null;
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
  pnlKind?: 'realised' | 'unrealised' | 'skipped';
  /** Scale-trail state — from backend SCALE_TRAIL mode */
  remainingQty?: number | null;
  effectiveStop?: number | null;
  exitPlan?: { mode?: string; notes?: string[]; policyVersion?: string; legs?: { r?: number }[] } | null;
  exitState?: {
    legsFilled?: Array<number | { r?: number | string }>;
    remainingQty?: number | null;
    effectiveStop?: number | null;
    realizedPnl?: number | null;
    unrealizedPnl?: number | null;
    rMultiple?: number | null;
    economicR?: number | null;
    pathR?: number | null;
    profitGuardActive?: boolean | null;
    initialStop?: number | null;
    closed?: boolean;
  } | null;
  scaleTrail?: boolean;
  scaleProgress?: string | null;
  deskProgress?: string | null;
  deskExitLabel?: string | null;
  executionStatus?: string | null;
  outcomeBucket?: string | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  rMultiple?: number | null;
  economicR?: number | null;
  pathR?: number | null;
  mfeR?: number | null;
  maeR?: number | null;
  riskPerShare?: number | null;
  score?: number | null;
  selectionReason?: string | null;
  lineage?: TradeLineage | null;
};

type SwingReport = {
  date: string;
  totalPicks: number;
  activePicks?: number;
  skippedNotTriggered?: number;
  totalDeployed: number;
  totalPnl: number | null;
  totalPnlPct: number | null;
  winCount: number;
  lossCount: number;
  hitRatePct?: number;
  bestPerformer: SwingPick | null;
  worstPerformer: SwingPick | null;
  pnlByDayBucket: Record<string, number>;
  picks: SwingPick[];
  isMock?: boolean;
  symbolSource?: string;
  archiveStatus?: string;
  executionPolicy?: string;
  executionBasis?: string;
  marketPhase?: string;
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

function policyTag(notes?: string[] | null): string | null {
  if (!notes?.length) return null;
  const parts: string[] = [];
  if (notes.includes('be_after_1r_scale')) parts.push('BE after +1R scale');
  else if (notes.includes('be_at_1r')) parts.push('1R BE');
  else if (notes.includes('be_at_0p25r')) parts.push('0.25R BE');
  if (notes.includes('max_stop_0p5pct')) parts.push('SL≤0.5%');
  return parts.length ? parts.join(' · ') : null;
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
  exitPlan?: { mode?: string; notes?: string[]; policyVersion?: string } | null;
  exitState?: {
    remainingQty?: number | null;
    effectiveStop?: number | null;
    profitGuardActive?: boolean | null;
  } | null;
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
  const stopLabel = exitState?.profitGuardActive === false ? 'initial SL' : 'trail SL';
  const policy = policyTag(exitPlan?.notes) || exitPlan?.policyVersion || null;
  return (
    <div className="flex flex-col items-start gap-0.5 min-w-[9rem]">
      <span className="text-[8px] font-mono tabular-nums text-slate-700 whitespace-nowrap">
        {scaleProgress || 'SCALE_TRAIL'}
      </span>
      {policy && (
        <span className="text-[7px] text-emerald-700 font-bold tabular-nums">{policy}</span>
      )}
      <span className="text-[7px] text-amber-700 font-bold tabular-nums">
        {rem != null ? `rem ${rem}${qty != null ? `/${qty}` : ''}` : null}
        {trail != null ? `${rem != null ? ' · ' : ''}${stopLabel} ${Number(trail).toFixed(2)}` : null}
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

/** Book P&L → WIN / LOSS / FLAT / SKIPPED (mirrors backend outcome_bucket). */
function bookOutcomeBucket(pnl: number | null | undefined, executionStatus?: string | null, skipped?: boolean): string {
  if (skipped || String(executionStatus || '').toUpperCase() === 'NOT_TRIGGERED') return 'SKIPPED';
  const p = Number(pnl);
  if (!Number.isFinite(p)) return 'FLAT';
  if (p > 0) return 'WIN';
  if (p < 0) return 'LOSS';
  return 'FLAT';
}

function economicRFromRow(row: {
  pnl?: number | null;
  economicR?: number | null;
  rMultiple?: number | null;
  riskPerShare?: number | null;
  qty?: number | null;
  entryPrice?: number | null;
  stopLoss?: number | null;
}): number | null {
  const risk =
    row.riskPerShare != null && Number.isFinite(Number(row.riskPerShare))
      ? Number(row.riskPerShare)
      : row.entryPrice != null && row.stopLoss != null
        ? Math.abs(Number(row.entryPrice) - Number(row.stopLoss))
        : null;
  const qty = Number(row.qty) || 0;
  const pnl = Number(row.pnl);
  if (risk != null && risk > 0 && qty > 0 && Number.isFinite(pnl)) {
    return Math.round((pnl / (risk * qty)) * 1000) / 1000;
  }
  if (row.economicR != null && Number.isFinite(Number(row.economicR))) return Number(row.economicR);
  if (row.rMultiple != null && Number.isFinite(Number(row.rMultiple))) return Number(row.rMultiple);
  return null;
}

function deriveCanonicalTrade<T extends {
  pnl?: number | null;
  outcomeBucket?: string | null;
  executionStatus?: string | null;
  skipped?: boolean;
  economicR?: number | null;
  rMultiple?: number | null;
  pathR?: number | null;
  riskPerShare?: number | null;
  qty?: number | null;
  entryPrice?: number | null;
  stopLoss?: number | null;
}>(row: T): T {
  const bucket = bookOutcomeBucket(row.pnl, row.executionStatus, row.skipped);
  const econ = bucket === 'SKIPPED' ? null : economicRFromRow(row);
  return {
    ...row,
    outcomeBucket: bucket,
    economicR: econ,
    rMultiple: econ,
  };
}

function deriveIntradayHeadlines(base: IntradayReport, trades: IntradayTrade[]): IntradayReport {
  const derived = trades.map((t) => {
    const row = deriveCanonicalTrade(t);
    if (row.outcomeBucket !== 'SKIPPED') return row;
    return {
      ...row,
      deployedCapital: 0,
      pnl: 0,
      pnlPct: 0,
      realizedPnl: 0,
      unrealizedPnl: 0,
      remainingQty: 0,
      markLive: false,
      pnlKind: 'skipped' as const,
    };
  });
  const wins = derived.filter((t) => t.outcomeBucket === 'WIN').length;
  const losses = derived.filter((t) => t.outcomeBucket === 'LOSS').length;
  const skipped = derived.filter((t) => t.outcomeBucket === 'SKIPPED').length;
  const triggered = derived.length - skipped;
  const totalPnl = derived.reduce((s, t) => s + (Number(t.pnl) || 0), 0);
  const deployed = derived.reduce((s, t) => s + (Number(t.deployedCapital) || 0), 0);
  return {
    ...base,
    trades: derived,
    totalPnl,
    hitRatePct: triggered ? Math.round((wins / triggered) * 1000) / 10 : 0,
    hitCount: wins,
    missCount: losses,
    attribution: {
      locked: derived.length,
      triggered,
      skipped,
      wins,
      losses,
      deployed,
    },
  };
}

function deriveSwingHeadlines(base: SwingReport, picks: SwingPick[]): SwingReport {
  const derived = picks.map((p) => {
    const row = deriveCanonicalTrade(p);
    if (row.outcomeBucket !== 'SKIPPED') return row;
    return {
      ...row,
      deployedCapital: 0,
      pnl: 0,
      pnlPct: 0,
      realizedPnl: 0,
      unrealizedPnl: 0,
      remainingQty: 0,
      markLive: false,
      pnlKind: 'skipped' as const,
    };
  });
  const active = derived.filter((p) => p.outcomeBucket !== 'SKIPPED' && !p.skipped && p.status !== 'NOT_TRIGGERED');
  const wins = active.filter((p) => p.outcomeBucket === 'WIN');
  const losses = active.filter((p) => p.outcomeBucket === 'LOSS');
  const totalPnl = active.reduce((s, p) => s + (Number(p.pnl) || 0), 0);
  const deployed = active.reduce((s, p) => s + (Number(p.deployedCapital) || 0), 0);
  const withPnl = active.filter((p) => p.pnl != null && Number.isFinite(Number(p.pnl)));
  const best = withPnl.length
    ? withPnl.reduce((a, b) => (Number(a.pnl) >= Number(b.pnl) ? a : b))
    : null;
  const worst = withPnl.length
    ? withPnl.reduce((a, b) => (Number(a.pnl) <= Number(b.pnl) ? a : b))
    : null;
  return {
    ...base,
    picks: derived,
    totalPnl,
    activePicks: active.length,
    winCount: wins.length,
    lossCount: losses.length,
    hitRatePct: active.length ? Math.round((wins.length / active.length) * 1000) / 10 : 0,
    bestPerformer: best,
    worstPerformer: worst,
    attribution: {
      locked: derived.length,
      triggered: active.length,
      skipped: derived.length - active.length,
      wins: wins.length,
      losses: losses.length,
      deployed,
    },
  };
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
  entryDate?: string | null;
  currentPrice?: number | null;
  ltp?: number | null;
  entryPrice?: number | null;
  approxQty?: number | null;
  status?: string | null;
  closed?: boolean | null;
  remainingQty?: number | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  triggered?: boolean | null;
  executionStatus?: string | null;
  outcome?: { hitLevel?: string | null; ltp?: number | null; pctChange?: number | null; scaleTrail?: boolean; label?: string | null; pnl?: number | null } | null;
  exitPlan?: { mode?: string; notes?: string[]; policyVersion?: string } | null;
  exitState?: { remainingQty?: number | null; effectiveStop?: number | null; realizedPnl?: number | null; unrealizedPnl?: number | null; closed?: boolean } | null;
};

type LivePricesDesk = {
  long?: LivePriceRow[];
  short?: LivePriceRow[];
  sessionDate?: string;
  date?: string;
  marketOpen?: boolean;
  updatedAt?: string;
};

type SessionDesk = {
  long?: LivePriceRow[];
  short?: LivePriceRow[];
  sessionDate?: string;
  locked?: {
    long?: LivePriceRow[];
    short?: LivePriceRow[];
    sessionDate?: string;
  };
};

type LiveMark = {
  ltp: number;
  hitLevel: string | null;
  remainingQty?: number | null;
  realizedPnl?: number | null;
  unrealizedPnl?: number | null;
  closed?: boolean | null;
  status?: string | null;
  triggered?: boolean | null;
  executionStatus?: string | null;
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

function isLiveSessionFill(mark: LiveMark | null | undefined): boolean {
  if (!mark) return false;
  if (mark.triggered === true) return true;
  const exec = String(mark.executionStatus || '').toUpperCase();
  if (exec === 'TRIGGERED' || exec === 'EXECUTED' || exec === 'FILLED') return true;
  if (Number(mark.remainingQty) > 0) return true;
  if (mark.closed === false) return true;
  if (mark.realizedPnl != null && Number.isFinite(Number(mark.realizedPnl))) return true;
  const status = String(mark.status || '').toUpperCase();
  if (status.includes('RUNNING') || status.includes('STOP') || status.includes('TARGET') || status.includes('TRAIL')) {
    return true;
  }
  return false;
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
    case 'ADVERSE':
    case 'ENTRY_FAILURE':
    case 'FAKE_BREAKOUT':
    case 'FAILED_BREAKOUT':
    case 'FAILED_FOLLOWTHROUGH':
    case 'STOP_BEFORE_FOLLOWTHROUGH':
      return 'desk-pill--danger';
    case 'STALLED_TRADE':
    case 'STALL':
    case 'GOOD_ENTRY_BAD_EXIT':
      return 'desk-pill--warn';
    case 'PARTIAL_FOLLOWTHROUGH':
    case 'TRAIL_CAPTURED':
    case 'TRAIL_LOCKED_GAINS':
      return 'desk-pill--info';
    case 'GOOD_TREND':
    case 'TREND_FOLLOWTHROUGH':
      return 'desk-pill--ok';
    default:
      return 'desk-pill--muted';
  }
}

function OutcomeRow({ trade }: { trade: IntradayTrade }) {
  const d: MissDiagnostic = trade.missDiagnostic || {
    isMiss: trade.outcomeBucket === 'LOSS',
    isHit: trade.outcomeBucket === 'WIN',
    isSkip: trade.outcomeBucket === 'SKIPPED',
    exitReason: trade.exitReason || 'OPEN',
    rootCause: null,
    factors: [],
    rMultiple: trade.economicR ?? trade.rMultiple ?? null,
    economicR: trade.economicR ?? null,
    pathR: trade.pathR ?? null,
    movePct: trade.pnlPct ?? null,
    gapToT1Pct: null,
    gapToT2Pct: null,
    stopUtilization: null,
    plannedRr: null,
    riskPerShare: trade.riskPerShare ?? null,
    maePct: null,
    mfePct: null,
    stopEff: null,
    falsePositive: false,
    holdingMins: null,
    source: 'LIVE_MARK',
  };
  const econR = trade.economicR ?? trade.rMultiple ?? d.economicR ?? d.rMultiple;
  const pathR = trade.pathR ?? d.pathR;
  const showPath = pathR != null && econR != null && Math.abs(Number(pathR) - Number(econR)) > 0.001;
  const rBad = (econR ?? 0) < 0;
  const exitLabel = trade.deskExitLabel || trade.exitReason;
  const exitTone =
    exitLabel === 'INITIAL_SL' || exitLabel === 'SL_HIT' || exitLabel === 'TRAIL_STOP' || exitLabel === 'TRAIL_SL_HIT'
      ? 'desk-pill--danger'
      : exitLabel === 'EOD_SQUAREOFF' || exitLabel === 'SKIPPED' || exitLabel === 'NOT_TRIGGERED'
        ? 'desk-pill--warn'
        : exitLabel === 'PARTIAL_SCALE'
          ? 'desk-pill--info'
          : 'desk-pill--ok';
  const ladder = trade.deskProgress || trade.scaleProgress;
  const ic = trade.deskIcSummary?.decision;
  const lineage = trade.lineage;
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
          {lineage?.lockRank != null && (
            <span className="ml-1 text-[8px] font-bold text-slate-400" title="Lock rank">
              #{lineage.lockRank}
            </span>
          )}
        </td>
        <td className={`px-2 py-1.5 font-semibold ${trade.direction === 'LONG' ? 'text-emerald-700' : 'text-red-600'}`}>
          {trade.direction}
        </td>
        <td className="px-2 py-1.5 text-right tabular-nums text-slate-700">{trade.qty ?? '—'}</td>
        <td className="px-2 py-1.5">
          <div className="flex flex-col gap-0.5">
            <span className={`desk-pill ${exitTone}`}>{exitLabel}</span>
            {trade.exitPrice != null && (
              <span className="text-[8px] font-semibold tabular-nums text-slate-500">
                @ {Number(trade.exitPrice).toFixed(2)}
              </span>
            )}
            {trade.outcomeBucket && (
              <span className="text-[8px] font-bold uppercase tracking-wider text-slate-400">
                {trade.executionStatus ? `${trade.executionStatus} · ` : ''}
                {trade.outcomeBucket}
              </span>
            )}
          </div>
        </td>
        <td className={`px-2 py-1.5 text-right tabular-nums font-bold ${rBad ? 'text-red-600' : 'text-emerald-700'}`}>
          <div>{fmtMissSigned(econR, 2, 'R')}</div>
          {showPath && (
            <div className="text-[8px] font-semibold text-slate-400" title="Path R (price move / risk)">
              path {fmtMissSigned(pathR, 2, 'R')}
            </div>
          )}
        </td>
        <td className={`px-2 py-1.5 text-right tabular-nums ${rBad ? 'text-red-600' : 'text-slate-700'}`}>
          {fmtMissSigned(d.movePct, 2, '%')}
        </td>
        <td className="hidden sm:table-cell px-2 py-1.5 text-right tabular-nums text-slate-600">
          {trade.maeR != null ? fmtMissSigned(trade.maeR, 2, 'R') : fmtMissNum(d.maePct, 2)}
        </td>
        <td className="hidden sm:table-cell px-2 py-1.5 text-right tabular-nums text-slate-600">
          {trade.mfeR != null ? fmtMissSigned(Math.max(0, trade.mfeR), 2, 'R') : fmtMissNum(d.mfePct, 2)}
        </td>
        <td className="hidden sm:table-cell px-2 py-1.5">
          <span className={`desk-pill ${rootCauseTone(d.rootCause)}`} title={ladder || undefined}>
            {(d.rootCause || '—').replace(/_/g, ' ')}
          </span>
          {ladder && (
            <div className="mt-0.5 text-[8px] font-semibold tabular-nums text-slate-400 leading-tight max-w-[140px]">
              {ladder}
            </div>
          )}
        </td>
        <td className={`px-2 py-1.5 text-right tabular-nums font-bold ${pnlTone(trade.pnl ?? trade.pnlPct)}`}>
          {trade.outcomeBucket === 'SKIPPED'
            ? fmtInr(0, 0)
            : trade.pnl == null
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
                <span className="inline-block max-w-[9rem] whitespace-normal break-words text-center leading-tight">
                  {f.replace(/_/g, ' ')}
                </span>
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
            <th className="px-2 py-2 text-left font-bold">Exit type / price</th>
            <th className="px-2 py-2 text-right font-bold">R</th>
            <th className="px-2 py-2 text-right font-bold">Move%</th>
            <th className="hidden sm:table-cell px-2 py-2 text-right font-bold">MAE (R)</th>
            <th className="hidden sm:table-cell px-2 py-2 text-right font-bold">MFE (R)</th>
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
  // Book outcomeBucket is authoritative — not path isHit/isMiss
  const misses = trades
    .filter((t) => t.outcomeBucket === 'LOSS' || t.outcomeBucket === 'FLAT')
    .slice()
    .sort((a, b) => (a.economicR ?? a.rMultiple ?? 0) - (b.economicR ?? b.rMultiple ?? 0));
  const hits = trades
    .filter((t) => t.outcomeBucket === 'WIN')
    .slice()
    .sort((a, b) => (b.economicR ?? b.rMultiple ?? 0) - (a.economicR ?? a.rMultiple ?? 0));
  const skips = trades
    .filter((t) => t.outcomeBucket === 'SKIPPED' || Boolean(t.missDiagnostic?.isSkip) || ['NOT_TRIGGERED', 'NO_MARK'].includes(t.exitReason))
    .slice()
    .sort((a, b) => a.symbol.localeCompare(b.symbol));

  if (!misses.length && !hits.length && !skips.length) return null;

  return (
    <div className="eod-panel-card space-y-0 overflow-hidden rounded-xl border border-slate-300 border-[0.5px] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
        <span className="desk-panel-title text-slate-900">Outcome Desk · {bookLabel}</span>
        <span className="desk-pill desk-pill--danger">{misses.length} loss/flat</span>
        <span className="desk-pill desk-pill--ok">{hits.length} win</span>
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
          {bookLabel} lock · Book outcome · Economic R
        </span>
      </div>

      {misses.length > 0 && (
        <div>
          <div className="border-b border-slate-100 bg-red-50/40 px-3 py-1.5 text-[9px] font-black uppercase tracking-wider text-red-700">
            Book LOSS / FLAT
          </div>
          <OutcomeTable rows={misses} />
        </div>
      )}

      {hits.length > 0 && (
        <div>
          <div className="border-b border-slate-100 bg-emerald-50/40 px-3 py-1.5 text-[9px] font-black uppercase tracking-wider text-emerald-700">
            Book WIN
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
    const timeoutMs = force ? 60_000 : 45_000;

    const loadOne = async <T,>(url: string, label: string): Promise<T | null> => {
      const ctrl = new AbortController();
      const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
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
              ? `${label} timed out (${force ? '60s' : '45s'})`
              : err.message
            : `${label} failed`;
        setError((prev) => (prev ? `${prev} · ${msg}` : msg));
        return null;
      } finally {
        window.clearTimeout(timer);
      }
    };

    try {
      const [intraData, swingData] = await Promise.all([
        loadOne<IntradayReport>(`/api/reports/eod-intraday${buildQs(dateStr)}`, 'Intraday'),
        loadOne<SwingReport>(`/api/reports/eod-swing${buildQs(swingDate)}`, 'Swing'),
      ]);
      if (intraData) setIntraday(intraData);
      else setIntraday(null);
      if (swingData) setSwing(swingData);
      else setSwing(null);
      if (!intraData && !swingData) {
        setError((prev) => prev || 'Book P&L failed to load');
      }
    } finally {
      setLoading(false);
    }
  }, [dateStr, swingDateStr]);

  // forceBookRebuild is read only when refreshToken/date triggers — parent may clear it without a second fetch
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch synchronizes this client panel with the selected report date
    void fetchReports({ force: forceBookRebuild });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot force paired with refreshToken
  }, [fetchReports, refreshToken]);

  // Market-hours live marks — overlay LTP / MTM without rewriting book cache
  useEffect(() => {
    if (!isTodayBook) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear a now-inapplicable live overlay when browsing historical books
      setLiveMarks(null);
      return;
    }
    let cancelled = false;

    const loadLive = async (snapshot: LiveDeskSnapshot) => {
      if (liveBusy.current) return;
      liveBusy.current = true;
      try {
        const lp = snapshot['live-prices'] as LivePricesDesk;
        const sw = snapshot['swing-session'] as SessionDesk;
        const intra = snapshot['intraday-session'] as SessionDesk;
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
              triggered: row.triggered ?? null,
              executionStatus: row.executionStatus ?? null,
            };
            bySymbol[sym] = ltp;
          }
        };
        const planRows = [...(lp?.long || []), ...(lp?.short || [])] as LivePriceRow[];
        const livePriceDate = String(
          lp?.sessionDate || lp?.date || planRows.find((row) => row.entryDate)?.entryDate || '',
        ).slice(0, 10);
        // A fixed plan can continue streaming fresh prices after its trade date.  Do not
        // let those prior-day symbols/exit states contaminate today's EOD book.
        if (livePriceDate === dateStr) {
          ingestPlan(lp?.long as LivePriceRow[] | undefined, 'LONG');
          ingestPlan(lp?.short as LivePriceRow[] | undefined, 'SHORT');
        }

        const ingestSession = (rows: LivePriceRow[] | undefined, fallbackDir: string) => {
          for (const row of rows || []) {
            const sym = String(row.symbol || '').toUpperCase();
            if (!sym) continue;
            const ltp = Number(row.currentPrice ?? row.ltp ?? row.entryPrice);
            if (!Number.isFinite(ltp) || ltp <= 0) continue;
            bySymbol[sym] = Number(row.currentPrice ?? row.ltp) > 0 ? Number(row.currentPrice ?? row.ltp) : ltp;
            const dir = String(row.direction || fallbackDir).toUpperCase();
            const key = markKey(sym, dir);
            const prev = byKey[key];
            byKey[key] = {
              ltp: Number(row.currentPrice ?? row.ltp) > 0 ? Number(row.currentPrice ?? row.ltp) : (prev?.ltp ?? ltp),
              hitLevel: prev?.hitLevel ?? (row.outcome?.hitLevel != null ? String(row.outcome.hitLevel) : null),
              remainingQty: row.remainingQty ?? row.exitState?.remainingQty ?? prev?.remainingQty ?? null,
              realizedPnl: row.realizedPnl ?? row.exitState?.realizedPnl ?? prev?.realizedPnl ?? null,
              unrealizedPnl: row.unrealizedPnl ?? row.exitState?.unrealizedPnl ?? prev?.unrealizedPnl ?? null,
              closed: row.closed ?? row.exitState?.closed ?? prev?.closed ?? null,
              status: row.status ?? prev?.status ?? null,
              triggered: row.triggered ?? prev?.triggered ?? null,
              executionStatus: row.executionStatus ?? prev?.executionStatus ?? null,
            };
          }
        };
        if (String(sw?.sessionDate || '').slice(0, 10) === dateStr) {
          ingestSession([...(sw?.long || []), ...(sw?.short || [])] as LivePriceRow[], 'LONG');
        }
        if (String(intra?.sessionDate || intra?.locked?.sessionDate || '').slice(0, 10) === dateStr) {
          ingestSession(
            [...(intra?.long || []), ...(intra?.short || []), ...(intra?.locked?.long || []), ...(intra?.locked?.short || [])] as LivePriceRow[],
            'LONG',
          );
        }

        const marketOpen = Boolean(lp?.marketOpen);
        setLiveMarks({
          marketOpen,
          updatedAt: typeof lp?.updatedAt === 'string' ? lp.updatedAt : snapshot.receivedAt,
          byKey,
          bySymbol,
        });
      } catch {
        /* keep last good marks */
      } finally {
        liveBusy.current = false;
      }
    };

    const unsubscribe = subscribeLiveDesk((snapshot) => {
      if (document.visibilityState === 'visible' && navigator.onLine) void loadLive(snapshot);
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [isTodayBook, dateStr]);

  const liveActive = Boolean(isTodayBook && liveMarks && (liveMarks.marketOpen || Object.keys(liveMarks.bySymbol).length > 0));

  const displayIntraday = useMemo(() => {
    if (!intraday) return null;
    if (!liveActive || !liveMarks) {
      return deriveIntradayHeadlines(intraday, intraday.trades || []);
    }

    let realised = 0;
    let unrealised = 0;
    const trades = (intraday.trades || []).map((rawT) => {
      const sym = String(rawT.symbol || '').toUpperCase();
      const dir = String(rawT.direction || 'LONG').toUpperCase();
      const live = liveMarks.byKey[markKey(sym, dir)] || (liveMarks.bySymbol[sym] != null
        ? { ltp: liveMarks.bySymbol[sym], hitLevel: null as string | null }
        : null);
      const bookSkip = Boolean(
        rawT.skipped || rawT.outcomeBucket === 'SKIPPED' || String(rawT.executionStatus || '').toUpperCase() === 'NOT_TRIGGERED',
      );
      if (bookSkip && !isLiveSessionFill(live)) {
        return {
          ...rawT,
          deployedCapital: 0,
          pnl: 0,
          pnlPct: 0,
          realizedPnl: 0,
          unrealizedPnl: 0,
          remainingQty: 0,
          exitState: null,
          markLive: false,
          pnlKind: 'skipped' as const,
        };
      }
      const t = bookSkip
        ? {
            ...rawT,
            skipped: false,
            executionStatus: 'TRIGGERED',
            outcomeBucket: undefined,
            deployedCapital: rawT.plannedCapital || rawT.deployedCapital || 0,
          }
        : rawT;

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
          const realized = Number(live.realizedPnl ?? state?.realizedPnl ?? t.realizedPnl ?? t.pnl ?? 0);
          realised += realized;
          return {
            ...t,
            exitPrice: live.ltp,
            exitReason: exitReasonFromHit(live.hitLevel, reason),
            exitState: {
              ...(state || {}),
              realizedPnl: realized,
              unrealizedPnl: 0,
              remainingQty: 0,
              closed: true,
            },
            remainingQty: 0,
            realizedPnl: realized,
            unrealizedPnl: 0,
            markLive: false,
            pnlKind: 'realised' as const,
            pnl: realized,
            pnlPct: entry > 0 && qty > 0 ? (realized / (entry * qty)) * 100 : t.pnlPct,
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

        const realized =
          live.realizedPnl != null && Number.isFinite(Number(live.realizedPnl))
            ? Number(live.realizedPnl)
            : remQty > 0 && liveMarks.marketOpen && (reason === 'EOD_SQUAREOFF' || Boolean(state?.closed))
              ? 0
              : Number(state?.realizedPnl ?? t.realizedPnl ?? 0);

        const unrealized =
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
      ...deriveIntradayHeadlines(intraday, trades),
      remainingCapital: (intraday.capital || 0) + realised + unrealised,
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
    if (!liveActive || !liveMarks) {
      return deriveSwingHeadlines(swing, swing.picks || []);
    }

    let realised = 0;
    let unrealised = 0;
    const picks = (swing.picks || []).map((rawP) => {
      const sym = String(rawP.symbol || '').toUpperCase();
      const dir = String(rawP.direction || 'LONG').toUpperCase();
      const live =
        liveMarks.byKey[markKey(sym, dir)] ||
        (liveMarks.bySymbol[sym] != null
          ? ({ ltp: liveMarks.bySymbol[sym], hitLevel: null } as LiveMark)
          : null);
      const bookSkip = Boolean(
        rawP.skipped || rawP.outcomeBucket === 'SKIPPED' || String(rawP.executionStatus || '').toUpperCase() === 'NOT_TRIGGERED',
      );
      if (bookSkip && !isLiveSessionFill(live)) {
        return {
          ...rawP,
          deployedCapital: 0,
          pnl: 0,
          pnlPct: 0,
          realizedPnl: 0,
          unrealizedPnl: 0,
          remainingQty: 0,
          markLive: false,
          pnlKind: 'skipped' as const,
        };
      }
      const p = bookSkip
        ? {
            ...rawP,
            skipped: false,
            executionStatus: 'TRIGGERED',
            outcomeBucket: undefined,
            deployedCapital: rawP.deployedCapital || 0,
          }
        : rawP;
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
          const realized =
            live?.realizedPnl != null && Number.isFinite(Number(live.realizedPnl))
              ? Number(live.realizedPnl)
              : remQty > 0 && liveMarks.marketOpen && (reason === 'EOD_SQUAREOFF' || Boolean(state?.closed))
                ? 0
                : Number(state?.realizedPnl ?? p.realizedPnl ?? 0);
          const unrealized =
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
      ...deriveSwingHeadlines(swing, picks),
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
  const intradayModeledBooked = (displayIntraday?.trades || []).reduce(
    (sum, trade) => sum + (Number(trade.realizedPnl) || 0), 0,
  );
  const intradayModeledOpen = (displayIntraday?.trades || []).reduce(
    (sum, trade) => sum + (Number(trade.unrealizedPnl) || 0), 0,
  );
  const swingModeledBooked = (displaySwing?.picks || []).reduce(
    (sum, pick) => sum + (pick.skipped ? 0 : (Number(pick.realizedPnl ?? (pick.pnlKind === 'realised' ? pick.pnl : 0)) || 0)), 0,
  );
  const swingModeledOpen = (displaySwing?.picks || []).reduce(
    (sum, pick) => sum + (pick.skipped ? 0 : (Number(pick.unrealizedPnl ?? (pick.pnlKind === 'unrealised' ? pick.pnl : 0)) || 0)), 0,
  );

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
            const expectOk = total >= 10;
            return (
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-300 border-[0.5px] bg-slate-50 px-3 py-2 text-[10px]">
                <span className="font-black uppercase tracking-wider text-slate-600">Locked desk for EOD</span>
                <span className="desk-pill desk-pill--info">Swing {swingN}</span>
                <span className="desk-pill desk-pill--ok">Intra L {intraL}</span>
                <span className="desk-pill desk-pill--danger">Intra S {intraS}</span>
                <span className={`desk-pill ${expectOk ? 'desk-pill--ok' : 'desk-pill--warn'}`}>
                  Total {total}{expectOk ? '' : ' / configured max 10'}
                </span>
                {!expectOk && (
                  <span className="text-amber-700">
                    Expect up to 5 swing + 5 intraday total; side mix is score-driven.
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
              trades={(displaySwing.picks || []).map((p) => ({
                  symbol: p.symbol,
                  direction: p.direction,
                  entryPrice: p.entryPrice,
                  exitPrice:
                    p.skipped || p.outcomeBucket === 'SKIPPED'
                      ? null
                      : p.exitPrice ?? p.currentPrice ?? p.entryPrice,
                  stopLoss: p.stopLoss,
                  target1: p.target1,
                  target2: p.target2,
                  exitReason: p.exitReason || p.status,
                  qty: p.qty,
                  deployedCapital: p.deployedCapital,
                  pnl: p.pnl,
                  pnlPct: p.pnlPct,
                  missAnalysis: null,
                  missDiagnostic: p.missDiagnostic || {
                    isMiss: p.outcomeBucket === 'LOSS',
                    isHit: p.outcomeBucket === 'WIN',
                    isSkip: p.outcomeBucket === 'SKIPPED' || Boolean(p.skipped),
                    exitReason: p.exitReason || p.status,
                    rootCause: p.outcomeBucket === 'SKIPPED' ? 'SIGNAL_CONFLICT' : null,
                    factors: p.outcomeBucket === 'SKIPPED' ? ['NOT_TRIGGERED', 'SKIP_PNL'] : [],
                    rMultiple: p.economicR ?? p.rMultiple ?? null,
                    economicR: p.economicR ?? null,
                    pathR: p.pathR ?? null,
                    movePct: p.pnlPct,
                    gapToT1Pct: null,
                    gapToT2Pct: null,
                    stopUtilization: null,
                    plannedRr: null,
                    riskPerShare: p.riskPerShare ?? null,
                    maePct: null,
                    mfePct: null,
                    stopEff: null,
                    falsePositive: false,
                    holdingMins: null,
                    source: p.outcomeBucket === 'SKIPPED' ? 'SKIP' : 'LEVELS',
                  },
                  outcomeNarrative: p.outcomeNarrative,
                  deskIcSummary: p.deskIcSummary,
                  outcomeBucket: p.outcomeBucket,
                  executionStatus: p.executionStatus,
                  economicR: p.economicR,
                  pathR: p.pathR,
                  rMultiple: p.rMultiple,
                  mfeR: p.mfeR,
                  maeR: p.maeR,
                  deskExitLabel: p.deskExitLabel,
                  deskProgress: p.deskProgress || p.scaleProgress,
                  lineage: p.lineage,
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
              {displayIntraday?.executionBasis === 'MODELED_PAPER' && (
                <p className="mt-1 text-[9px] font-bold uppercase tracking-wide text-amber-700">
                  Paper model · no broker fills · {displayIntraday.marketPhase === 'OPEN' ? 'unrealized MTM' : 'modeled close'}
                </p>
              )}
            </div>

            {noIntraday ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">
                {displayIntraday?.archiveStatus === 'NO_BOOK' || displayIntraday?.symbolSource === 'historical_missing'
                  ? `No archived Intraday book for ${dateStr}. Run EOD on that session to persist it.`
                  : 'No archived intraday picks for this date.'}
              </div>
            ) : displayIntraday ? (
              <>
                <AttributionStrip attribution={displayIntraday.attribution} label="Fill / skip" />
                <DayLessonsStrip lessons={displayIntraday.dayLessons} />
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">{displayIntraday.executionBasis === 'MODELED_PAPER' ? (displayIntraday.marketPhase === 'OPEN' ? 'Modeled MTM' : 'Modeled P&L') : 'Total P&L'}</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone(displayIntraday.totalPnl)}`}>
                      <LiveTickNumber value={fmtInr(displayIntraday.totalPnl, 2)} />
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">{displayIntraday.executionBasis === 'MODELED_PAPER' ? 'Modeled booked' : 'Realised'}</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displayIntraday as { liveRealisedPnl?: number }).liveRealisedPnl ?? intradayModeledBooked)}`}>
                      {fmtInr(
                        (displayIntraday as { liveRealisedPnl?: number }).liveRealisedPnl ??
                          intradayModeledBooked,
                        2,
                      )}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Unrealised</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displayIntraday as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? intradayModeledOpen)}`}>
                      {fmtInr((displayIntraday as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? intradayModeledOpen, 2)}
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
                    <div className="desk-panel-title">Portfolio value</div>
                    <div className="desk-metric-value text-slate-800 tabular-nums">₹{displayIntraday.remainingCapital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                  </div>
                </div>

                <PortfolioDist
                  title="Intraday portfolio balance"
                  totalDeployed={displayIntraday.totalDeployed || 0}
                  rows={(displayIntraday.trades || []).filter((t) => t.outcomeBucket !== 'SKIPPED' && !t.skipped).map((t) => ({
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
                              {' '}
                              <span className="text-[8px] text-slate-400 ml-1">{trade.direction}</span>
                              {trade.pnlKind === 'unrealised' && (
                                <><span aria-hidden> </span><span className="ml-1 text-[7px] font-black uppercase text-cyan-600">U</span></>
                              )}
                              {trade.pnlKind === 'realised' && (
                                <><span aria-hidden> </span><span className="ml-1 text-[7px] font-black uppercase text-slate-400">R</span></>
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
                                trade.exitPrice ?? '—'
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
                {' · Asset Matrix swing lock (not intraday)'}
                {liveActive && liveMarks?.marketOpen ? ' · LIVE MTM' : ''}
              </p>
              {displaySwing?.executionBasis === 'MODELED_PAPER' && (
                <p className="mt-1 text-[9px] font-bold uppercase tracking-wide text-amber-700">
                  Paper model · no broker fills · {displaySwing.marketPhase === 'OPEN' ? 'unrealized MTM' : 'modeled close'}
                </p>
              )}
            </div>

            {noSwing ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">
                {displaySwing?.archiveStatus === 'NO_BOOK' || displaySwing?.symbolSource === 'historical_missing'
                  ? `No archived Swing book for ${swingDateStr || dateStr}. Run EOD on that session to persist it.`
                  : 'No locked swing portfolio. Lock swing from Asset Matrix BUY set first.'}
              </div>
            ) : displaySwing ? (
              <>
                <AttributionStrip attribution={displaySwing.attribution} label="Fill / skip" />
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">{displaySwing.executionBasis === 'MODELED_PAPER' ? (displaySwing.marketPhase === 'OPEN' ? 'Modeled MTM' : 'Modeled P&L') : 'Total P&L'}</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone(displaySwing.totalPnl || displaySwing.totalPnlPct)}`}>
                      {displaySwing.totalPnl != null && Math.abs(Number(displaySwing.totalPnl)) >= 0.005
                        ? <LiveTickNumber value={fmtInr(displaySwing.totalPnl, 2)} />
                        : displaySwing.totalPnlPct != null
                          ? fmtMissSigned(displaySwing.totalPnlPct, 2, '%')
                          : '—'}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">{displaySwing.executionBasis === 'MODELED_PAPER' ? 'Modeled booked' : 'Realised'}</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displaySwing as { liveRealisedPnl?: number }).liveRealisedPnl ?? swingModeledBooked)}`}>
                      {fmtInr((displaySwing as { liveRealisedPnl?: number }).liveRealisedPnl ?? swingModeledBooked, 2)}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="desk-panel-title">Unrealised</div>
                    <div className={`desk-metric-value tabular-nums ${pnlTone((displaySwing as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? swingModeledOpen)}`}>
                      {fmtInr((displaySwing as { liveUnrealisedPnl?: number }).liveUnrealisedPnl ?? swingModeledOpen, 2)}
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
                  rows={(displaySwing.picks || []).filter((p) => p.outcomeBucket !== 'SKIPPED' && !p.skipped).map((p) => ({
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
                        <th className="hidden sm:table-cell text-left px-2 py-1.5 font-bold">Src / Rank</th>
                        <th className="text-center px-2 py-1.5 font-bold">Status</th>
                        <th className="text-right px-2 py-1.5 font-bold">Qty</th>
                        <th className="text-right px-2 py-1.5 font-bold">Entry</th>
                        <th className="text-right px-2 py-1.5 font-bold">Mark</th>
                        <th className="text-right px-2 py-1.5 font-bold">Exit</th>
                        <th className="hidden sm:table-cell text-right px-2 py-1.5 font-bold">Econ R</th>
                        <th className="hidden sm:table-cell text-left px-2 py-1.5 font-bold">Scale / Trail</th>
                        <th className="hidden sm:table-cell text-right px-2 py-1.5 font-bold">Deployed</th>
                        <th className="text-right px-2 py-1.5 font-bold">P&L</th>
                        <th className="hidden sm:table-cell text-right px-2 py-1.5 font-bold">%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displaySwing.picks.map((pick, i) => {
                        const badge = statusBadge(pick.status);
                        const econ = pick.economicR ?? pick.rMultiple;
                        const path = pick.pathR;
                        const showPath = path != null && econ != null && Math.abs(Number(path) - Number(econ)) > 0.001;
                        const lin = pick.lineage;
                        return (
                          <tr key={`${pick.symbol}-${i}`} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-2 py-1.5">
                              <span className={`font-bold ${pick.direction === 'LONG' ? 'text-emerald-700' : 'text-red-700'}`}>
                                {pick.symbol}
                              </span>
                              {' '}
                              <span className="text-[8px] text-slate-400 ml-1">{pick.direction}</span>
                              {pick.outcomeBucket && (
                                <><span aria-hidden> </span><span className="ml-1 text-[7px] font-black uppercase text-slate-400">{pick.outcomeBucket}</span></>
                              )}
                              {pick.pnlKind === 'unrealised' && (
                                <><span aria-hidden> </span><span className="ml-1 text-[7px] font-black uppercase text-cyan-600">U</span></>
                              )}
                              {pick.pnlKind === 'realised' && !pick.skipped && (
                                <><span aria-hidden> </span><span className="ml-1 text-[7px] font-black uppercase text-slate-400">R</span></>
                              )}
                            </td>
                            <td className="hidden sm:table-cell px-2 py-1.5 text-[8px] text-slate-500">
                              <div className="font-bold">{lin?.source || pick.selectionReason || '—'}</div>
                              <div>
                                {lin?.lockRank != null ? `#${lin.lockRank}` : '—'}
                                {lin?.score != null || pick.score != null
                                  ? ` · ${Number(lin?.score ?? pick.score).toFixed(1)}`
                                  : ''}
                              </div>
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
                                <LiveTickNumber value={Number(pick.currentPrice).toFixed(2)} />
                              ) : (
                                pick.currentPrice != null ? Number(pick.currentPrice).toFixed(2) : '—'
                              )}
                            </td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">
                              {pick.skipped || pick.outcomeBucket === 'SKIPPED' ? '—' : (pick.exitPrice ?? '—')}
                            </td>
                            <td className={`hidden sm:table-cell text-right px-2 py-1.5 tabular-nums font-bold ${(econ ?? 0) < 0 ? 'text-red-600' : 'text-emerald-700'}`}>
                              <div>{fmtMissSigned(econ, 2, 'R')}</div>
                              {showPath && (
                                <div className="text-[7px] font-semibold text-slate-400">path {fmtMissSigned(path, 2, 'R')}</div>
                              )}
                            </td>
                            <td className="hidden sm:table-cell px-2 py-1.5">
                              <ScaleExitCell
                                scaleTrail={pick.scaleTrail}
                                scaleProgress={pick.deskProgress || pick.scaleProgress}
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
                      {' '}
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
                      {' '}
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
