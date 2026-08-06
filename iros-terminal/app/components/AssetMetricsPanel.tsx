'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { DeskGaugeFill, motion } from '@/lib/desk-motion';

/* ── Types (API facts only) ─────────────────────────────────────────── */

type FactorComponent = {
  score: number;
  weight: number;
  rated: boolean;
  rsVsIndexPct?: number | null;
  niftyChangePct?: number | null;
  gapPct?: number | null;
  intradayRet?: number | null;
  orbHigh?: number | null;
  orbLow?: number | null;
  orbVelocityPct?: number | null;
  orbPosPct?: number | null;
  inPlay?: boolean;
  inPlayReason?: string;
  overextended?: boolean;
  vwapMode?: string;
  vwapZ?: number | null;
  vwapSource?: string;
  vwap?: number | null;
  rvolTime?: number | null;
  rvolRaw?: number | null;
  cumVolFracHeuristic?: number | null;
  reason?: string;
  rsi?: number | null;
};

type PositionRow = {
  rank?: number;
  symbol: string;
  name?: string;
  direction: 'LONG' | 'SHORT' | string;
  sector?: string;
  sleeve?: 'MOMENTUM' | 'MEAN_REVERSION' | string;
  score?: number | null;
  scorePctRank?: number | null;
  intradayRetPctRank?: number | null;
  meanrevScore?: number | null;
  gapPct?: number | null;
  intradayRet?: number | null;
  inPlay?: boolean;
  inPlayReason?: string;
  overextended?: boolean;
  vwapMode?: string;
  vwap?: number | null;
  orbHigh?: number | null;
  orbLow?: number | null;
  orbPosPct?: number | null;
  factorBreakdown?: Record<string, FactorComponent>;
  /** RS vs NIFTY % from session engine — top-level or factorBreakdown.relativeStrength */
  rsVsIndexPct?: number | null;
  riskScale?: number | null;
  effectiveRiskFraction?: number | null;
  ltp?: number | null;
  entryPrice?: number | null;
  approxQty?: number | null;
  deployedCapital?: number | null;
  positionValue?: number | null;
  unrealizedPnl?: number | null;
  pnlPct?: number | null;
  stopLoss?: number | null;
  target1?: number | null;
  target2?: number | null;
  rewardRisk?: number | null;
  distToSlPct?: number | null;
  distToT1Pct?: number | null;
  distToT2Pct?: number | null;
  status?: string;
  closed?: boolean;
  ltpSource?: string;
  dataStale?: boolean;
  /** Scale-trail plan and live state — from backend SCALE_TRAIL mode */
  exitPlan?: { mode?: string; legs?: { r: number; label: string }[]; runnerQty?: number | null } | null;
  exitState?: {
    legsFilled?: number[];
    remainingQty?: number | null;
    effectiveStop?: number | null;
    realizedPnl?: number | null;
    unrealizedPnl?: number | null;
    rMultiple?: number | null;
    closed?: boolean;
  } | null;
  realizedPnl?: number | null;
};

type AttentionItem = {
  symbol?: string;
  direction?: string;
  status?: string;
  ltp?: number | null;
  distToSlPct?: number | null;
  distToT1Pct?: number | null;
};

type SessionEvent = {
  type?: string;
  at?: string;
  symbol?: string;
  direction?: string;
  long?: string[];
  short?: string[];
};

type SessionResponse = {
  success?: boolean;
  locked?: boolean;
  sessionDate?: string;
  committedAt?: string;
  updatedAt?: string;
  snapshotUpdatedAt?: string;
  marketOpen?: boolean | null;
  sessionClosed?: boolean | null;
  dataStale?: boolean | null;
  feedStatus?: string;
  executionPolicy?: string;
  priceSourcesNote?: string;
  ltpSourceMix?: Record<string, number>;
  regime?: {
    label?: string;
    bias?: string;
    niftyChangePct?: number | null;
    bankNiftyChangePct?: number | null;
    indiaVix?: number | null;
    reasons?: string[];
  };
  macros?: {
    nifty?: string | null;
    niftyDelta?: string | null;
    bankNifty?: string | null;
    bankNiftyDelta?: string | null;
    indiaVix?: string | null;
    indiaVixDelta?: string | null;
  };
  capital?: {
    longCapital?: number;
    shortCapital?: number;
    riskFraction?: number;
    basketSize?: number;
    candidatePoolSize?: number;
    lockSize?: number;
    momentumSlots?: number;
    meanRevSlots?: number;
    riskScaleLong?: number;
    riskScaleShort?: number;
  };
  meanRevGate?: {
    open?: boolean;
    reason?: string;
    vixMax?: number;
  };
  portfolio?: {
    longCapital?: number;
    shortCapital?: number;
    longExposure?: number;
    shortExposure?: number;
    grossExposure?: number;
    netExposure?: number;
    unrealizedPnl?: number | null;
    realizedPnl?: number | null;
  };
  attention?: AttentionItem[];
  long?: PositionRow[];
  short?: PositionRow[];
  events?: SessionEvent[];
  error?: string;
};

type CandidatesResponse = {
  success?: boolean;
  error?: string;
  dataStale?: boolean;
  snapshotUpdatedAt?: string;
  regime?: SessionResponse['regime'];
  capital?: SessionResponse['capital'];
  meanRevGate?: SessionResponse['meanRevGate'];
  proposedLong?: PositionRow[];
  proposedShort?: PositionRow[];
  adoptLong?: PositionRow[];
  adoptShort?: PositionRow[];
  funnel?: Record<string, number | string>;
  locked?: boolean;
};

/** Honest monitor fields — only what /api/live-prices returns. */
type LivePricesResponse = {
  long?: unknown[];
  short?: unknown[];
  updatedAt?: string | null;
  snapshotUpdatedAt?: string | null;
  snapshotAgeSec?: number | null;
  source?: string;
  priceSourcesNote?: string;
  marketOpen?: boolean | null;
  sessionClosed?: boolean | null;
  dataStale?: boolean | null;
  ltpSourceMix?: Record<string, number>;
  locked?: boolean;
  executionPolicy?: string;
  error?: string;
};

type SubView = 'positions' | 'risk' | 'regime' | 'events';

/* ── Formatters — never invent ──────────────────────────────────────── */

function dash(v: number | string | null | undefined, digits = 2): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') {
    if (Number.isNaN(v)) return '—';
    return v.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits });
  }
  return String(v);
}

