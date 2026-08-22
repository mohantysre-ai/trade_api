'use client';

import { useEffect, useState } from 'react';

type Structure = {
  status?: string | null;
  direction?: 'CALL' | 'PUT' | null;
  barCount?: number | null;
  last?: number | null;
  ema9?: number | null;
  ema20?: number | null;
  orbHigh?: number | null;
  orbLow?: number | null;
  firstDirection?: 'CALL' | 'PUT' | null;
  confirmedAt?: string | null;
};

type Candidate = {
  key: string;
  label: string;
  exchange: string;
  bucket: string;
  spot: number | null;
  direction: 'CALL' | 'PUT' | null;
  state: 'ELIGIBLE' | 'WATCH' | 'NO_TRADE';
  reason: string;
  score: number | null;
  missingInputs: string[];
  failedGates: string[];
  contract?: { symbol?: string; strike?: number; expiry?: string; ltp?: number; delta?: number; gamma?: number; theta?: number; vega?: number; iv?: number } | null;
  providerStatus?: string | null;
  dataSource?: string | null;
  expiry?: string | null;
  dataLimitations?: string[];
  chain?: Array<{ symbol?: string; strike?: number; optionType?: string; ltp?: number; oi?: number; oiChange?: number; delta?: number; gamma?: number; theta?: number; vega?: number; iv?: number }>;
  structure?: Structure | null;
};

type BuySideContract = {
  index: string;
  bucket?: string;
  symbol?: string;
  strike?: number | null;
  optionType?: string;
  expiry?: string | null;
  lotSize?: number | null;
  atmProxy?: boolean;
  implemented?: boolean;
  barCount?: number;
  entry?: number | null;
  exit?: number | null;
  entryAt?: string | null;
  exitAt?: string | null;
  pnlPoints?: number | null;
  pnlRupees?: number | null;
  limitation?: string | null;
  blockedBy?: string | null;
};

type Radar = {
  success: boolean;
  mode?: string;
  sessionDate?: string;
  updatedAt?: string | null;
  executionPolicy?: string;
  cacheStatus?: string;
  disclaimer?: string;
  candidates: Candidate[];
  selected: Candidate[];
  indices?: Array<{
    key: string;
    label?: string;
    bucket?: string;
    spot?: number | null;
    firstDirection?: string | null;
    confirmedAt?: string | null;
    selected?: boolean;
    structure?: Structure | null;
    error?: string | null;
  }>;
  implemented?: BuySideContract[];
  buySideContracts?: BuySideContract[];
  limitations?: string[];
  limits?: { maxDailyEntries: number; maxConcurrent: number; maxPerCorrelationBucket: number; scoreFloor?: number; buySideCap?: number };
  reentryPolicy?: {
    maxAttemptsPerIndex: number;
    targetCooldownMin: number;
    profitTrailCooldownMin: number;
    sameDirectionStopCooldownMin: number;
    riskScale: number;
  };
  error?: string;
};

const GATE_LABEL: Record<string, string> = {
  breadth: 'Breadth',
  breakout: 'Breakout',
  contract: 'Contract',
  contractEconomics: 'Economics',
  futuresOi: 'Futures OI',
  optionChain: 'Chain',
  riskReward: 'R:R',
  structure: 'Structure',
  trend: 'Trend',
  fresh: 'Live quotes',
};

function fmtSpot(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

function fmtPnl(value: number | null | undefined) {
  if (value == null) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

function fmtNum(value: number | null | undefined, digits = 2) {
  return value == null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: digits });
}

function pnlClass(value: number | null | undefined) {
  if (value == null || value === 0) return 'text-slate-500';
  return value > 0 ? 'text-emerald-600' : 'text-red-500';
}

function statePill(state: Candidate['state']) {
  switch (state) {
    case 'ELIGIBLE':
      return { label: 'Eligible', className: 'desk-pill desk-pill--ok' };
    case 'WATCH':
      return { label: 'Watch', className: 'desk-pill desk-pill--warn' };
    case 'NO_TRADE':
      return { label: 'No trade', className: 'desk-pill desk-pill--muted' };
    default: {
      const _never: never = state;
      return { label: String(_never), className: 'desk-pill desk-pill--muted' };
    }
  }
}

