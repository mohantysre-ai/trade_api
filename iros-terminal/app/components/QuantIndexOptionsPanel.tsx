'use client';

import { useEffect, useMemo, useState } from 'react';

type Decision = {
  strategy_id: string;
  index: string;
  utility: number;
  expected_value: number;
  cvar95: number;
  stress_loss: number;
  transaction_cost: number;
  decision: string;
  reasons?: string[];
};

type Leg = {
  side?: string;
  symbol?: string;
  strike?: number;
  optionType?: string;
  expiry?: string;
  qty?: number;
  lotSize?: number;
  entryFill?: number;
  entryPrice?: number;
  currentPrice?: number;
  currentBid?: number;
  currentAsk?: number;
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  markedAt?: string;
};

type Position = {
  strategyPositionId: string;
  strategyId: string;
  index?: string;
  status: string;
  expiry?: string;
  enteredAt?: string;
  updatedAt?: string;
  entrySpot?: number;
  currentSpot?: number;
  entryDebit?: number;
  entryCredit?: number;
  entryValue?: number;
  combinedStructureValue?: number;
  unrealizedPnl?: number;
  realizedPnl?: number;
  maxLoss?: number;
  maxProfit?: number;
  markStatus?: string;
  exitedAt?: string;
  exitReason?: string;
  breakevens?: number[];
  exitGreeks?: Record<string, number>;
  netGreeks?: Record<string, number>;
  legs?: Leg[];
};

type Radar = {
  success: boolean;
  updatedAt?: string;
  sessionStatus?: string;
  huntActive?: boolean;
  selectionAuthority?: string;
  streamStatus?: { connected?: boolean; subscribed?: number; lastTickAt?: string };
  quantDecision?: {
    engine?: string;
    model?: string;
    decision?: string;
    noTradeUtility?: number;
    selected?: Decision[];
    ranked?: Decision[];
    rejected?: Decision[];
    portfolioRisk?: {
      pass?: boolean;
      stressLoss?: number;
      greeks?: Record<string, number>;
      limits?: Record<string, number>;
    };
  };
  strategyBook?: { open?: Position[]; closed?: Position[] };
  sessionDate?: string;
  paperBook?: { entryCount?: number; closedCount?: number; realizedPnl?: number; openPnl?: number; totalPnl?: number };
  error?: string;
};

const n = (value?: number | null, digits = 2) =>
  value == null || Number.isNaN(value)
    ? '—'
    : value.toLocaleString('en-IN', { maximumFractionDigits: digits });
const money = (value?: number | null) => (value == null || Number.isNaN(value) ? '—' : `₹${n(value, 0)}`);
const label = (value?: string | null) => value?.replaceAll('_', ' ') ?? '—';
const sideClass = (side?: string) =>
  String(side || '').toUpperCase() === 'BUY'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-rose-200 bg-rose-50 text-rose-700';
