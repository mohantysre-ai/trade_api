'use client';

import { useEffect, useState } from 'react';

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
};

type Radar = {
  success: boolean;
  updatedAt?: string | null;
  executionPolicy?: string;
  candidates: Candidate[];
  selected: Candidate[];
  limits?: { maxDailyEntries: number; maxConcurrent: number; maxPerCorrelationBucket: number; scoreFloor: number };
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

function fmtSpot(value: number | null) {
  return value == null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

export default function IndexOptionsPanel({ refreshToken = 0 }: { refreshToken?: number }) {
  const [radar, setRadar] = useState<Radar | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetch('/api/index-options', { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const data = await response.json() as Radar;
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        setRadar(data);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setRadar({ success: false, candidates: [], selected: [], error: error instanceof Error ? error.message : 'Radar unavailable' });
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshToken]);

  return (
    <section className="space-y-3" aria-label="Index options radar">
      <div className="desk-card p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="desk-panel-title text-[var(--fg-strong)]">INDEX OPTIONS RADAR</h2>
            <p className="mt-1 text-[10px] text-[var(--fg-muted)]">Direction first · futures OI · option chain · weighted constituents · contract economics</p>
          </div>
          <div className="flex gap-2 text-[9px] font-bold uppercase tracking-wider">
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Manual only</span>
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Max {radar?.limits?.maxDailyEntries ?? 10}/day</span>
            <span className="rounded border border-[var(--terminal-line)] px-2 py-1 text-[var(--fg-muted)]">Max {radar?.limits?.maxConcurrent ?? 2} open</span>
          </div>
        </div>
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
            <div className="mt-3 border-t border-[var(--terminal-line)] pt-2 text-[9px] leading-relaxed text-[var(--fg-muted)]">
              {row.reason}
            </div>
            {row.contract && <div className="mt-2 rounded border border-[var(--terminal-line)] p-2 text-[8px] text-[var(--fg-muted)]">
              <div className="font-bold text-[var(--fg-strong)]">{row.dataSource === 'LEMONN_FALLBACK' ? 'LEMONN FALLBACK' : row.dataSource === 'SCANX_FALLBACK' ? 'SCANX FALLBACK' : 'ANGEL'} · {row.contract.symbol ?? row.contract.strike ?? '—'} · ₹{row.contract.ltp ?? '—'}</div>
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