function inr(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

/** Null/undefined/NaN P&L → em dash — never coerce to 0 / ₹0.00. */
function pnlFmt(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return dash(v, digits);
}

function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(digits)}%`;
}

/** Prefer top-level rsVsIndexPct; fall back to relativeStrength factor only. Never invent. */
function rowRsVsIndex(r: PositionRow): number | null {
  if (r.rsVsIndexPct != null && !Number.isNaN(r.rsVsIndexPct)) return r.rsVsIndexPct;
  const rs = r.factorBreakdown?.relativeStrength?.rsVsIndexPct;
  if (rs != null && !Number.isNaN(rs)) return rs;
  return null;
}

function rowGapIntra(r: PositionRow): { gap: number | null; intra: number | null } {
  const gap =
    r.gapPct != null && !Number.isNaN(r.gapPct)
      ? r.gapPct
      : r.factorBreakdown?.relativeStrength?.gapPct ?? null;
  const intra =
    r.intradayRet != null && !Number.isNaN(r.intradayRet)
      ? r.intradayRet
      : r.factorBreakdown?.relativeStrength?.intradayRet ?? null;
  return { gap: gap ?? null, intra: intra ?? null };
}

function rowInPlay(r: PositionRow): boolean {
  if (r.inPlay === true) return true;
  return r.factorBreakdown?.breakout?.inPlay === true;
}

function sleeveTone(sleeve?: string): string {
  const s = (sleeve || 'MOMENTUM').toUpperCase();
  if (s.includes('MEAN') || s.includes('REV')) return 'desk-pill--warn';
  return 'desk-pill--strong';
}

function OrbBand({
  orbLow,
  orbHigh,
  vwap,
  ltp,
}: {
  orbLow?: number | null;
  orbHigh?: number | null;
  vwap?: number | null;
  ltp?: number | null;
}) {
  if (
    orbLow == null ||
    orbHigh == null ||
    Number.isNaN(orbLow) ||
    Number.isNaN(orbHigh) ||
    orbHigh <= orbLow
  ) {
    return <p className="text-[9px] text-slate-400">ORB band —</p>;
  }
  const pad = (orbHigh - orbLow) * 0.15;
  const lo = orbLow - pad;
  const hi = orbHigh + pad;
  const span = hi - lo || 1;
  const pctOf = (v: number) => Math.max(0, Math.min(100, ((v - lo) / span) * 100));
  const lowPct = pctOf(orbLow);
  const highPct = pctOf(orbHigh);
  const bandW = Math.max(highPct - lowPct, 1);
  return (
    <div className="space-y-1">
      <div className="text-[8px] uppercase tracking-wider text-slate-500">ORB band</div>
      <div className="relative h-5 rounded glass-flat overflow-hidden">
        <motion.div
          className="absolute top-0 bottom-0 bg-cyan-200/70 border-x border-cyan-500/50"
          initial={false}
          animate={{ left: `${lowPct}%`, width: `${bandW}%` }}
          transition={{ type: 'spring', stiffness: 260, damping: 28 }}
        />
        {vwap != null && !Number.isNaN(vwap) && (
          <motion.div
            className="absolute top-0 bottom-0 w-0.5 bg-violet-500"
            initial={false}
            animate={{ left: `${pctOf(vwap)}%` }}
            transition={{ type: 'spring', stiffness: 280, damping: 30 }}
            title={`VWAP ${vwap}`}
          />
        )}
        {ltp != null && !Number.isNaN(ltp) && (
          <motion.div
            className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-slate-900 border border-white"
            initial={false}
            animate={{ left: `calc(${pctOf(ltp)}% - 4px)` }}
            transition={{ type: 'spring', stiffness: 300, damping: 28 }}
            title={`LTP ${ltp}`}
          />
        )}
      </div>
      <div className="flex justify-between text-[8px] tabular-nums text-slate-500">
        <span>L {dash(orbLow)}</span>
        <span>VWAP {dash(vwap)}</span>
        <span>H {dash(orbHigh)}</span>
      </div>
    </div>
  );
}

function formatIstClock(iso?: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString('en-IN', {
      hour12: false,
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return '—';
  }
}

function formatIstNow(): string {
  return new Date().toLocaleTimeString('en-IN', {
    hour12: false,
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return 'text-slate-500';
  return v > 0 ? 'text-emerald-600' : 'text-red-600';
}

function statusTone(status?: string): string {
  const s = (status || '').toUpperCase();
  if (s.includes('STOP') || s === 'CLOSED') return 'desk-pill--danger';
  if (s.includes('DATA STALE')) return 'desk-pill--warn';
  if (s.includes('SL APPROACHING')) return 'desk-pill--warn';
  if (s.includes('SESSION CLOSED') || s.includes('NOT TRIGGERED')) return 'desk-pill--muted';
  if (s.includes('TARGET')) return 'desk-pill--ok';
  if (s === 'RUNNING') return 'desk-pill--strong';
  return 'desk-pill--muted';
}

function mixLabel(mix?: Record<string, number> | null): string {
  if (!mix) return '—';
  const bits = Object.entries(mix)
    .filter(([, n]) => typeof n === 'number' && n > 0)
    .map(([k, n]) => `${k}:${n}`);
  return bits.length ? bits.join(' · ') : '—';
}

/**
 * Monitor banner — facts from /api/live-prices only.
 * Never claims tick-live freshness or "no external API calls".
 */
function buildLivePricesBanner(lp: LivePricesResponse | null, clock: string): string {
  if (!lp) return `MONITOR · awaiting live-prices · clock ${clock} IST`;

  const parts: string[] = ['MONITOR'];

  if (lp.sessionClosed === true) parts.push('poll ~10s (market closed · close marks)');
  else if (lp.marketOpen === true) parts.push('poll active (market open)');
  else if (lp.marketOpen === false) parts.push('poll active (market closed)');
  else parts.push('poll —');

  const evalAt = formatIstClock(lp.updatedAt);
  const snapAt = formatIstClock(lp.snapshotUpdatedAt);
  parts.push(evalAt !== '—' ? `eval@ ${evalAt} IST` : 'eval@ —');
  parts.push(snapAt !== '—' ? `snapshot@ ${snapAt} IST` : 'snapshot@ —');

  if (typeof lp.snapshotAgeSec === 'number' && !Number.isNaN(lp.snapshotAgeSec)) {
    parts.push(`age ${Math.round(lp.snapshotAgeSec)}s`);
  }

  const mix = mixLabel(lp.ltpSourceMix);
  parts.push(mix !== '—' ? `sources ${mix}` : 'sources —');
  if (lp.priceSourcesNote) parts.push(lp.priceSourcesNote);
  else if (lp.source) parts.push(`source ${lp.source}`);

  if (lp.marketOpen === true) parts.push('session OPEN');
  else if (lp.marketOpen === false) parts.push('session CLOSED');
  else parts.push('session —');

  if (lp.locked === true) parts.push('plan locked');
  if (lp.dataStale) parts.push('DATA STALE');
  if (lp.error) parts.push(`error ${lp.error}`);

  parts.push(`clock ${clock} IST`);
  return parts.join(' · ');
}

/* ── API helpers ────────────────────────────────────────────────────── */

async function readJsonSafe<T extends object>(res: Response, fallback: T): Promise<T> {
  try {
    const data = (await res.json()) as T;
    return data && typeof data === 'object' ? data : fallback;
  } catch {
    return fallback;
  }
}

async function fetchSession(): Promise<SessionResponse> {
  const empty: SessionResponse = { success: false, locked: false, long: [], short: [] };
  try {
    const res = await fetch('/api/intraday-session', { cache: 'no-store' });
    const data = await readJsonSafe<SessionResponse>(res, empty);
    if (res.status === 404) {
      return { ...empty, error: 'Session API not found (404)' };
    }
    if (!res.ok) {
      return { ...empty, ...data, error: data.error || `Session HTTP ${res.status}` };
    }
    return data;
  } catch (err) {
    return { ...empty, error: err instanceof Error ? err.message : 'Session fetch failed' };
  }
}

async function fetchCandidates(): Promise<CandidatesResponse> {
  const empty: CandidatesResponse = { success: false };
  try {
    const res = await fetch('/api/intraday-session/candidates', { cache: 'no-store' });
    const data = await readJsonSafe<CandidatesResponse>(res, empty);
    if (res.status === 404) {
      return { ...empty, error: 'Candidates API not found (404)' };
    }
    if (!res.ok) {
      return { ...empty, ...data, error: data.error || `Candidates HTTP ${res.status}` };
    }
    return data;
  } catch (err) {
    return { ...empty, error: err instanceof Error ? err.message : 'Candidates fetch failed' };
  }
}

async function fetchLivePrices(): Promise<LivePricesResponse> {
  const empty: LivePricesResponse = {
    long: [],
    short: [],
    updatedAt: null,
    source: 'none',
    dataStale: true,
  };
  try {
    const res = await fetch('/api/live-prices', { cache: 'no-store' });
    const data = await readJsonSafe<LivePricesResponse>(res, empty);
    if (res.status === 404) {
      return { ...empty, error: 'live-prices API not found (404)' };
    }
    if (!res.ok) {
      return { ...empty, ...data, error: data.error || `live-prices HTTP ${res.status}` };
    }
    return data;
  } catch (err) {
    return {
      ...empty,
      error: err instanceof Error ? err.message : 'live-prices fetch failed',
    };
  }
}

async function commitSession(force = false): Promise<SessionResponse & { error?: string }> {
  try {
    const res = await fetch(`/api/intraday-session/commit?force=${force ? 'true' : 'false'}`, {
      method: 'POST',
      cache: 'no-store',
    });
    const data = await readJsonSafe<SessionResponse & { error?: string }>(res, {
      success: false,
      error: `Commit HTTP ${res.status}`,
    });
    if (!res.ok) {
      return { ...data, error: data.error || `Commit HTTP ${res.status}` };
    }
    return data;
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : 'Commit failed' };
  }
}

/* ── Subcomponents ──────────────────────────────────────────────────── */

function StatusPill({ children, tone }: { children: React.ReactNode; tone?: string }) {
  const label = String(children ?? '');
  const liveish = /LIVE|RUNNING|OPEN|POLL|LOCKED/i.test(label);
  const warnish = /STALE|WARN|CLOSED|HOLD/i.test(label);
  const errish = /ERROR|FAIL|REJECT/i.test(label);
  const dotClass = errish
    ? 'desk-breathe-dot is-error'
    : warnish
      ? 'desk-breathe-dot is-warn'
      : liveish
        ? 'desk-breathe-dot'
        : 'desk-breathe-dot';
  return (
    <span className={`desk-pill glass-pill inline-flex items-center gap-1.5 ${tone || 'desk-pill--muted'}`}>
      {(liveish || warnish || errish) && <span className={dotClass} aria-hidden />}
      {children}
    </span>
  );
}

function Kpi({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[8px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className={`text-[13px] font-bold tabular-nums ${valueClass || 'text-slate-900'}`}>{value}</div>
    </div>
  );
}

function PositionTable({
  title,
  rows,
  selected,
  onSelect,
  emptyHint,
}: {
  title: string;
  rows: PositionRow[];
  selected: string | null;
  onSelect: (symbol: string) => void;
  emptyHint: string;
}) {
  const cols = [
    '#', 'Symbol', 'Sleeve', 'LTP', 'Entry', 'Qty', 'Value', 'P&L', '%',
    'Score', 'Rank%', 'Gap/Intra', 'Play', 'RS', 'SL', 'T1', 'T2', 'R:R', '→SL', '→T1', 'Status',
  ];
  return (
    <div className="bg-white/80 border border-slate-200 rounded-xl overflow-hidden shadow-sm">
      <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between">
        <h3 className="desk-panel-title text-slate-900">{title}</h3>
        <span className="text-[9px] text-slate-500 tabular-nums">{rows.length} names</span>
      </div>
      <div className="overflow-x-auto desk-scroll-x">
        <table className="w-full text-left text-[10px]">
          <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-[8px]">
            <tr>
              {cols.map((h) => (
                <th key={h} className="px-2 py-1.5 font-semibold whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={cols.length} className="px-3 py-6 text-center text-slate-400">
                  {emptyHint}
                </td>
              </tr>
            ) : (
              rows.map((r, i) => {
                const sym = r.symbol;
                const isSel = selected === sym;
                const rs = rowRsVsIndex(r);
                const { gap, intra } = rowGapIntra(r);
                const play = rowInPlay(r);
                const sleeve = r.sleeve || 'MOMENTUM';
                return (
                  <tr
                    key={`${sym}-${i}`}
                    onClick={() => onSelect(sym)}
                    className={`border-t border-slate-100 cursor-pointer hover:bg-cyan-50/40 ${isSel ? 'bg-cyan-50/60' : ''}`}
                  >
                    <td className="px-2 py-1.5 tabular-nums text-slate-500">{r.rank ?? i + 1}</td>
                    <td className="px-2 py-1.5 font-bold text-slate-900">{sym || '—'}</td>
                    <td className="px-2 py-1.5">
                      <StatusPill tone={sleeveTone(sleeve)}>
                        {sleeve.includes('MEAN') || sleeve.includes('REV') ? 'MR' : 'MOM'}
                      </StatusPill>
                    </td>
                    <td className="px-2 py-1.5 tabular-nums">{dash(r.ltp)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{dash(r.entryPrice)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{r.approxQty ?? '—'}{r.exitState?.remainingQty != null && r.exitState.remainingQty !== r.approxQty ? <span className="text-amber-600 ml-1">/{r.exitState.remainingQty}rem</span> : null}</td>
                    <td className="px-2 py-1.5 tabular-nums">{inr(r.positionValue ?? r.deployedCapital ?? null)}</td>
                    <td className={`px-2 py-1.5 tabular-nums font-semibold ${pnlClass(r.unrealizedPnl)}`}>{pnlFmt(r.unrealizedPnl)}</td>
                    <td className={`px-2 py-1.5 tabular-nums ${pnlClass(r.pnlPct)}`}>{pct(r.pnlPct)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{r.score == null ? 'UNRATED' : dash(r.score, 1)}</td>
                    <td className="px-2 py-1.5 tabular-nums">
                      {r.scorePctRank == null ? '—' : dash(r.scorePctRank, 0)}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums whitespace-nowrap">
                      {gap == null && intra == null
                        ? '—'
                        : `${gap == null ? '—' : pct(gap, 1)} / ${intra == null ? '—' : pct(intra, 1)}`}
                    </td>
                    <td className="px-2 py-1.5">
                      {play ? (
                        <span className="inline-block w-2 h-2 rounded-full bg-cyan-500" title={r.inPlayReason || 'in play'} />
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className={`px-2 py-1.5 tabular-nums ${pnlClass(rs)}`}>{pct(rs, 1)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{r.exitState?.effectiveStop != null ? <span title="Effective trail stop">{dash(r.exitState.effectiveStop)}*</span> : dash(r.stopLoss)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{dash(r.target1)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{dash(r.target2)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{dash(r.rewardRisk, 1)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{r.distToSlPct == null ? '—' : `${r.distToSlPct.toFixed(2)}%`}</td>
                    <td className="px-2 py-1.5 tabular-nums">{r.distToT1Pct == null ? '—' : `${r.distToT1Pct.toFixed(2)}%`}</td>
                    <td className="px-2 py-1.5">
                      <StatusPill tone={statusTone(r.status)}>{r.status || '—'}</StatusPill>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Main panel ─────────────────────────────────────────────────────── */

export default function AssetMetricsPanel({
  refreshToken = 0,
}: {
  /** Bumped by top desk Refresh — reloads session / candidates / prices. */
  refreshToken?: number;
}) {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [candidates, setCandidates] = useState<CandidatesResponse | null>(null);
  const [livePrices, setLivePrices] = useState<LivePricesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [subView, setSubView] = useState<SubView>('positions');
  const [selected, setSelected] = useState<string | null>(null);
  const [clock, setClock] = useState(formatIstNow);
  const [researchOpen, setResearchOpen] = useState(false);
  const [lemonn, setLemonn] = useState<{ count?: number; source?: string; isMock?: boolean } | null>(null);
  const [dhan, setDhan] = useState<{ count?: number; source?: string; isMock?: boolean } | null>(null);

  const loadSession = useCallback(async () => {
    try {
      const data = await fetchSession();
      setSession(data);
      setError(data.error || null);
      setSelected((prev) => {
        if (prev) return prev;
        return data.long?.[0]?.symbol || data.short?.[0]?.symbol || null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Session fetch failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCandidates = useCallback(async () => {
    try {
      const data = await fetchCandidates();
      setCandidates(data);
    } catch {
      /* candidates optional when locked */
    }
  }, []);

  const loadLivePrices = useCallback(async () => {
    try {
      const data = await fetchLivePrices();
      setLivePrices(data);
    } catch {
      setLivePrices({
        long: [],
        short: [],
        updatedAt: null,
        source: 'none',
        dataStale: true,
        error: 'live-prices unavailable',
      });
    }
  }, []);

  const loadResearch = useCallback(async () => {
    try {
      const [l, d] = await Promise.all([
        fetch('/api/intraday-matrix', { cache: 'no-store' }).then((r) => r.json()).catch(() => null),
        fetch('/api/dhan-scanner-matrix', { cache: 'no-store' }).then((r) => r.json()).catch(() => null),
      ]);
      if (l) setLemonn({ count: l.count, source: l.source, isMock: l.isMock });
      if (d) setDhan({ count: d.count ?? d.tradePlan?.length, source: d.source, isMock: d.isMock });
    } catch {
      /* research optional */
    }
  }, []);

  useEffect(() => {
    void loadSession();
    void loadCandidates();
    void loadLivePrices();
    const clockId = window.setInterval(() => setClock(formatIstNow()), 1000);
    return () => window.clearInterval(clockId);
  }, [loadSession, loadCandidates, loadLivePrices]);

  useEffect(() => {
    if (!refreshToken) return;
    void loadSession();
    void loadCandidates();
    void loadLivePrices();
    void loadResearch();
  }, [refreshToken, loadSession, loadCandidates, loadLivePrices, loadResearch]);

  useEffect(() => {
    const marketOpen = livePrices?.marketOpen ?? session?.marketOpen;
    const closed = livePrices?.sessionClosed ?? session?.sessionClosed;
    const ms = closed === true ? 10_000 : marketOpen === true ? 2_000 : 5_000;
    const id = window.setInterval(() => {
      void loadSession();
      void loadLivePrices();
    }, ms);
    return () => window.clearInterval(id);
  }, [loadSession, loadLivePrices, livePrices?.marketOpen, livePrices?.sessionClosed, session?.marketOpen, session?.sessionClosed]);

  const onCommit = async (force = false) => {
    setCommitting(true);
    setError(null);
    try {
      const result = await commitSession(force);
      if (result.error && !result.locked) {
        setError(typeof result.error === 'string' ? result.error : 'Commit failed');
      }
      await loadSession();
      await loadCandidates();
      await loadLivePrices();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Commit failed');
    } finally {
      setCommitting(false);
    }
  };

  const allRows = useMemo(() => {
    if (session?.locked) {
      return [...(session?.long || []), ...(session?.short || [])];
    }
    return [
      ...(candidates?.proposedLong || session?.long || []),
      ...(candidates?.proposedShort || session?.short || []),
    ];
  }, [session, candidates]);
  const selectedRow = useMemo(
    () => allRows.find((r) => r.symbol === selected) || null,
    [allRows, selected]
  );

  const longCap = session?.portfolio?.longCapital ?? session?.capital?.longCapital ?? candidates?.capital?.longCapital;
  const shortCap = session?.portfolio?.shortCapital ?? session?.capital?.shortCapital ?? candidates?.capital?.shortCapital;
  const banner = buildLivePricesBanner(livePrices, clock);
  const regimeLabel = session?.regime?.label || candidates?.regime?.label || 'UNRATED';
  const marketOpen = livePrices?.marketOpen ?? session?.marketOpen;
  const dataStale = Boolean(livePrices?.dataStale || session?.dataStale);

  const istToday = useMemo(
    () =>
      new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Kolkata',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).format(new Date()),
    [clock],
  );
  const sessionDate = String(session?.sessionDate || '').slice(0, 10);
  const lockedToday = Boolean(session?.locked && sessionDate === istToday);
  const staleLocked = Boolean(session?.locked && sessionDate && sessionDate !== istToday);
  // After close / overnight: keep showing the locked basket (SESSION CLOSED + last LTP).
  // Never fall back to candidates while a lock exists — candidates hardcode RUNNING.
  const showLockedBasket = Boolean(
    session?.locked && ((session?.long?.length ?? 0) > 0 || (session?.short?.length ?? 0) > 0),
  );
  const locked = lockedToday;
  const displayLong = showLockedBasket ? (session?.long || []) : (candidates?.proposedLong || []);
  const displayShort = showLockedBasket ? (session?.short || []) : (candidates?.proposedShort || []);
  const hasCandidates =
    (candidates?.proposedLong?.length ?? 0) > 0 || (candidates?.proposedShort?.length ?? 0) > 0;
  const canCommit = !lockedToday && !staleLocked && hasCandidates && !committing;
  const canForceRotate = staleLocked && hasCandidates && !committing;

  const attentionItems = session?.attention || [];
  const meanRevGate = session?.meanRevGate || candidates?.meanRevGate;
  const mrGatedOff = meanRevGate?.open === false;
  const basketSize = session?.capital?.basketSize ?? candidates?.capital?.basketSize ?? 5;
  const candidatePoolSize =
    session?.capital?.candidatePoolSize ?? candidates?.capital?.candidatePoolSize ?? 10;
  const adoptLong = candidates?.adoptLong || [];
  const adoptShort = candidates?.adoptShort || [];
  const showAttention = attentionItems.length > 0 && lockedToday;

  const emptyHint = showLockedBasket
    ? lockedToday
      ? 'No locked positions —'
      : `Locked ${sessionDate} · close marks (rotate next session for a new basket)`
    : candidates?.error
      ? `Candidates unavailable — ${candidates.error}`
      : 'No candidates yet — commit unavailable until API returns names';

  return (
    <div className="asset-metrics-panel space-y-3">
      {/* Honest monitor banner — live-prices fields only */}
      <div
        className={`desk-monitor-banner ${
          dataStale ? 'is-stale' : showLockedBasket ? 'is-locked' : ''
        }`}
        role="status"
      >
        <span
          className={`desk-monitor-dot ${
            dataStale ? 'is-stale' : marketOpen === true ? 'is-open' : ''
          }`}
        />
        <span className="leading-snug">{banner}</span>
      </div>

      {/* Header chrome */}
      <div className="bg-white/80 border border-slate-200 rounded-xl p-3 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="desk-panel-title text-slate-900">INTRADAY</h2>
              <StatusPill tone="desk-pill--strong">MANUAL EXECUTION</StatusPill>
              {lockedToday ? (
                <StatusPill tone="desk-pill--info">SESSION BASKET LOCKED · {sessionDate}</StatusPill>
              ) : staleLocked ? (
                <StatusPill tone="desk-pill--warn">
                  LOCKED CLOSE · {sessionDate} → EOD
                </StatusPill>
              ) : (
                <StatusPill>UNLOCKED</StatusPill>
              )}
              <StatusPill tone={marketOpen === true ? 'desk-pill--ok' : 'desk-pill--muted'}>
                {marketOpen === true ? 'MARKET OPEN' : marketOpen === false ? 'MARKET CLOSED' : 'MARKET —'}
              </StatusPill>
              <StatusPill tone={statusTone(dataStale ? 'DATA STALE' : session?.feedStatus)}>
                FEED {session?.feedStatus || '—'}
              </StatusPill>
            </div>
            <p className="text-[9px] text-slate-500 mt-1">
              Model outputs are probabilistic. Missing → — / UNRATED / DATA STALE. No broker auto-orders.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="text-right">
              <div className="text-[8px] uppercase text-slate-500 tracking-wider">IST</div>
              <div className="text-[14px] font-bold tabular-nums text-slate-900">{clock}</div>
            </div>
            {canCommit && (
              <button
                type="button"
                disabled={committing}
                onClick={() => onCommit(false)}
                className="desk-btn-primary"
              >
                {committing
                  ? 'Locking…'
                  : `Adopt ${basketSize}+${basketSize} from ${candidatePoolSize}+${candidatePoolSize}`}
              </button>
            )}
            {canForceRotate && (
              <button
                type="button"
                disabled={committing}
                onClick={() => onCommit(true)}
                className="desk-btn-primary"
                title="Force rotate stale-day basket to today"
              >
                {committing ? 'Rotating…' : 'Rotate today'}
              </button>
            )}
          </div>
        </div>

        {!showLockedBasket && (adoptLong.length > 0 || adoptShort.length > 0) && (
          <p className="mt-2 text-[9px] text-slate-600">
            High-prob adopt (score / in-play):{' '}
            <span className="font-bold text-emerald-700">
              BUY {adoptLong.map((r) => r.symbol).join(', ') || '—'}
            </span>
            {' · '}
            <span className="font-bold text-red-700">
              SELL {adoptShort.map((r) => r.symbol).join(', ') || '—'}
            </span>
          </p>
        )}

        <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <Kpi
            label="NIFTY"
            value={
              session?.macros?.nifty != null
                ? `${session.macros.nifty}${session.macros.niftyDelta ? ` (${session.macros.niftyDelta})` : ''}`
                : '—'
            }
          />
          <Kpi
            label="BANKNIFTY"
            value={
              session?.macros?.bankNifty != null
                ? `${session.macros.bankNifty}${session.macros.bankNiftyDelta ? ` (${session.macros.bankNiftyDelta})` : ''}`
                : '—'
            }
          />
          <Kpi
            label="INDIA VIX"
            value={
              session?.macros?.indiaVix != null
                ? `${session.macros.indiaVix}${session.macros.indiaVixDelta ? ` (${session.macros.indiaVixDelta})` : ''}`
                : '—'
            }
          />
          <Kpi label="Regime" value={regimeLabel} />
          <Kpi label="Long sleeve" value={longCap == null ? '—' : inr(longCap)} />
          <Kpi label="Short sleeve" value={shortCap == null ? '—' : inr(shortCap)} />
        </div>
      </div>

      {/* Portfolio summary */}
      <div className="bg-white/80 border border-slate-200 rounded-xl p-3 shadow-sm grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-10 gap-2 sm:gap-3 min-w-0">
        <Kpi label="Long exposure" value={inr(session?.portfolio?.longExposure ?? null)} />
        <Kpi label="Short exposure" value={inr(session?.portfolio?.shortExposure ?? null)} />
        <Kpi label="Gross" value={inr(session?.portfolio?.grossExposure ?? null)} />
        <Kpi label="Net" value={inr(session?.portfolio?.netExposure ?? null)} />
        <Kpi
          label="Unrealized P&L"
          value={pnlFmt(session?.portfolio?.unrealizedPnl)}
          valueClass={pnlClass(session?.portfolio?.unrealizedPnl)}
        />
        <Kpi
          label="Realized P&L"
          value={pnlFmt(session?.portfolio?.realizedPnl)}
          valueClass={pnlClass(session?.portfolio?.realizedPnl)}
        />
        <Kpi
          label="Risk scale L"
          value={dash(session?.capital?.riskScaleLong ?? candidates?.capital?.riskScaleLong, 2)}
        />
        <Kpi
          label="Risk scale S"
          value={dash(session?.capital?.riskScaleShort ?? candidates?.capital?.riskScaleShort, 2)}
        />
        <Kpi label="Session date" value={session?.sessionDate || '—'} />
        <Kpi label="Committed" value={formatIstClock(session?.committedAt)} />
      </div>

      {/* Attention strip */}
      {showAttention && (
        <div className="flex flex-wrap gap-2">
          {dataStale && (
            <span className={`desk-pill ${statusTone('DATA STALE')}`}>
              DATA STALE
            </span>
          )}
          {mrGatedOff && (
            <span className={`desk-pill ${statusTone('DATA STALE')}`} title={meanRevGate?.reason || ''}>
              Mean-reversion sleeve gated off — {meanRevGate?.reason || 'momentum only'}
            </span>
          )}
          {attentionItems.map((a, i) => (
            <button
              key={`${a.symbol}-${i}`}
              type="button"
              onClick={() => a.symbol && setSelected(a.symbol)}
              className={`desk-pill ${statusTone(a.status)}`}
            >
              {a.symbol || '—'} {a.direction || ''} — {a.status || '—'}
              {a.distToSlPct != null ? ` · SL ${a.distToSlPct.toFixed(2)}%` : ''}
            </button>
          ))}
        </div>
      )}

      {/* Sub-views */}
      <div className="desk-subnav" role="tablist" aria-label="Asset metrics views">
        {([
          ['positions', 'Live Positions'],
          ['risk', 'Risk'],
          ['regime', 'Regime'],
          ['events', 'Events'],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={subView === key}
            onClick={() => setSubView(key)}
            className={subView === key ? 'is-on' : undefined}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="desk-pill desk-pill--danger px-3 py-2 text-[10px] normal-case tracking-normal font-semibold">
          {error}
        </div>
      )}
      {loading && (
        <div className="text-[10px] text-slate-400 px-1">Loading session…</div>
      )}

      {subView === 'positions' && (
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_280px] gap-3">
          <div className="space-y-3">
            <PositionTable
              title={locked ? 'LONG BOOK' : 'LONG CANDIDATES'}
              rows={displayLong}
              selected={selected}
              onSelect={setSelected}
              emptyHint={emptyHint}
            />
            <PositionTable
              title={locked ? 'SHORT BOOK' : 'SHORT CANDIDATES'}
              rows={displayShort}
              selected={selected}
              onSelect={setSelected}
              emptyHint={emptyHint}
            />
          </div>

          <div className="space-y-3">
            <div className="glass-overlay rounded-xl p-3">
              <h3 className="desk-panel-title text-slate-900 mb-2">DETAIL</h3>
              {!selectedRow ? (
                <p className="text-[10px] text-slate-400">Select a symbol</p>
              ) : (
                <div className="space-y-2 text-[10px]">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-900 text-[13px]">{selectedRow.symbol}</span>
                    <StatusPill tone={statusTone(selectedRow.status)}>{selectedRow.status || '—'}</StatusPill>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <Kpi label="Direction" value={selectedRow.direction || '—'} />
                    <Kpi label="Sector" value={selectedRow.sector || '—'} />
                    <Kpi
                      label="Sleeve"
                      value={
                        selectedRow.sleeve
                          ? selectedRow.sleeve.includes('MEAN') || selectedRow.sleeve.includes('REV')
                            ? 'MEAN_REV'
                            : 'MOMENTUM'
                          : '—'
                      }
                    />
                    <Kpi label="Score" value={selectedRow.score == null ? 'UNRATED' : dash(selectedRow.score, 1)} />
                    <Kpi
                      label="Score rank %"
                      value={selectedRow.scorePctRank == null ? '—' : dash(selectedRow.scorePctRank, 0)}
                    />
                    <Kpi
                      label="RS vs NIFTY"
                      value={pct(rowRsVsIndex(selectedRow), 1)}
                      valueClass={pnlClass(rowRsVsIndex(selectedRow))}
                    />
                    <Kpi
                      label="Gap / Intraday"
                      value={(() => {
                        const { gap, intra } = rowGapIntra(selectedRow);
                        if (gap == null && intra == null) return '—';
                        return `${gap == null ? '—' : pct(gap, 1)} / ${intra == null ? '—' : pct(intra, 1)}`;
                      })()}
                    />
                    <Kpi
                      label="In-play"
                      value={rowInPlay(selectedRow) ? (selectedRow.inPlayReason || selectedRow.factorBreakdown?.breakout?.inPlayReason || 'yes') : 'no'}
                    />
                    <Kpi label="LTP src" value={selectedRow.ltpSource || '—'} />
                    <Kpi label="Entry" value={dash(selectedRow.entryPrice)} />
                    <Kpi label="LTP" value={dash(selectedRow.ltp)} />
                    <Kpi label="SL" value={dash(selectedRow.stopLoss)} />
                    <Kpi label="T1 / T2" value={`${dash(selectedRow.target1)} / ${dash(selectedRow.target2)}${selectedRow.exitPlan?.mode === 'SCALE_TRAIL' ? ' (ref)' : ''}`} />
                    <Kpi label="Qty" value={selectedRow.approxQty == null ? '—' : String(selectedRow.approxQty)} />
                    {selectedRow.exitState != null && (
                      <>
                        <Kpi label="Rem Qty" value={selectedRow.exitState.remainingQty == null ? '—' : String(selectedRow.exitState.remainingQty)} />
                        <Kpi label="Eff SL" value={selectedRow.exitState.effectiveStop == null ? '—' : dash(selectedRow.exitState.effectiveStop)} />
                        <Kpi
                          label="Realised PnL"
                          value={pnlFmt(selectedRow.exitState.realizedPnl ?? selectedRow.realizedPnl)}
                          valueClass={pnlClass(selectedRow.exitState.realizedPnl ?? selectedRow.realizedPnl)}
                        />
                        <Kpi
                          label="Unrealised PnL"
                          value={pnlFmt(selectedRow.exitState.unrealizedPnl ?? selectedRow.unrealizedPnl)}
                          valueClass={pnlClass(selectedRow.exitState.unrealizedPnl ?? selectedRow.unrealizedPnl)}
                        />
                      </>
                    )}
                    <Kpi label="R:R" value={dash(selectedRow.rewardRisk, 1)} />
                    <Kpi label="Risk scale" value={dash(selectedRow.riskScale, 2)} />
                    <Kpi
                      label="Eff. risk frac"
                      value={
                        selectedRow.effectiveRiskFraction == null
                          ? '—'
                          : dash(selectedRow.effectiveRiskFraction, 4)
                      }
                    />
                  </div>
                  <div className="mt-2">
                    <OrbBand
                      orbLow={selectedRow.orbLow ?? selectedRow.factorBreakdown?.breakout?.orbLow}
                      orbHigh={selectedRow.orbHigh ?? selectedRow.factorBreakdown?.breakout?.orbHigh}
                      vwap={selectedRow.vwap ?? selectedRow.factorBreakdown?.vwap?.vwap}
                      ltp={selectedRow.ltp}
                    />
                  </div>
                  {selectedRow.factorBreakdown && (
                    <div className="mt-2 border-t border-slate-100 pt-2">
                      <div className="text-[8px] uppercase tracking-wider text-slate-500 mb-1">Factor breakdown</div>
                      <div className="space-y-1.5 max-h-40 overflow-y-auto">
                        {Object.entries(selectedRow.factorBreakdown).map(([k, c], i) => {
                          const scorePct = c.rated
                            ? Math.max(0, Math.min(100, Number(c.score) <= 1 ? Number(c.score) * 100 : Number(c.score)))
                            : 0;
                          return (
                            <motion.div
                              key={k}
                              className="space-y-0.5"
                              initial={{ opacity: 0, y: 4 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ delay: i * 0.04, duration: 0.28 }}
                            >
                              <div className="flex justify-between tabular-nums gap-2">
                                <span className="text-slate-600">
                                  {k}{c.rated ? '' : ' · UNRATED'}
                                  {k === 'relativeStrength' && c.rsVsIndexPct != null
                                    ? ` · RS ${pct(c.rsVsIndexPct, 1)}`
                                    : ''}
                                  {k === 'momentum' && c.overextended
                                    ? ' · OVEREXTENDED'
                                    : ''}
                                  {k === 'vwap' && c.vwapMode
                                    ? ` · ${c.vwapMode}`
                                    : ''}
                                  {k === 'volume' && c.rvolTime != null
                                    ? ` · rvolT ${dash(c.rvolTime, 2)}×`
                                    : ''}
                                  {k === 'breakout' && c.orbHigh != null && c.orbLow != null
                                    ? ` · ORB ${dash(c.orbLow)}–${dash(c.orbHigh)}`
                                    : ''}
                                  {k === 'breakout' && c.inPlay
                                    ? ' · IN-PLAY'
                                    : ''}
                                  {k === 'breakout' && c.orbVelocityPct != null
                                    ? ` · vel ${pct(c.orbVelocityPct, 1)}`
                                    : ''}
                                </span>
                                <span className="font-semibold shrink-0 text-slate-900">{c.rated ? dash(c.score, 1) : '—'}</span>
                              </div>
                              {c.rated && (
                                <DeskGaugeFill
                                  pct={scorePct}
                                  toneClass={scorePct >= 60 ? 'bg-emerald-500' : scorePct >= 40 ? 'bg-amber-500' : 'bg-slate-400'}
                                />
                              )}
                            </motion.div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="bg-white/80 border border-slate-200 rounded-xl p-3 shadow-sm">
              <h3 className="desk-panel-title text-slate-900 mb-2">EVENTS</h3>
              <div className="space-y-1.5 max-h-56 overflow-y-auto">
                {(session?.events || []).length === 0 ? (
                  <p className="text-[10px] text-slate-400">No events yet</p>
                ) : (
                  [...(session?.events || [])].reverse().slice(0, 30).map((ev, i) => (
                    <div key={i} className="text-[9px] border-b border-slate-50 pb-1">
                      <span className="font-bold text-slate-700">{ev.type || 'EVENT'}</span>
                      <span className="text-slate-400 ml-2">{formatIstClock(ev.at)}</span>
                      {ev.symbol && <span className="ml-2 text-slate-600">{ev.symbol}</span>}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {subView === 'risk' && (
        <div className="bg-white/80 border border-slate-200 rounded-xl p-3 shadow-sm space-y-2">
          <h3 className="desk-panel-title text-slate-900">RISK</h3>
          <p className="text-[10px] text-slate-500">
            Risk fraction {session?.capital?.riskFraction ?? candidates?.capital?.riskFraction ?? '—'} of sleeve ·
            ATR stops · T1/T2 from server. UI cannot mutate symbols.
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Kpi
              label="Risk scale L"
              value={dash(session?.capital?.riskScaleLong ?? candidates?.capital?.riskScaleLong, 2)}
            />
            <Kpi
              label="Risk scale S"
              value={dash(session?.capital?.riskScaleShort ?? candidates?.capital?.riskScaleShort, 2)}
            />
          </div>
          {allRows.length === 0 ? (
            <p className="text-[10px] text-slate-400">No positions —</p>
          ) : (
            <div className="overflow-x-auto desk-scroll-x">
              <table className="w-full text-[10px]">
                <thead className="text-[8px] uppercase text-slate-500">
                  <tr>
                    <th className="text-left py-1">Symbol</th>
                    <th className="text-left py-1">Dir</th>
                    <th className="text-left py-1">Risk scale</th>
                    <th className="text-left py-1">Eff. frac</th>
                    <th className="text-left py-1">RS</th>
                    <th className="text-left py-1">Max loss</th>
                    <th className="text-left py-1">→SL%</th>
                    <th className="text-left py-1">→T1%</th>
                    <th className="text-left py-1">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {allRows.map((r) => (
                    <tr key={r.symbol} className="border-t border-slate-100">
                      <td className="py-1 font-bold text-slate-900">{r.symbol}</td>
                      <td className="py-1 text-slate-700">{r.direction}</td>
                      <td className="py-1 tabular-nums text-slate-800">{dash(r.riskScale, 2)}</td>
                      <td className="py-1 tabular-nums text-slate-800">
                        {r.effectiveRiskFraction == null ? '—' : dash(r.effectiveRiskFraction, 4)}
                      </td>
                      <td className={`py-1 tabular-nums ${pnlClass(rowRsVsIndex(r))}`}>{pct(rowRsVsIndex(r), 1)}</td>
                      <td className="py-1 tabular-nums text-slate-800">
                        {r.approxQty != null && r.entryPrice != null && r.stopLoss != null
                          ? inr(Math.abs(r.entryPrice - r.stopLoss) * r.approxQty)
                          : '—'}
                      </td>
                      <td className="py-1 tabular-nums text-slate-800">{r.distToSlPct == null ? '—' : `${r.distToSlPct.toFixed(2)}%`}</td>
                      <td className="py-1 tabular-nums text-slate-800">{r.distToT1Pct == null ? '—' : `${r.distToT1Pct.toFixed(2)}%`}</td>
                      <td className="py-1"><StatusPill tone={statusTone(r.status)}>{r.status || '—'}</StatusPill></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {subView === 'regime' && (
        <div className="bg-white/80 border border-slate-200 rounded-xl p-3 shadow-sm space-y-2">
          <h3 className="desk-panel-title text-slate-900">REGIME</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Kpi label="Label" value={regimeLabel} />
            <Kpi label="Bias" value={session?.regime?.bias || candidates?.regime?.bias || '—'} />
            <Kpi
              label="NIFTY Δ"
              value={
                session?.regime?.niftyChangePct == null && candidates?.regime?.niftyChangePct == null
                  ? '—'
                  : pct(session?.regime?.niftyChangePct ?? candidates?.regime?.niftyChangePct ?? null)
              }
            />
            <Kpi
              label="VIX"
              value={
                session?.regime?.indiaVix == null && candidates?.regime?.indiaVix == null
                  ? '—'
                  : dash(session?.regime?.indiaVix ?? candidates?.regime?.indiaVix ?? null, 1)
              }
            />
          </div>
          <ul className="text-[10px] text-slate-600 list-disc pl-4">
            {(session?.regime?.reasons || candidates?.regime?.reasons || []).length === 0 ? (
              <li>No regime reasons —</li>
            ) : (
              (session?.regime?.reasons || candidates?.regime?.reasons || []).map((r) => (
                <li key={r}>{r}</li>
              ))
            )}
          </ul>
          {candidates?.funnel && (
            <div className="text-[9px] text-slate-500 pt-2 border-t border-slate-100">
              Funnel · universe {candidates.funnel.universe ?? '—'} · reject {candidates.funnel.filterReject ?? '—'} ·
              long scored {candidates.funnel.longScored ?? '—'} · short scored {candidates.funnel.shortScored ?? '—'}
            </div>
          )}
        </div>
      )}

      {subView === 'events' && (
        <div className="bg-white/80 border border-slate-200 rounded-xl p-3 shadow-sm">
          <h3 className="desk-panel-title text-slate-900 mb-2">EVENT AUDIT</h3>
          <div className="space-y-2">
            {(session?.events || []).length === 0 ? (
              <p className="text-[10px] text-slate-400">No commit / close events recorded</p>
            ) : (
              [...(session?.events || [])].reverse().map((ev, i) => (
                <div key={i} className="text-[10px] border border-slate-100 rounded-lg px-2 py-1.5">
                  <div className="font-bold text-slate-800">{ev.type || 'EVENT'}</div>
                  <div className="text-slate-500">{formatIstClock(ev.at)} IST</div>
                  {ev.long && <div className="text-emerald-700">LONG: {ev.long.join(', ')}</div>}
                  {ev.short && <div className="text-red-700">SHORT: {ev.short.join(', ')}</div>}
                  {ev.symbol && <div>{ev.direction} {ev.symbol}</div>}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Research feeds — demoted */}
      <div className="border border-slate-200 rounded-xl overflow-hidden bg-slate-50/50">
        <button
          type="button"
          onClick={() => {
            const next = !researchOpen;
            setResearchOpen(next);
            if (next && !lemonn && !dhan) void loadResearch();
          }}
          className="w-full flex items-center justify-between px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500 hover:bg-slate-100"
        >
          <span>Research feeds (optional) — Lemonn / Dhan</span>
          <span>{researchOpen ? '▾' : '▸'}</span>
        </button>
        {researchOpen && (
          <div className="px-3 pb-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px] text-slate-600">
            <div className="border border-slate-200 rounded-lg p-2 bg-white/70">
              <div className="font-bold text-slate-700">Lemonn</div>
              <div>Source: {lemonn?.source || '—'}</div>
              <div>Count: {lemonn?.count ?? '—'}</div>
              {lemonn?.isMock && <div className="text-amber-600 font-semibold">mock fallback</div>}
            </div>
            <div className="border border-slate-200 rounded-lg p-2 bg-white/70">
              <div className="font-bold text-slate-700">Dhan ScanX</div>
              <div>Source: {dhan?.source || '—'}</div>
              <div>Count: {dhan?.count ?? '—'}</div>
              {dhan?.isMock && <div className="text-amber-600 font-semibold">mock fallback</div>}
            </div>
            <p className="sm:col-span-2 text-[9px] text-slate-400">
              Research only — does not mutate the locked session basket.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