const pnlClass = (value?: number) => ((value ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-500');
const UI_VERSION = 'LEG_TICKET_UI_V3';

function legPnl(leg: Leg): number | null {
  const entry = leg.entryFill ?? leg.entryPrice;
  const current = leg.currentPrice;
  if (entry == null || current == null) return null;
  const side = String(leg.side || '').toUpperCase();
  const qty = Math.max(1, Number(leg.qty || 1)) * Math.max(1, Number(leg.lotSize || 1));
  const sign = side === 'SELL' ? -1 : 1;
  return (current - entry) * qty * sign;
}

function legActionLine(leg: Leg, fallbackExpiry?: string): string {
  const side = String(leg.side || '—').toUpperCase();
  const symbol = leg.symbol || 'contract unavailable';
  const expiry = leg.expiry || fallbackExpiry || 'expiry —';
  const strike = leg.strike == null ? 'strike —' : n(leg.strike, 0);
  const optionType = leg.optionType || 'CE/PE —';
  const qty = n((leg.qty || 1) * (leg.lotSize || 1), 0);
  const entry = money(leg.entryFill ?? leg.entryPrice);
  return `${side} ${qty} qty · ${symbol} · ${expiry} · ${strike} ${optionType} · entry ${entry}`;
}

function StrategyCard({ position }: { position: Position }) {
  const legs = position.legs ?? [];
  return (
    <div className="desk-card p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="desk-panel-title text-[var(--fg-strong)]">{position.index || '—'}</span>
            <span className="font-black text-[var(--fg-strong)]">{label(position.strategyId)}</span>
            <span className={position.markStatus === 'LIVE' ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--warn'}>
              {position.markStatus || position.status || '—'}
            </span>
          </div>
          <div className="mt-1 text-[10px] text-[var(--fg-muted)]">
            Expiry {position.expiry || '—'} · Entry spot {n(position.entrySpot, 2)} · Spot now {n(position.currentSpot, 2)}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-xl font-black tabular-nums ${pnlClass(position.unrealizedPnl)}`}>
            {money(position.unrealizedPnl)}
          </div>
          <div className="text-[10px] text-[var(--fg-muted)]">Max loss {money(position.maxLoss)}</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="Entry debit" value={money(position.entryDebit ?? position.entryValue)} />
        <Metric label="Structure mark" value={money(position.combinedStructureValue)} />
        <Metric label="Max profit" value={money(position.maxProfit)} />
        <Metric label="Updated" value={position.updatedAt ? new Date(position.updatedAt).toLocaleTimeString('en-IN') : '—'} />
      </div>

      <div className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="desk-panel-title text-emerald-600">TRADE TICKET · WHAT TO BUY / SELL</div>
          <span className="desk-pill desk-pill--ok">MANUAL EXECUTION</span>
        </div>
        {legs.length ? (
          <div className="mt-2 space-y-1">
            {legs.map((leg, index) => (
              <div key={`ticket-${leg.symbol || index}-${index}`} className="rounded-md border border-[var(--terminal-line)] bg-[var(--surface)] px-2.5 py-2 text-[11px] font-bold text-[var(--fg-strong)]">
                {index + 1}. {legActionLine(leg, position.expiry)}
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 text-[11px] font-bold text-amber-600">
            Leg details are missing from the durable book, so this strategy is not actionable from the UI.
          </div>
        )}
      </div>

      <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--terminal-line)]">
        <table className="w-full min-w-[760px] text-left text-[10px]">
          <thead className="bg-[var(--surface-muted)] text-[var(--fg-subtle)]">
            <tr>
              <th className="px-2 py-2">Leg</th>
              <th>Contract</th>
              <th>Strike</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Mark</th>
              <th>Bid / Ask</th>
              <th>P&L</th>
              <th>Greeks Δ / Θ</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, index) => {
              const pnl = legPnl(leg);
              return (
                <tr key={`${leg.symbol || index}-${index}`} className="border-t border-[var(--terminal-line)]">
                  <td className="px-2 py-2">
                    <span className={`rounded border px-1.5 py-0.5 font-black ${sideClass(leg.side)}`}>
                      {String(leg.side || '—').toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <div className="font-bold text-[var(--fg-strong)]">{leg.symbol || '—'}</div>
                    <div className="text-[9px] text-[var(--fg-muted)]">{leg.expiry || position.expiry || '—'}</div>
                  </td>
                  <td>
                    <span className="font-bold">{n(leg.strike, 0)}</span>{' '}
                    <span className="text-[var(--fg-muted)]">{leg.optionType || '—'}</span>
                  </td>
                  <td>{n((leg.qty || 1) * (leg.lotSize || 1), 0)}</td>
                  <td>{money(leg.entryFill ?? leg.entryPrice)}</td>
                  <td>{money(leg.currentPrice)}</td>
                  <td>{money(leg.currentBid)} / {money(leg.currentAsk)}</td>
                  <td className={pnlClass(pnl ?? 0)}>{money(pnl)}</td>
                  <td>{n(leg.delta, 3)} / {n(leg.theta, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!legs.length && <div className="p-4 text-center text-[var(--fg-muted)]">No leg details in durable book.</div>}
      </div>
    </div>
  );
}

function ClosedPositionCard({ position }: { position: any }) {
  const exitReason = label(position.exitReason || 'CLOSED');
  const pnl = Number(position.realizedPnl ?? 0);
  return (
    <div className="desk-card p-3 sm:p-4 opacity-90">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="desk-panel-title text-[var(--fg-strong)]">{position.strategyId || '—'}</span>
            <span className="desk-pill desk-pill--warn">{position.status || 'CLOSED'}</span>
          </div>
          <div className="mt-1 text-[10px] text-[var(--fg-muted)]">
            Entered {position.enteredAt ? new Date(position.enteredAt).toLocaleString('en-IN') : '—'} · Exited {position.exitedAt ? new Date(position.exitedAt).toLocaleString('en-IN') : '—'}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-xl font-black tabular-nums ${pnlClass(pnl)}`}>
            {money(pnl)}
          </div>
          <div className="text-[10px] text-[var(--fg-muted)]">Realized P&L</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="Max loss" value={money(position.maxLoss)} />
        <Metric label="Max profit" value={money(position.maxProfit)} />
        <Metric label="Exit reason" value={exitReason} />
        <Metric label="Unrealized" value={money(position.unrealizedPnl)} />
      </div>

      {position.breakevens?.length ? (
        <div className="mt-3 text-[10px] text-[var(--fg-muted)]">
          Breakevens: {position.breakevens.map((b: number) => n(b, 2)).join(' / ')}
        </div>
      ) : null}

      {position.exitGreeks ? (
        <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
          Exit Greeks: Δ {n(position.exitGreeks.delta, 3)} / Γ {n(position.exitGreeks.gamma, 5)} / Θ {n(position.exitGreeks.theta, 2)} / Vega {n(position.exitGreeks.vega, 2)}
        </div>
      ) : null}
    </div>
  );
}

function Metric({ label: metricLabel, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--terminal-line)] bg-[var(--surface-muted)] px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-wider text-[var(--fg-subtle)]">{metricLabel}</div>
      <div className="mt-1 font-bold tabular-nums text-[var(--fg-strong)]">{value}</div>
    </div>
  );
}