function tileAccent(state: Candidate['state']) {
  switch (state) {
    case 'ELIGIBLE':
      return 'var(--terminal-green)';
    case 'WATCH':
      return 'var(--terminal-amber)';
    case 'NO_TRADE':
      return 'var(--fg-muted)';
    default: {
      const _never: never = state;
      return String(_never);
    }
  }
}

function chainSourceLabel(source: string | null | undefined) {
  if (source === 'LEMONN_FALLBACK') return 'Lemonn';
  if (source === 'SCANX_FALLBACK') return 'ScanX';
  return 'Angel';
}

function candidateHeadline(row: Candidate) {
  const bars = row.structure?.barCount ?? 0;
  if (row.state === 'ELIGIBLE') return 'All gates passed';
  if (row.state === 'WATCH') return 'Score below 80';
  if (row.reason.startsWith('HARD_GATE_FAILED:') && row.failedGates.includes('fresh')) {
    return bars === 0 ? 'Quotes not live' : 'Stale quotes';
  }
  if (row.reason.startsWith('DATA_INCOMPLETE:')) {
    return bars === 0 ? 'No live 5m session' : 'Incomplete evidence';
  }
  if (row.reason === 'DIRECTION_NOT_PROVEN') return 'No ORB breakout';
  return 'No trade';
}

function gateChips(row: Candidate) {
  const keys = [...row.failedGates, ...row.missingInputs].filter((name, index, list) => list.indexOf(name) === index);
  return keys.slice(0, 4).map((key) => GATE_LABEL[key] ?? key);
}

