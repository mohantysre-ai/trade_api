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
  contract?: { symbol?: string; strike?: number; expiry?: string; ltp?: number; delta?: number; gamma?: number; theta?: number; vega?: number; iv?: number; lotSize?: number; token?: string; exchange?: string } | null;
  providerStatus?: string | null;
  dataSource?: string | null;
  expiry?: string | null;
  dataLimitations?: string[];
  gateEvidence?: {
    futuresOi?: { state?: string; priceChangePct?: number | null; oiChangePct?: number | null; aligned?: boolean | null; baseline?: { basis?: string; ageSeconds?: number | null } | null };
    optionChain?: { reason?: string; aligned?: boolean | null; directionalOiChange?: number | null; opposingOiChange?: number | null };
    breadth?: { score?: number | null; coveragePct?: number | null; aligned?: boolean | null; source?: string };
    contractEconomics?: { aligned?: boolean | null; greeksSource?: string | null; spreadPct?: number | null };
    riskReward?: { aligned?: boolean | null; expectedR?: number | null; basis?: string; stop?: number | null; target?: number | null; minimumR?: number | null };
  };
  chain?: Array<{ symbol?: string; strike?: number; optionType?: string; ltp?: number; oi?: number; oiChange?: number; delta?: number; gamma?: number; theta?: number; vega?: number; iv?: number }>;
  structure?: Structure | null;
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
  paperBook?: {
    mode?: string; entryCount?: number; dailyEntryCap?: number; openPnl?: number; realizedPnl?: number; totalPnl?: number;
    open?: PaperPosition[]; closed?: PaperPosition[];
  };
  limits?: { minDailyEntries?: number; maxDailyEntries: number; maxConcurrent: number; maxPerCorrelationBucket: number; scoreFloor?: number; buySideCap?: number; huntMode?: string };
  reentryPolicy?: {
    maxAttemptsPerIndex: number;
    targetCooldownMin: number;
    profitTrailCooldownMin: number;
    sameDirectionStopCooldownMin: number;
    riskScale: number;
  };
  error?: string;
};

type PaperPosition = {
  id: string; index: string; symbol: string; direction: string; quantity: number; status: string;
  entryPremium: number; currentPremium: number; effectiveStopPremium: number; targetPremium: number;
  unrealizedPnl?: number; pnl?: number; pnlPct?: number; exitReason?: string; enteredAt?: string;
  markSource?: string; markedAt?: string; markStatus?: string; markError?: string | null;
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

function fmtNum(value: number | null | undefined, digits = 2) {
  return value == null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: digits });
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
  if (source === 'LEMONN_FALLBACK') return 'Option Backup B';
  if (source === 'SCANX_FALLBACK') return 'Option Backup A';
  return 'Angel One';
}

function candidateHeadline(row: Candidate) {
  const bars = row.structure?.barCount ?? 0;
  if (row.state === 'ELIGIBLE') return 'All gates passed';
  if (row.state === 'WATCH') return 'Score below 80';
  if (row.reason.startsWith('HARD_GATE_FAILED:') && row.failedGates.includes('fresh')) {
    return bars === 0 ? 'Quotes not live' : 'Stale quotes';
  }
  if (row.reason.startsWith('HARD_GATE_FAILED:')) {
    return `Blocked: ${row.failedGates.map((key) => GATE_LABEL[key] ?? key).join(' · ')}`;
  }
  if (row.reason.startsWith('DATA_INCOMPLETE:')) {
    if (bars === 0) return '5m price feed unavailable';
    if (bars < 20) return `EMA20 warm-up · ${20 - bars} bars left`;
    return 'Waiting for required evidence';
  }
  if (row.reason === 'DIRECTION_NOT_PROVEN') return 'No ORB breakout';
  return 'No trade';
}

function compactEvidence(row: Candidate) {
  const evidence = row.gateEvidence;
  if (!evidence) return [];
  const breadth = evidence.breadth;
  const futures = evidence.futuresOi;
  const chain = evidence.optionChain;
  const rr = evidence.riskReward;
  return [
    { label: 'Fut OI', value: futures?.state?.replaceAll('_', ' ') ?? 'Missing', aligned: futures?.aligned },
    { label: 'Breadth', value: breadth?.score == null ? 'Missing' : `${(breadth.score * 100).toFixed(0)}% · ${fmtNum(breadth.coveragePct, 0)}% cov`, aligned: breadth?.aligned },
    { label: 'Chain', value: chain?.reason?.replaceAll('_', ' ') ?? 'Missing', aligned: chain?.aligned },
    { label: 'R:R', value: rr?.expectedR == null ? rr?.basis?.replaceAll('_', ' ') ?? 'Missing' : `${fmtNum(rr.expectedR)}R · S ${fmtNum(rr.stop)} · T ${fmtNum(rr.target)}`, aligned: rr?.aligned },
  ];
}