export default function QuantIndexOptionsPanel({ refreshToken = 0 }: { refreshToken?: number }) {
  const [radar, setRadar] = useState<Radar | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let busy = false;
    const run = async () => {
      if (busy || controller.signal.aborted) return;
      busy = true;
      try {
        const response = await fetch('/api/index-options', { cache: 'no-store', signal: controller.signal });
        const data = (await response.json()) as Radar;
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        setRadar(data);
      } catch (error) {
        if (!controller.signal.aborted) {
          setRadar({ success: false, error: error instanceof Error ? error.message : 'Quant desk unavailable' });
        }
      } finally {
        busy = false;
        setLoading(false);
        if (!controller.signal.aborted) timer = window.setTimeout(run, 5000);
      }
    };
    void run();
    return () => {
      controller.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [refreshToken]);

  const q = radar?.quantDecision;
  const ranked = q?.ranked ?? [];
  const open = radar?.strategyBook?.open ?? [];
  const closed = radar?.strategyBook?.closed ?? [];
  const isClosed = radar?.sessionStatus === 'CLOSED';
  const greek = q?.portfolioRisk?.greeks ?? {};
  const top = useMemo(() => ranked.slice(0, 10), [ranked]);

  return (
    <section className="ix-radar space-y-3" aria-label="Quant V2 index options desk">
      <div className="desk-card signal-widget signal-widget--radar p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="signal-live-orb" />
              <h2 className="desk-panel-title text-[var(--fg-strong)]">INDEX OPTIONS · QUANT V2</h2>
            </div>
            <p className="mt-1 text-[11px] text-[var(--fg-muted)]">
              Exact strategy legs · strikes · entry marks · durable paper book
            </p>
            <p className="mt-1 text-[9px] font-bold tracking-wider text-[var(--fg-subtle)]">{UI_VERSION}</p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <span className="desk-pill desk-pill--ok">SOLE SELECTION AUTHORITY</span>
            <span className="desk-pill desk-pill--muted">{q?.model ? label(q.model) : 'Loading model'}</span>
            <span className={radar?.streamStatus?.connected ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--warn'}>
              {radar?.streamStatus?.connected ? 'Stream live' : 'REST fallback'}
            </span>
            <span className="desk-pill desk-pill--muted">{radar?.sessionStatus ?? '—'}</span>
          </div>
        </div>
      </div>

      {radar?.error && <div className="desk-card p-3 text-red-500">{radar.error}</div>}

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        {[
          ['Decision', q?.decision],
          ['Candidates', ranked.length],
          ['Selected', q?.selected?.length ?? 0],
          ['Open', open.length],
          ['Net Δ', n(greek.delta, 3)],
          ['Net Γ', n(greek.gamma, 5)],
          ['Net Θ', n(greek.theta, 2)],
          ['Net Vega', n(greek.vega, 2)],
        ].map(([key, value]) => (
          <div key={String(key)} className="desk-card p-3">
            <div className="text-[9px] uppercase tracking-wider text-[var(--fg-subtle)]">{key}</div>
            <div className="mt-1 font-bold tabular-nums text-[var(--fg-strong)]">{String(value ?? '—')}</div>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="desk-panel-title text-[var(--fg-strong)]">
              {isClosed && !open.length ? 'CLOSED QUANT STRATEGIES' : 'OPEN QUANT STRATEGIES'}
            </div>
            <div className="mt-1 text-[10px] text-[var(--fg-muted)]">
              {isClosed && !open.length
                ? 'These positions were closed during today’s session.'
                : 'These are the actual paper positions with exact option contracts and strikes.'}
            </div>
          </div>
          <span className="desk-pill desk-pill--ok">
            {isClosed && !open.length ? `${closed.length} closed` : `${open.length} open`}
          </span>
        </div>
        {(isClosed && !open.length ? closed : open).map((position) =>
          isClosed && !open.length ? (
            <ClosedPositionCard key={position.strategyPositionId} position={position} />
          ) : (
            <StrategyCard key={position.strategyPositionId} position={position} />
          ),
        )}
        {!open.length && !closed.length && !loading && (
          <div className="desk-card py-6 text-center text-[var(--fg-muted)]">
            No open Quant V2 position · NO TRADE is valid.
          </div>
        )}
      </div>

      <div className="grid gap-2 md:grid-cols-3">
        <div className="desk-card p-3">
          <div className="desk-panel-title">PORTFOLIO RISK GOVERNOR</div>
          <div className="mt-2 text-xl font-bold">{q?.portfolioRisk?.pass === false ? 'BLOCKED' : 'WITHIN LIMITS'}</div>
          <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
            Stress loss {money(q?.portfolioRisk?.stressLoss)} · hard portfolio admission before durable lock
          </div>
        </div>
        <div className="desk-card p-3">
          <div className="desk-panel-title">NO-TRADE BENCHMARK</div>
          <div className="mt-2 text-xl font-bold tabular-nums">Utility {n(q?.noTradeUtility, 2)}</div>
          <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
            Positive utility must beat doing nothing after costs, tail, Greeks and concentration penalties.
          </div>
        </div>
        <div className="desk-card p-3">
          <div className="desk-panel-title">MARKET DECISION</div>
          <div className="mt-2 text-xl font-bold">
            {isClosed ? 'SESSION CLOSED' : (q?.decision ?? (loading ? 'CALCULATING' : 'NO TRADE'))}
          </div>
          <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
            {isClosed ? 'EOD archive active — review closed positions below.' : (q?.engine ?? radar?.selectionAuthority ?? 'INDEX_OPTIONS_QUANT_V2')}
          </div>
        </div>
      </div>

      <div className="desk-card overflow-x-auto p-3">
        <div className="desk-panel-title text-[var(--fg-strong)]">STRUCTURE OPTIMIZER</div>
        <table className="mt-3 w-full min-w-[880px] text-left text-[10px]">
          <thead className="text-[var(--fg-subtle)]">
            <tr>
              <th className="py-2">Rank</th>
              <th>Index</th>
              <th>Structure</th>
              <th>Utility</th>
              <th>EV</th>
              <th>CVaR95</th>
              <th>Stress</th>
              <th>Cost</th>
              <th>Decision</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {top.map((decision, index) => (
              <tr key={`${decision.strategy_id}-${decision.index}-${index}`} className="border-t border-[var(--terminal-line)]">
                <td className="py-2">{index + 1}</td>
                <td>{decision.index}</td>
                <td className="font-bold">{label(decision.strategy_id)}</td>
                <td className={decision.utility > 0 ? 'text-emerald-600' : 'text-red-500'}>{n(decision.utility)}</td>
                <td>{money(decision.expected_value)}</td>
                <td>{money(decision.cvar95)}</td>
                <td>{money(decision.stress_loss)}</td>
                <td>{money(decision.transaction_cost)}</td>
                <td>
                  <span className={decision.decision === 'ADMIT' ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--muted'}>
                    {decision.decision}
                  </span>
                </td>
                <td>{label(decision.reasons?.join(' · '))}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!top.length && !loading && <div className="py-5 text-center text-[var(--fg-muted)]">No repriced structures available.</div>}
      </div>
    </section>
  );
}