function sessionLabel(iso: string | undefined) {
  if (!iso) return 'Last Friday';
  const [year, month, day] = iso.split('-').map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

function clock(iso: string | null | undefined) {
  if (!iso) return '—';
  const match = iso.match(/T(\d{2}:\d{2})/);
  return match ? match[1] : iso;
}

function contractStatus(row: BuySideContract): { label: string; className: string } {
  if (row.implemented) return { label: 'Implemented', className: 'desk-pill desk-pill--ok' };
  if (row.blockedBy === 'CORRELATION_GUARD') return { label: 'Bucket filled', className: 'desk-pill desk-pill--warn' };
  if (row.limitation === 'OPTION_CANDLES_UNAVAILABLE') return { label: 'No option 5m', className: 'desk-pill desk-pill--muted' };
  if (row.atmProxy) return { label: 'ATM', className: 'desk-pill desk-pill--info' };
  return { label: 'ATM±3', className: 'desk-pill desk-pill--muted' };
}

function loadRadar(url: string, signal: AbortSignal) {
  return fetch(url, { cache: 'no-store', signal }).then(async (response) => {
    const data = await response.json() as Radar;
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  });
}

export default function IndexOptionsPanel({ refreshToken = 0 }: { refreshToken?: number }) {
  const [radar, setRadar] = useState<Radar | null>(null);
  const [replay, setReplay] = useState<Radar | null>(null);
  const [loading, setLoading] = useState(true);
  const [replayLoading, setReplayLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setReplayLoading(true);
    loadRadar('/api/index-options', controller.signal)
      .then(setRadar)
      .catch((error) => {
        if (!controller.signal.aborted) setRadar({ success: false, candidates: [], selected: [], error: error instanceof Error ? error.message : 'Radar unavailable' });
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    loadRadar('/api/index-options?sessionDate=last-friday', controller.signal)
      .then(setReplay)
      .catch((error) => {
        if (!controller.signal.aborted) setReplay({ success: false, candidates: [], selected: [], buySideContracts: [], error: error instanceof Error ? error.message : 'Friday replay unavailable' });
      })
      .finally(() => { if (!controller.signal.aborted) setReplayLoading(false); });
    return () => controller.abort();
  }, [refreshToken]);

  const buySide = replay?.buySideContracts ?? [];
  const implemented = replay?.implemented ?? [];
  const implementedPnl = implemented.reduce<number | null>((sum, row) => {
    if (row.pnlRupees == null) return sum;
    return (sum ?? 0) + row.pnlRupees;
  }, null);

  return (
    <section className="ix-radar space-y-3" aria-label="Index options radar">
      <div className="desk-card p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="desk-panel-title text-[var(--fg-strong)]">INDEX OPTIONS RADAR</h2>
            <p className="mt-1 text-[11px] text-[var(--fg-muted)]">Direction first · futures OI · option chain · weighted constituents · contract economics</p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="desk-pill desk-pill--muted">Manual only</span>
            <span className="desk-pill desk-pill--muted">Max {radar?.limits?.maxDailyEntries ?? 10}/day</span>
            <span className="desk-pill desk-pill--muted">Max {radar?.limits?.maxConcurrent ?? 2} open</span>
            {radar?.cacheStatus === 'STALE' && <span className="desk-pill desk-pill--warn">Cached</span>}
          </div>
        </div>
      </div>

      {radar?.error && (
        <div className="desk-card border border-red-500/40 p-3 text-[12px] text-red-600">{radar.error}</div>
      )}

      <div className="desk-metric-grid grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {(radar?.candidates ?? []).map((row) => {
          const pill = statePill(row.state);
          const chips = gateChips(row);
          return (
            <article
              key={row.key}
              className="desk-metric-tile flex-col items-stretch justify-start"
              style={{ ['--tile-accent' as string]: tileAccent(row.state) }}
            >
              <div className="flex w-full items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="desk-metric-label">{row.label}</div>
                  <div className="text-[10px] uppercase tracking-wider text-[var(--fg-subtle)]">{row.exchange} · {row.bucket}</div>
                </div>
                <span className={pill.className}>{pill.label}</span>
              </div>
              <div className="desk-metric-value desk-num mt-2 w-full">{fmtSpot(row.spot)}</div>
              <div className="mt-2 grid w-full grid-cols-3 gap-2 text-[10px]">
                <div>
                  <div className="uppercase tracking-wider text-[var(--fg-subtle)]">Side</div>
                  <div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">{row.direction ?? '—'}</div>
                </div>
                <div>
                  <div className="uppercase tracking-wider text-[var(--fg-subtle)]">Score</div>
                  <div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">{row.score == null ? '—' : row.score.toFixed(1)}</div>
                </div>
                <div>
                  <div className="uppercase tracking-wider text-[var(--fg-subtle)]">5m</div>
                  <div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">{row.structure?.barCount ?? '—'}</div>
                </div>
              </div>
              <div className="mt-2 text-[11px] leading-snug text-[var(--fg-muted)]">{candidateHeadline(row)}</div>
              {chips.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {chips.map((chip) => (
                    <span key={chip} className="desk-pill desk-pill--muted">{chip}</span>
                  ))}
                </div>
              )}
              {row.contract && (
                <div className="mt-2 w-full border-t border-[var(--terminal-line)] pt-2 text-[10px] text-[var(--fg-muted)]">
                  <div className="flex flex-wrap items-center gap-1">
                    <span className="desk-pill desk-pill--muted">{chainSourceLabel(row.dataSource)}</span>
                    <span className="font-bold text-[var(--fg-strong)]">{row.contract.symbol ?? row.contract.strike ?? '—'}</span>
                    <span className="tabular-nums desk-num">₹{row.contract.ltp ?? '—'}</span>
                  </div>
                  <div className="mt-1 tabular-nums desk-num">
                    Δ {fmtNum(row.contract.delta)} · Γ {fmtNum(row.contract.gamma, 4)} · Θ {fmtNum(row.contract.theta)} · Vega {fmtNum(row.contract.vega)} · IV {fmtNum(row.contract.iv)}
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {loading && <div className="glass-skeleton h-16 rounded-xl" aria-hidden />}
      {!loading && radar?.candidates.length === 0 && !radar.error && (
        <div className="desk-card p-4 text-[12px] text-[var(--fg-muted)]">No index instruments returned.</div>
      )}

      <div className="desk-card overflow-hidden p-3 sm:p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="glass-pill inline-flex items-center gap-1.5 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-600">
            Friday session replay · {sessionLabel(replay?.sessionDate)}
          </span>
          <span className={`glass-pill px-2 py-0.5 text-[9px] font-bold tabular-nums ${pnlClass(implementedPnl)}`}>
            Implemented {fmtPnl(implementedPnl)}
          </span>
        </div>

        {replay?.error && <div className="mb-2 text-[12px] text-red-600">{replay.error}</div>}
        {replayLoading && <div className="glass-skeleton mb-3 h-12 rounded-xl" aria-hidden />}

        <div className="desk-metric-grid eod-kpi-strip mb-3 grid grid-cols-2 gap-2 xl:grid-cols-4">
          {(replay?.indices ?? []).map((row) => (
            <div key={row.key} className="desk-metric-tile flex-col items-stretch justify-start" style={{ ['--tile-accent' as string]: row.selected ? 'var(--terminal-cyan)' : 'var(--fg-muted)' }}>
              <div className="flex w-full items-center justify-between gap-2">
                <div className="desk-metric-label">{row.label ?? row.key}</div>
                <span className={`desk-pill ${row.selected ? 'desk-pill--info' : 'desk-pill--muted'}`}>
                  {row.selected ? 'Selected' : row.firstDirection ? 'Blocked' : 'No break'}
                </span>
              </div>
              <div className="desk-metric-value desk-num mt-1">{fmtSpot(row.spot)}</div>
              <div className="desk-metric-delta mt-1 text-[var(--fg-muted)]">
                {row.firstDirection ?? '—'}
                {row.confirmedAt ? ` · ${clock(row.confirmedAt)}` : ''}
                {row.structure?.barCount != null ? ` · ${row.structure.barCount} bars` : ''}
              </div>
            </div>
          ))}
        </div>

        <div className="overflow-x-auto desk-scroll-x">
          <table className="ix-book-table">
            <thead>
              <tr>
                <th className="text-left">Contract</th>
                <th className="text-left">Index</th>
                <th className="text-right">Strike</th>
                <th className="text-right">Entry</th>
                <th className="text-right">Exit</th>
                <th className="text-right">Pts</th>
                <th className="text-right">P&amp;L</th>
                <th className="text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {buySide.map((row) => {
                const status = contractStatus(row);
                return (
                  <tr key={`${row.index}-${row.symbol}`} className={row.implemented ? 'is-impl' : undefined}>
                    <td className="font-bold text-[var(--fg-strong)]">{row.symbol ?? '—'}</td>
                    <td>{row.index}</td>
                    <td className="text-right tabular-nums desk-num">{fmtNum(row.strike, 0)}</td>
                    <td className="text-right tabular-nums desk-num">{fmtNum(row.entry)}</td>
                    <td className="text-right tabular-nums desk-num">{fmtNum(row.exit)}</td>
                    <td className={`text-right tabular-nums desk-num ${pnlClass(row.pnlPoints)}`}>{fmtPnl(row.pnlPoints)}</td>
                    <td className={`text-right tabular-nums desk-num font-semibold ${pnlClass(row.pnlRupees)}`}>{fmtPnl(row.pnlRupees)}</td>
                    <td><span className={status.className}>{status.label}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!replayLoading && buySide.length === 0 && !replay?.error && (
            <div className="mt-3 text-[12px] text-[var(--fg-muted)]">No confirmed CALL/PUT on Friday 5m ORB, or option tokens were unavailable.</div>
          )}
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-[var(--fg-muted)]">
          Paper long premium from 5m option closes. Entry is the first bar after ORB+EMA confirm; exit is the last session bar. Historical OI, greeks and weighted breadth were not archived — radar gates stay closed.
        </p>
      </div>

      <div className="desk-card flex flex-wrap items-baseline gap-x-4 gap-y-1 p-3 text-[11px]">
        <span className="font-bold uppercase tracking-wider text-[var(--fg-muted)]">Policy</span>
        <span className="text-[var(--fg-muted)]">1 BROAD + 1 FINANCIAL</span>
        <span className="tabular-nums text-[var(--fg-muted)]">
          Re-entry {radar?.reentryPolicy?.maxAttemptsPerIndex ?? 2}× · {radar?.reentryPolicy?.targetCooldownMin ?? 20}m / {radar?.reentryPolicy?.profitTrailCooldownMin ?? 30}m / {radar?.reentryPolicy?.sameDirectionStopCooldownMin ?? 45}m · {(radar?.reentryPolicy?.riskScale ?? 0.5) * 100}% risk
        </span>
      </div>
    </section>
  );
}
