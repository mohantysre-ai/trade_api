'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  buildIndexOptionsView,
  fmtLabel as label,
  fmtMoney as money,
  fmtNum as n,
  type IndexOptionsView,
  type Leg,
  type Metric as MetricRow,
  type Position,
  type Radar,
} from '../../lib/index-options-vm';

const sideClass = (side?: string) =>
  String(side || '').toUpperCase() === 'BUY'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-rose-200 bg-rose-50 text-rose-700';
const pnlClass = (value?: number | null) => ((value ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-500');
const UI_VERSION = 'LEG_TICKET_UI_V4';

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

function MiniTile({ label: metricLabel, value }: { label: string; value: string }) {
  return (
    <div className="desk-metric-tile min-w-0 overflow-hidden">
      <div className="desk-metric-label w-full min-w-0">{metricLabel}</div>
      <div className="desk-metric-value tabular-nums w-full min-w-0">{value}</div>
    </div>
  );
}

/** Stat tile for the top metrics row — same chrome as the shared dashboard KPI tiles. */
function StatCard({ metric }: { metric: MetricRow }) {
  const toneClass =
    metric.tone === 'ok'
      ? 'text-emerald-500'
      : metric.tone === 'warn'
        ? 'text-amber-500'
        : metric.tone === 'danger'
          ? 'text-red-500'
          : 'text-[var(--fg-strong)]';
  return (
    <div
      className="desk-metric-tile min-w-0 overflow-hidden"
      title={metric.hint ? `${metric.source} · ${metric.hint}` : metric.source}
      data-metric={metric.id}
      data-source={metric.source}
      data-nullable={metric.nullable ? 'true' : 'false'}
    >
      <div className="desk-metric-label w-full min-w-0">{metric.label}</div>
      <div className={`desk-metric-value tabular-nums w-full min-w-0 ${toneClass}`}>{metric.value}</div>
      {metric.hint ? (
        <div className="desk-metric-delta w-full min-w-0 text-[9px] text-[var(--fg-muted)]">{metric.hint}</div>
      ) : null}
    </div>
  );
}

/** Bordered section container so every block reads as a card, not loose text. */
function SectionCard({
  title,
  subtitle,
  badge,
  badgeClass = 'desk-pill--muted',
  children,
  className = '',
}: {
  title: string;
  subtitle?: string;
  badge?: string;
  badgeClass?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`desk-card p-3 sm:p-4 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="desk-panel-title text-[var(--fg-strong)]">{title}</div>
          {subtitle ? <div className="mt-1 text-[10px] text-[var(--fg-muted)]">{subtitle}</div> : null}
        </div>
        {badge ? <span className={`desk-pill ${badgeClass}`}>{badge}</span> : null}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function StrategyCard({ position }: { position: Position }) {
  const legs = position.legs ?? [];
  return (
    <div className="rounded-xl border-[var(--terminal-line)] bg-[var(--terminal-panel-2)] p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="desk-panel-title text-[var(--fg-strong)]">{position.index || '—'}</span>
            <span className="font-black text-[var(--fg-strong)]">{label(position.strategyId)}</span>
            <span
              className={position.markStatus === 'LIVE' ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--warn'}
            >
              {position.markStatus || position.status || '—'}
            </span>
          </div>
          <div className="mt-1 text-[10px] text-[var(--fg-muted)]">
            Expiry {position.expiry || '—'} · Entry spot {n(position.entrySpot, 2)} · Spot now{' '}
            {n(position.currentSpot, 2)}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-xl font-black tabular-nums ${pnlClass(position.unrealizedPnl)}`}>
            {money(position.unrealizedPnl)}
          </div>
          <div className="text-[10px] text-[var(--fg-muted)]">Max loss {money(position.maxLoss)}</div>
        </div>
      </div>

      <div className="mt-3 grid-cols-2 gap-2 sm:grid-cols-4">
        <MiniTile label="Entry debit" value={money(position.entryDebit ?? position.entryValue)} />
        <MiniTile label="Structure mark" value={money(position.combinedStructureValue)} />
        <MiniTile label="Max profit" value={money(position.maxProfit)} />
        <MiniTile
          label="Updated"
          value={position.updatedAt ? new Date(position.updatedAt).toLocaleTimeString('en-IN') : '—'}
        />
      </div>

      <div className="mt-3 rounded-lg border-[var(--terminal-line)] bg-emerald-500/10 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="desk-panel-title text-emerald-600">TRADE TICKET · WHAT TO BUY / SELL</div>
          <span className="desk-pill desk-pill--ok">MANUAL EXECUTION</span>
        </div>
        {legs.length ? (
          <div className="mt-2 space-y-1">
            {legs.map((leg, index) => (
              <div
                key={`ticket-${leg.symbol || index}-${index}`}
                className="rounded-md border-[var(--terminal-line)] bg-[var(--surface)] px-2.5 py-2 text-[11px] font-bold text-[var(--fg-strong)]"
              >
                {index + 1}. {legActionLine(leg, position.expiry)}
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-2 rounded-md border-[var(--terminal-line)] bg-amber-500/10 px-2.5 py-2 text-[11px] font-bold text-amber-600">
            Leg details are missing from the durable book, so this strategy is not actionable from the UI.
          </div>
        )}
      </div>

      <div className="mt-3 overflow-x-auto rounded-lg border-[var(--terminal-line)]">
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
                  <td>
                    {money(leg.currentBid)} / {money(leg.currentAsk)}
                  </td>
                  <td className={pnlClass(pnl)}>{money(pnl)}</td>
                  <td>
                    {n(leg.delta, 3)} / {n(leg.theta, 1)}
                  </td>
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

function ClosedPositionCard({ position, historical }: { position: Position; historical: boolean }) {
  const legs = position.legs ?? [];
  const exitReason = position.exitReason ? label(position.exitReason) : 'CLOSED';
  const pnl = position.realizedPnl != null ? Number(position.realizedPnl) : null;
  return (
    <div className="rounded-xl border-[var(--terminal-line)] bg-[var(--terminal-panel-2)] p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="desk-panel-title text-[var(--fg-strong)]">{position.index || '—'}</span>
            <span className="font-black text-[var(--fg-strong)]">{label(position.strategyId)}</span>
            <span className="desk-pill desk-pill--warn">{position.status || 'CLOSED'}</span>
            {historical ? <span className="desk-pill desk-pill--ok">DURABLE LEDGER</span> : null}
          </div>
          <div className="mt-1 text-[10px] text-[var(--fg-muted)]">
            Expiry {position.expiry || '—'} · Entry{' '}
            {position.enteredAt ? new Date(position.enteredAt).toLocaleString('en-IN') : '—'} · Exit{' '}
            {position.exitedAt ? new Date(position.exitedAt).toLocaleString('en-IN') : '—'}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-xl font-black tabular-nums ${pnlClass(pnl)}`}>{money(pnl)}</div>
          <div className="text-[10px] text-[var(--fg-muted)]">Realized P&L · {exitReason}</div>
        </div>
      </div>

      <div className="mt-3 grid-cols-2 gap-2 sm:grid-cols-4">
        <MiniTile label="Max loss" value={money(position.maxLoss)} />
        <MiniTile label="Max profit" value={money(position.maxProfit)} />
        <MiniTile label="Entry debit" value={money(position.entryDebit ?? position.entryValue)} />
        <MiniTile label="Exit reason" value={exitReason} />
      </div>

      <div className="mt-3 overflow-x-auto rounded-lg border-[var(--terminal-line)]">
        <table className="w-full min-w-[760px] text-left text-[10px]">
          <thead className="bg-[var(--surface-muted)] text-[var(--fg-subtle)]">
            <tr>
              <th className="px-2 py-2">Leg</th>
              <th>Contract</th>
              <th>Strike</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>P&L</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, index) => {
              const exitFill = leg.exitFill ?? leg.currentPrice;
              const entryFill = leg.entryFill ?? leg.entryPrice;
              const signed =
                entryFill != null && exitFill != null
                  ? (exitFill - entryFill) *
                  Math.max(1, Number(leg.qty || 1)) *
                  Math.max(1, Number(leg.lotSize || 1)) *
                  (String(leg.side || '').toUpperCase() === 'SELL' ? -1 : 1)
                  : null;
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
                  <td>{money(entryFill)}</td>
                  <td>{money(exitFill)}</td>
                  <td className={pnlClass(signed)}>{money(signed)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!legs.length && (
          <div className="p-4 text-center text-[var(--fg-muted)]">Leg details are missing from the durable ledger.</div>
        )}
      </div>

      {position.breakevens?.length ? (
        <div className="mt-3 text-[10px] text-[var(--fg-muted)]">
          Breakevens: {position.breakevens.map((b: number) => n(b, 2)).join(' / ')}
        </div>
      ) : null}

      {position.exitGreeks ? (
        <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
          Exit Greeks: Δ {n(position.exitGreeks.delta, 3)} / Γ {n(position.exitGreeks.gamma, 5)} / Θ{' '}
          {n(position.exitGreeks.theta, 2)} / Vega {n(position.exitGreeks.vega, 2)}
        </div>
      ) : null}
    </div>
  );
}

/** Dev-only: prove which payload field drove each stat. Gated on NODE_ENV. */
function logProvenance(view: IndexOptionsView) {
  if (process.env.NODE_ENV === 'production') return;
  const lines = view.metrics.map((metric) => `${metric.label.padEnd(22)} ← ${metric.source}`);
  console.debug(
    `[INDEX OPTIONS ${view.isHistorical ? 'HISTORICAL' : 'LIVE'}] metric provenance\n${lines.join('\n')}`,
  );
}

export default function QuantIndexOptionsPanel({
  refreshToken = 0,
  sessionDate: sessionDateProp = '',
}: {
  refreshToken?: number;
  sessionDate?: string;
}) {
  const [radar, setRadar] = useState<Radar | null>(null);
  const [sessionDate, setSessionDate] = useState(sessionDateProp);
  const [loading, setLoading] = useState(true);

  useEffect(() => setSessionDate(sessionDateProp), [sessionDateProp]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let busy = false;
    const run = async () => {
      if (busy || controller.signal.aborted) return;
      busy = true;
      try {
        const query = sessionDate ? `?sessionDate=${encodeURIComponent(sessionDate)}` : '';
        const response = await fetch(`/api/index-options${query}`, { cache: 'no-store', signal: controller.signal });
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
        if (!controller.signal.aborted && !sessionDate) timer = window.setTimeout(run, 5000);
      }
    };
    void run();
    return () => {
      controller.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [refreshToken, sessionDate]);

  const view = useMemo<IndexOptionsView | null>(
    () => (radar ? buildIndexOptionsView(radar, { sessionDate, loading }) : null),
    [radar, sessionDate, loading],
  );

  useEffect(() => {
    if (view) logProvenance(view);
  }, [view]);

  const q = radar?.quantDecision;
  const openPositions = view?.openPositions ?? [];
  const closedPositions = view?.closedPositions ?? [];
  const isHistorical = view?.isHistorical ?? Boolean(sessionDate);
  const listMode = view?.listMode ?? 'EMPTY';
  const showClosed = listMode === 'CLOSED' || (isHistorical && closedPositions.length > 0 && openPositions.length === 0);
  const visiblePositions = showClosed ? closedPositions : openPositions;
  const top = useMemo(() => q?.ranked?.slice(0, 10) ?? [], [q]);
  const replayLimitations = radar?.replayDiagnostics?.limitations ?? [];
  const metrics = view?.metrics ?? [];

  return (
    <section className="ix-radar space-y-3" aria-label="Quant V2 index options desk">
      <div className="desk-card signal-widget signal-widget--radar p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="signal-live-orb" />
              <h2 className="desk-panel-title text-[var(--fg-strong)]">INDEX OPTIONS · QUANT V2</h2>
            </div>
            <p className="mt-1 text-[11px] text-[var(--fg-muted)]">
              Exact strategy legs · strikes · entry marks · durable paper book
            </p>
            <p className="mt-1 text-[9px] font-bold tracking-wider text-[var(--fg-subtle)]">
              {UI_VERSION} · {isHistorical ? 'HISTORICAL SESSION' : 'LIVE SESSION'}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <span className="desk-pill desk-pill--ok">SOLE SELECTION AUTHORITY</span>
            <span className="desk-pill desk-pill--muted">COMMON SCENARIO DISTRIBUTION REPRICER</span>
            <span className={radar?.streamStatus?.connected ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--warn'}>
              {radar?.streamStatus?.connected ? 'STREAM LIVE' : 'REST FALLBACK'}
            </span>
            <span className="desk-pill desk-pill--muted">
              {isHistorical ? 'CLOSED' : (radar?.sessionStatus ?? '—')}
            </span>
            <label className="desk-pill desk-pill--muted flex items-center gap-1">
              Session
              <input
                type="date"
                value={sessionDate}
                onChange={(event) => setSessionDate(event.target.value)}
                className="bg-transparent text-[10px] font-bold text-[var(--fg-strong)] outline-none"
              />
            </label>
            {sessionDate && (
              <button type="button" onClick={() => setSessionDate('')} className="desk-pill desk-pill--ok">
                Live session
              </button>
            )}
          </div>
        </div>
      </div>

      {radar?.error && <div className="desk-card p-3 text-red-500">{radar.error}</div>}

      <div className="desk-metric-grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
        {metrics.map((metric) => (
          <StatCard key={metric.id} metric={metric} />
        ))}
      </div>

      <SectionCard
        title={showClosed ? 'CLOSED QUANT STRATEGIES' : 'OPEN QUANT STRATEGIES'}
        subtitle={
          isHistorical
            ? 'Actual executed positions from the durable Quant V2 ledger.'
            : showClosed
              ? "These positions were closed during today's session."
              : 'These are the actual paper positions with exact option contracts and strikes.'
        }
        badge={
          showClosed
            ? isHistorical
              ? `${closedPositions.length} executed`
              : `${closedPositions.length} closed`
            : `${openPositions.length} open`
        }
        badgeClass={visiblePositions.length ? 'desk-pill--ok' : 'desk-pill--muted'}
      >
        <div className="space-y-3">
          {visiblePositions.map((position) =>
            showClosed ? (
              <ClosedPositionCard
                key={position.strategyPositionId}
                position={position}
                historical={isHistorical}
              />
            ) : (
              <StrategyCard key={position.strategyPositionId} position={position} />
            ),
          )}
          {!visiblePositions.length && !loading && (
            <div className="rounded-xl border-[var(--terminal-line)] bg-[var(--terminal-panel-2)] py-6 text-center text-[var(--fg-muted)]">
              {isHistorical ? (
                <>
                  No executed Quant V2 position for this session.
                  <span className="mt-1 block text-[10px]">
                    Qualification History: {view?.qualificationAvailable ? 'archived' : 'Not Archived'}
                  </span>
                </>
              ) : (
                'No open Quant V2 position · NO TRADE is valid.'
              )}
            </div>
          )}
        </div>
      </SectionCard>

      <div className="grid gap-3 md:grid-cols-3">
        <SectionCard
          title="PORTFOLIO RISK GOVERNOR"
          badge={q?.portfolioRisk?.pass === false ? 'BLOCKED' : 'WITHIN LIMITS'}
          badgeClass={q?.portfolioRisk?.pass === false ? 'desk-pill--warn' : 'desk-pill--ok'}
        >
          <div className="desk-metric-value tabular-nums">
            {q?.portfolioRisk?.pass === false ? 'BLOCKED' : 'WITHIN LIMITS'}
          </div>
          <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
            Stress loss {money(q?.portfolioRisk?.stressLoss)} · hard portfolio admission before durable lock
          </div>
        </SectionCard>

        <SectionCard title="NO-TRADE BENCHMARK" badge="DO NOTHING FLOOR" badgeClass="desk-pill--muted">
          <div className="desk-metric-value tabular-nums">Utility {n(q?.noTradeUtility, 2)}</div>
          <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
            Positive utility must beat doing nothing after costs, tail, Greeks and concentration penalties.
          </div>
        </SectionCard>

        <SectionCard
          title="MARKET DECISION"
          badge={isHistorical ? 'HISTORICAL' : (radar?.sessionStatus ?? '—')}
          badgeClass={isHistorical ? 'desk-pill--muted' : 'desk-pill--info'}
        >
          <div className="desk-metric-value">
            {isHistorical ? 'HISTORICAL SESSION' : (view?.decision ?? (loading ? 'CALCULATING' : 'NO TRADE'))}
          </div>
          <div className="mt-2 text-[10px] text-[var(--fg-muted)]">
            {isHistorical
              ? `Durable executions: ${view?.executed ?? '—'} · Qualification history: ${view?.qualificationAvailable ? 'archived' : 'not archived'
              }`
              : (q?.engine ?? radar?.selectionAuthority ?? 'INDEX_OPTIONS_QUANT_V2')}
          </div>
        </SectionCard>
      </div>

      {isHistorical && replayLimitations.length > 0 && (
        <SectionCard
          title="REPLAY DIAGNOSTICS · LIMITATIONS"
          subtitle="Historical live eligibility gates were not fully archived. Replay is analytical only and does not override durable executions."
          badge="ANALYTICAL ONLY"
          badgeClass="desk-pill--warn"
        >
          <div className="flex flex-wrap gap-1.5">
            {replayLimitations.map((limitation) => (
              <span key={limitation} className="desk-pill desk-pill--warn">
                {limitation}
              </span>
            ))}
          </div>
        </SectionCard>
      )}

      {isHistorical && view?.qualificationAvailable && (
        <SectionCard
          title="QUALIFICATION HISTORY · VERIFIED"
          subtitle="Immutable decision audit from the durable Quant V2 ledger."
          badge="ARCHIVED"
          badgeClass="desk-pill--ok"
        >
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            {(
              [
                ['Evaluated', radar?.historicalQualification?.evaluatedCount],
                ['Elig', radar?.historicalQualification?.eligibleCount],
                ['Qualified', radar?.historicalQualification?.qualifiedCount],
                ['Selected', radar?.historicalQualification?.selectedCount],
                ['Executed', radar?.historicalQualification?.executedCount],
                ['Rejected', radar?.historicalQualification?.rejectedCount],
                ['Entry blocked', radar?.historicalQualification?.entryBlockedCount],
              ] as Array<[string, number | undefined]>
            ).map(([key, value]) => (
              <MiniTile key={key} label={key} value={value == null ? '—' : String(value)} />
            ))}
          </div>
          {radar?.historicalQualification?.rejectionSummary &&
            Object.keys(radar.historicalQualification.rejectionSummary).length > 0 && (
              <div className="mt-3">
                <div className="text-[9px] uppercase tracking-wider text-[var(--fg-subtle)]">Rejection reasons</div>
                <div className="mt-1 flex-wrap gap-1.5">
                  {Object.entries(radar.historicalQualification.rejectionSummary).map(([reason, count]) => (
                    <span key={reason} className="desk-pill desk-pill--muted">
                      {label(reason)}: {count}
                    </span>
                  ))}
                </div>
              </div>
            )}
        </SectionCard>
      )}

      {isHistorical && view?.qualificationAvailable && radar?.candidateHistory?.length ? (
        <SectionCard title="CANDIDATE AUDIT TRAIL" className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-left text-[10px]">
            <thead className="text-[var(--fg-subtle)]">
              <tr>
                <th className="py-2">Time</th>
                <th>Index</th>
                <th>Strategy</th>
                <th>State</th>
                <th>Rank</th>
                <th>Utility</th>
                <th>Risk</th>
                <th>Selected</th>
                <th>Executed</th>
                <th>Reasons</th>
              </tr>
            </thead>
            <tbody>
              {radar.candidateHistory.map((candidate, idx) => (
                <tr
                  key={`${candidate.strategyId}-${candidate.index}-${idx}`}
                  className="border-t border-[var(--terminal-line)]"
                >
                  <td className="py-2">
                    {candidate.timestamp ? new Date(candidate.timestamp).toLocaleTimeString('en-IN') : '—'}
                  </td>
                  <td>{candidate.index || '—'}</td>
                  <td>{label(candidate.strategyId)}</td>
                  <td>
                    <span
                      className={`desk-pill ${candidate.status === 'EXECUTED' || candidate.status === 'SELECTED'
                          ? 'desk-pill--ok'
                          : candidate.status === 'ENTRY_BLOCKED'
                            ? 'desk-pill--warn'
                            : 'desk-pill--muted'
                        }`}
                    >
                      {label(candidate.status)}
                    </span>
                  </td>
                  <td>{candidate.rank ?? '—'}</td>
                  <td className={candidate.utility && candidate.utility > 0 ? 'text-emerald-600' : 'text-red-500'}>
                    {n(candidate.utility, 2)}
                  </td>
                  <td>{candidate.riskGatePassed ? 'PASS' : 'FAIL'}</td>
                  <td>{candidate.selected ? 'YES' : 'NO'}</td>
                  <td>{candidate.executed ? 'YES' : 'NO'}</td>
                  <td>{label((candidate.reasons || []).join(' · '))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      ) : null}

      <SectionCard
        title="STRUCTURE OPTIMIZER · RANKED CANDIDATES"
        subtitle={isHistorical ? 'Replay repricing is analytical only.' : 'Common scenario distribution repricer.'}
        badge={`${top.length} ranked`}
        badgeClass="desk-pill--muted"
        className="overflow-x-auto"
      >
        <table className="w-full min-w-[880px] text-left text-[10px]">
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
              <tr
                key={`${decision.strategy_id}-${decision.index}-${index}`}
                className="border-t border-[var(--terminal-line)]"
              >
                <td className="py-2">{index + 1}</td>
                <td>{decision.index}</td>
                <td className="font-bold">{label(decision.strategy_id)}</td>
                <td className={decision.utility > 0 ? 'text-emerald-600' : 'text-red-500'}>{n(decision.utility)}</td>
                <td>{money(decision.expected_value)}</td>
                <td>{money(decision.cvar95)}</td>
                <td>{money(decision.stress_loss)}</td>
                <td>{money(decision.transaction_cost)}</td>
                <td>
                  <span
                    className={decision.decision === 'ADMIT' ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--muted'}
                  >
                    {decision.decision}
                  </span>
                </td>
                <td>{label(decision.reasons?.join(' · '))}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!top.length && !loading && (
          <div className="py-5 text-center text-[var(--fg-muted)]">No repriced structures available.</div>
        )}
      </SectionCard>
    </section>
  );
}