function gateChips(row: Candidate) {
  const keys = [...row.failedGates, ...row.missingInputs].filter((name, index, list) => list.indexOf(name) === index);
  return keys.slice(0, 4).map((key) => GATE_LABEL[key] ?? key);
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
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    let inFlight = false;
    const refresh = () => {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true;
      loadRadar('/api/index-options', controller.signal)
        .then(setRadar)
        .catch((error) => {
          if (!controller.signal.aborted) setRadar({ success: false, candidates: [], selected: [], error: error instanceof Error ? error.message : 'Radar unavailable' });
        })
        .finally(() => {
          inFlight = false;
          if (!controller.signal.aborted) setLoading(false);
        });
    };
    refresh();
    const id = window.setInterval(refresh, 15_000);
    return () => {
      window.clearInterval(id);
      controller.abort();
    };
  }, [refreshToken]);

  return (
    <section className="ix-radar space-y-3" aria-label="Index options radar">
      <div className="desk-card p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="desk-panel-title text-[var(--fg-strong)]">INDEX OPTIONS RADAR</h2>
            <p className="mt-1 text-[11px] text-[var(--fg-muted)]">Direction first · futures OI · option chain · weighted constituents · contract economics</p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="desk-pill desk-pill--ok">Auto paper only</span>
            <span className="desk-pill desk-pill--muted">Continuous hunt</span>
            <span className="desk-pill desk-pill--muted">No minimum</span>
            <span className="desk-pill desk-pill--muted">Max {radar?.limits?.maxDailyEntries ?? 20}/day</span>
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
          const evidence = compactEvidence(row);
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
                  <div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">{row.score == null ? 'Pending' : row.score.toFixed(1)}</div>
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
              {evidence.length > 0 && (
                <div className="mt-2 grid w-full grid-cols-2 gap-1 border-t border-[var(--terminal-line)] pt-2 text-[9px]">
                  {evidence.map((item) => (
                    <div key={item.label} className="min-w-0">
                      <span className="uppercase tracking-wider text-[var(--fg-subtle)]">{item.label} </span>
                      <span className={item.aligned === true ? 'text-emerald-600' : item.aligned === false ? 'text-red-500' : 'text-[var(--fg-muted)]'}>
                        {item.value}
                      </span>
                    </div>
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

      {radar?.paperBook && (
        <div className="desk-card p-3 sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="desk-panel-title">PAPER OPTION BOOK</div>
              <div className="mt-1 text-[10px] text-[var(--fg-muted)]">
                Automatic paper fills · no broker orders · {radar.paperBook.entryCount ?? 0}/{radar.paperBook.dailyEntryCap ?? 20} entries
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5 text-[10px]">
              <span className="desk-pill desk-pill--muted">Open ₹{fmtNum(radar.paperBook.openPnl)}</span>
              <span className="desk-pill desk-pill--muted">Realized ₹{fmtNum(radar.paperBook.realizedPnl)}</span>
              <span className={(radar.paperBook.totalPnl ?? 0) >= 0 ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--warn'}>
                Total ₹{fmtNum(radar.paperBook.totalPnl)}
              </span>
            </div>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-[10px]">
              <thead className="uppercase tracking-wider text-[var(--fg-subtle)]">
                <tr><th className="pb-2">Contract</th><th>Index</th><th>Qty</th><th>Entry</th><th>Mark</th><th>Trail SL</th><th>Target</th><th>P&amp;L</th><th>Status</th></tr>
              </thead>
              <tbody>
                {[...(radar.paperBook.open ?? []), ...(radar.paperBook.closed ?? []).slice(-5).reverse()].map((position) => {
                  const pnl = position.status === 'OPEN' ? position.unrealizedPnl : position.pnl;
                  return (
                    <tr key={position.id} className="border-t border-[var(--terminal-line)] tabular-nums">
                      <td className="py-2 font-bold text-[var(--fg-strong)]">{position.symbol}</td><td>{position.index}</td><td>{position.quantity}</td>
                      <td>₹{fmtNum(position.entryPremium)}</td><td>₹{fmtNum(position.currentPremium)}</td>
                      <td>₹{fmtNum(position.effectiveStopPremium)}</td><td>₹{fmtNum(position.targetPremium)}</td>
                      <td className={(pnl ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-500'}>₹{fmtNum(pnl)}</td>
                      <td>
                        <div>{position.status === 'CLOSED' ? position.exitReason ?? 'CLOSED' : 'OPEN'}</div>
                        {position.markSource && <div className="text-[8px] text-[var(--fg-subtle)]">{position.markSource.replaceAll('_', ' ')}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {loading && <div className="glass-skeleton h-16 rounded-xl" aria-hidden />}
      {!loading && radar?.candidates.length === 0 && !radar.error && (
        <div className="desk-card p-4 text-[12px] text-[var(--fg-muted)]">No index instruments returned.</div>
      )}

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
