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

const tone = (state: Candidate['state']) =>
  state === 'ELIGIBLE'
    ? 'border-emerald-500/50 text-emerald-600'
    : state === 'WATCH'
      ? 'border-amber-500/50 text-amber-600'
      : 'border-[var(--terminal-line)] text-[var(--fg-muted)]';

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

function structureLine(row: Structure | null | undefined) {
  if (!row) return '5m candles —';
  const bars = row.barCount == null ? '—' : String(row.barCount);
  return `5m ${bars} bars · ORB ${fmtNum(row.orbHigh)} / ${fmtNum(row.orbLow)} · EMA9/20 ${fmtNum(row.ema9, 1)} / ${fmtNum(row.ema20, 1)}`;
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
  const buyPnl = buySide.reduce<number | null>((sum, row) => {
    if (row.pnlRupees == null) return sum;
    return (sum ?? 0) + row.pnlRupees;
  }, null);
  const implementedPnl = implemented.reduce<number | null>((sum, row) => {
    if (row.pnlRupees == null) return sum;
    return (sum ?? 0) + row.pnlRupees;
  }, null);

  return (
    <section className="space-y-3" aria-label="Index options radar">
      <div className="desk-card p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="desk-panel-title text-[var(--fg-strong)]">INDEX OPTIONS RADAR</h2>
            <p className="mt-1 text-[10px] text-[var(--fg-muted)]">Direction first · futures OI · option chain · weighted constituents · contract economics</p>
          </div>
          <div className="flex flex-wrap gap-2 text-[9px] font-bold uppercase tracking-wider">
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Manual only</span>
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Max {radar?.limits?.maxDailyEntries ?? 10}/day</span>
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Max {radar?.limits?.maxConcurrent ?? 2} open</span>
            {radar?.cacheStatus === 'STALE' && <span className="rounded border border-amber-500/40 px-2 py-1 text-amber-600">Stale cache</span>}
          </div>
        </div>
        <p className="mt-2 text-[9px] leading-relaxed text-[var(--fg-subtle)]">
          Max 10/day is a session entry cap, not a 10-name basket. Correlation allows one BROAD (NIFTY or SENSEX) and one FINANCIAL (BANKNIFTY or FINNIFTY) at a time.
        </p>
      </div>

      {radar?.error && <div className="desk-card border border-red-500/40 p-3 text-xs text-red-600">{radar.error}</div>}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {(radar?.candidates ?? []).map((row) => (
          <article key={row.key} className={`desk-card border-l-2 p-3 ${tone(row.state)}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-xs font-black text-[var(--fg-strong)]">{row.label}</div>
                <div className="mt-0.5 text-[9px] uppercase tracking-wider text-[var(--fg-subtle)]">{row.exchange} · {row.bucket}</div>
              </div>
              <span className="text-[9px] font-black">{row.state.replace('_', ' ')}</span>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-[9px]">
              <div><div className="text-[var(--fg-subtle)]">SPOT</div><div className="mt-0.5 font-bold text-[var(--fg-strong)]">{fmtSpot(row.spot)}</div></div>
              <div><div className="text-[var(--fg-subtle)]">SIDE</div><div className="mt-0.5 font-bold text-[var(--fg-strong)]">{row.direction ?? '—'}</div></div>
              <div><div className="text-[var(--fg-subtle)]">SCORE</div><div className="mt-0.5 font-bold text-[var(--fg-strong)]">{row.score == null ? 'UNRATED' : row.score.toFixed(1)}</div></div>
            </div>
            <div className="mt-2 text-[8px] text-[var(--fg-subtle)]">{structureLine(row.structure)}</div>
            <div className="mt-3 border-t border-[var(--terminal-line)] pt-2 text-[9px] leading-relaxed text-[var(--fg-muted)]">
              {row.reason}
            </div>
            {row.contract && <div className="mt-2 rounded border border-[var(--terminal-line)] p-2 text-[8px] text-[var(--fg-muted)]">
              <div className="font-bold text-[var(--fg-strong)]">{row.dataSource === 'SCANX_FALLBACK' ? 'SCANX FALLBACK' : 'ANGEL'} · {row.contract.symbol ?? row.contract.strike ?? '—'} · ₹{row.contract.ltp ?? '—'}</div>
              <div className="mt-1">Δ {row.contract.delta ?? '—'} · Γ {row.contract.gamma ?? '—'} · Θ {row.contract.theta ?? '—'} · Vega {row.contract.vega ?? '—'} · IV {row.contract.iv ?? '—'}</div>
            </div>}
            {(row.chain?.length ?? 0) > 0 && <div className="mt-2 overflow-x-auto">
              <table className="w-full text-[7px] text-[var(--fg-muted)]">
                <thead><tr className="text-[var(--fg-subtle)]"><th className="text-left">SIDE</th><th className="text-right">STRIKE</th><th className="text-right">LTP</th><th className="text-right">ΔOI</th><th className="text-right">DELTA</th><th className="text-right">IV</th></tr></thead>
                <tbody>{(row.chain ?? []).slice(0, 6).map((item) => <tr key={item.symbol} className="border-t border-[var(--terminal-line)]">
                  <td>{item.optionType}</td><td className="text-right">{item.strike ?? '—'}</td><td className="text-right">{item.ltp ?? '—'}</td><td className="text-right">{item.oiChange ?? '—'}</td><td className="text-right">{item.delta ?? '—'}</td><td className="text-right">{item.iv ?? '—'}</td>
                </tr>)}</tbody>
              </table>
            </div>}
            {row.missingInputs.length > 0 && <div className="mt-2 text-[8px] uppercase tracking-wide text-[var(--fg-subtle)]">Awaiting: {row.missingInputs.join(' · ')}</div>}
          </article>
        ))}
      </div>

      {!loading && radar?.candidates.length === 0 && !radar.error && <div className="desk-card p-4 text-xs text-[var(--fg-muted)]">No index instruments returned.</div>}
      {loading && <div className="desk-card p-4 text-xs text-[var(--fg-muted)]">Loading deterministic index-options evidence…</div>}

      <div className="desk-card p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="desk-panel-title text-[var(--fg-strong)]">FRIDAY SESSION REPLAY</h3>
            <p className="mt-1 text-[10px] text-[var(--fg-muted)]">
              {replay?.sessionDate ?? 'last Friday'} · paper long premium from 5m candles · gates not overridden
            </p>
          </div>
          <div className="flex gap-2 text-[9px] font-bold uppercase tracking-wider">
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Implemented P&amp;L {fmtPnl(implementedPnl)}</span>
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Listed buy-side {fmtPnl(buyPnl)}</span>
          </div>
        </div>
        {replay?.disclaimer && <p className="mt-2 text-[9px] leading-relaxed text-[var(--fg-subtle)]">{replay.disclaimer}</p>}
        {replay?.error && <div className="mt-2 text-xs text-red-600">{replay.error}</div>}
        {replayLoading && <div className="mt-3 text-[10px] text-[var(--fg-muted)]">Fetching Friday 5m index and option candles…</div>}

        <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
          {(replay?.indices ?? []).map((row) => (
            <div key={row.key} className="rounded border border-[var(--terminal-line)] p-2">
              <div className="flex items-center justify-between gap-2 text-[10px] font-black text-[var(--fg-strong)]">
                <span>{row.label ?? row.key}</span>
                <span className="text-[8px] uppercase text-[var(--fg-subtle)]">{row.selected ? 'Selected' : 'Blocked'}</span>
              </div>
              <div className="mt-1 text-[9px] text-[var(--fg-muted)]">Spot {fmtSpot(row.spot)} · {row.firstDirection ?? 'NO BREAKOUT'}</div>
              <div className="mt-1 text-[8px] text-[var(--fg-subtle)]">{structureLine(row.structure)}</div>
              {row.confirmedAt && <div className="mt-1 text-[8px] text-[var(--fg-subtle)]">Confirmed {row.confirmedAt}</div>}
              {row.error && <div className="mt-1 text-[8px] text-red-600">{row.error}</div>}
            </div>
          ))}
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[8px] text-[var(--fg-muted)]">
            <thead>
              <tr className="text-[var(--fg-subtle)]">
                <th className="text-left">CONTRACT</th>
                <th className="text-left">INDEX</th>
                <th className="text-right">STRIKE</th>
                <th className="text-right">5M</th>
                <th className="text-right">ENTRY</th>
                <th className="text-right">EXIT</th>
                <th className="text-right">PTS</th>
                <th className="text-right">P&amp;L ₹</th>
                <th className="text-left">NOTE</th>
              </tr>
            </thead>
            <tbody>
              {buySide.map((row) => (
                <tr key={`${row.index}-${row.symbol}`} className="border-t border-[var(--terminal-line)]">
                  <td className="py-1 font-bold text-[var(--fg-strong)]">{row.symbol ?? '—'}{row.implemented ? ' · IMPL' : ''}</td>
                  <td>{row.index}</td>
                  <td className="text-right">{fmtNum(row.strike, 0)}</td>
                  <td className="text-right">{row.barCount ?? '—'}</td>
                  <td className="text-right">{fmtNum(row.entry)}</td>
                  <td className="text-right">{fmtNum(row.exit)}</td>
                  <td className="text-right">{fmtPnl(row.pnlPoints)}</td>
                  <td className="text-right">{fmtPnl(row.pnlRupees)}</td>
                  <td>{row.limitation ?? row.blockedBy ?? (row.atmProxy ? 'ATM proxy · greeks unavailable' : '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!replayLoading && buySide.length === 0 && !replay?.error && (
            <div className="mt-2 text-[10px] text-[var(--fg-muted)]">No buy-side contracts: Friday 5m ORB+EMA did not confirm CALL/PUT, or option tokens were unavailable.</div>
          )}
        </div>
        {(replay?.limitations?.length ?? 0) > 0 && (
          <div className="mt-3 text-[8px] uppercase tracking-wide text-[var(--fg-subtle)]">Limitations: {(replay?.limitations ?? []).join(' · ')}</div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="desk-card p-3">
          <h3 className="desk-panel-title text-[var(--fg-strong)]">CORRELATION GUARD</h3>
          <p className="mt-2 text-[10px] leading-relaxed text-[var(--fg-muted)]">Only one of NIFTY/SENSEX and one of BANKNIFTY/FINNIFTY can be selected. A missing chain, stale quote, failed hard gate, or score below 80 cannot be overridden.</p>
        </div>
        <div className="desk-card p-3">
          <h3 className="desk-panel-title text-[var(--fg-strong)]">RE-ENTRY &amp; COOLDOWN GOVERNOR</h3>
          <p className="mt-2 text-[10px] leading-relaxed text-[var(--fg-muted)]">Two attempts per index. Target cooldown {radar?.reentryPolicy?.targetCooldownMin ?? 20}m; profitable trail {radar?.reentryPolicy?.profitTrailCooldownMin ?? 30}m; same-direction stop {radar?.reentryPolicy?.sameDirectionStopCooldownMin ?? 45}m. Every re-entry requires a fresh break, aligned OI and weighted breadth at {(radar?.reentryPolicy?.riskScale ?? 0.5) * 100}% risk.</p>
        </div>
      </div>
    </section>
  );
}
