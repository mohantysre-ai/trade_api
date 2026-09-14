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
  direction: 'CALL' | 'PUT' | 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null;
  bias?: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null;
  strategyMode?: 'BUY_PREMIUM' | 'SELL_PREMIUM';
  strategyType?: string | null;
  strategyId?: string | null;
  family?: string | null;
  constructionStatus?: string | null;
  state: 'ELIGIBLE' | 'WATCH' | 'NO_TRADE';
  eligible?: boolean;
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
    breadth?: {
      score?: number | null; directionalScore?: number | null; coveragePct?: number | null;
      aligned?: boolean | null; strictAligned?: boolean | null; source?: string; classification?: string;
      confirmationMode?: string; reason?: string; alignmentFloor?: number | null; adaptiveFloor?: number | null; earlyFloor?: number | null;
      bullishPct?: number | null; bearishPct?: number | null; neutralPct?: number | null; quoteProxyPct?: number | null;
    };
    contractEconomics?: { aligned?: boolean | null; greeksSource?: string | null; spreadPct?: number | null };
    riskReward?: { aligned?: boolean | null; expectedR?: number | null; basis?: string; stop?: number | null; target?: number | null; minimumR?: number | null };
    structure?: { aligned?: boolean | null; status?: string; barCount?: number | null };
    futuresRegime?: { aligned?: boolean | null; state?: string; priceChangePct?: number | null };
    volatilityEdge?: { aligned?: boolean | null; shortIv?: number | null; indiaVix?: number | null; ivEdgePoints?: number | null; ivToVix?: number | null };
    definedRisk?: { aligned?: boolean | null; creditToRisk?: number | null; minimum?: number | null; maxLossPerLot?: number | null };
    thetaCarry?: { aligned?: boolean | null; netTheta?: number | null; netGamma?: number | null; gammaCap?: number | null };
    tailBuffer?: { aligned?: boolean | null; minimumBufferAtr?: number | null; minimum?: number | null };
    timeWindow?: { aligned?: boolean | null; reason?: string; daysToExpiry?: number | null; entryCutoffIst?: string };
    construction?: { reason?: string; chainContracts?: number; uniqueStrikes?: number; usableContracts?: number; lowestStrike?: number | null; highestStrike?: number | null; structureStatus?: string; missingLegs?: string[] };
  };
  legs?: Array<{ action?: 'BUY' | 'SELL'; side?: 'BUY' | 'SELL'; role?: string; symbol?: string; strike?: number; optionType?: string; expiry?: string; entryPrice?: number; entryFill?: number; ltp?: number; delta?: number; theta?: number; iv?: number; spreadPct?: number; lotSize?: number }>;
  risk?: { entryCredit?: number | null; maxProfitPerLot?: number | null; maxLossPerLot?: number | null; creditToRisk?: number | null; lowerBreakEven?: number | null; upperBreakEven?: number | null; minimumBufferAtr?: number | null };
  chain?: Array<{ symbol?: string; strike?: number; optionType?: string; ltp?: number; oi?: number; oiChange?: number; delta?: number; gamma?: number; theta?: number; vega?: number; iv?: number }>;
  structure?: Structure | null;
  oiResearch?: { pcr?: number | null; source?: string | null };
  componentFreshness?: Record<string, { status?: string; source?: string; asOf?: string | null }>;
  entryDebit?: number | null;
  entryCredit?: number | null;
  maxProfit?: number | null;
  maxLoss?: number | null;
  breakevens?: number[];
  rewardRisk?: number | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  margin?: number | null;
  paperEntryState?: string;
  paperEntryReason?: string;
  strategyPositionId?: string;
};

type Radar = {
  success: boolean;
  mode?: string;
  sessionDate?: string;
  updatedAt?: string | null;
  executionPolicy?: string;
  cacheStatus?: string;
  sessionStatus?: 'OPEN' | 'CLOSED';
  huntActive?: boolean;
  streamStatus?: { connected?: boolean; subscribed?: number; lastTickAt?: string | null };
  disclaimer?: string;
  candidates: Candidate[];
  sellerCandidates?: Candidate[];
  selected: Candidate[];
  modularCandidates?: Candidate[];
  modularSelected?: Candidate[];
  strategyBook?: {
    positions?: StrategyPosition[];
    open?: StrategyPosition[];
    closed?: StrategyPosition[];
  };
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
  strategyMode?: 'BUY_PREMIUM' | 'SELL_PREMIUM'; strategyType?: string;
  entryPremium?: number; currentPremium?: number; effectiveStopPremium?: number; targetPremium?: number;
  entryCredit?: number; currentDebit?: number; profitTargetDebit?: number; stopDebit?: number; maxLossPerLot?: number;
  unrealizedPnl?: number; pnl?: number; pnlPct?: number; exitReason?: string; enteredAt?: string;
  markSource?: string; markedAt?: string; markStatus?: string; markError?: string | null;
};

type StrategyLeg = {
  side?: 'BUY' | 'SELL'; action?: 'BUY' | 'SELL'; role?: string; symbol?: string;
  strike?: number; optionType?: string; expiry?: string; qty?: number; lotSize?: number;
  entryBid?: number; entryAsk?: number; entryFill?: number; currentBid?: number;
  currentAsk?: number; currentPrice?: number; exitFill?: number;
};

type StrategyPosition = {
  strategyPositionId: string; strategyId: string; family?: string; index?: string;
  status: 'OPEN' | 'CLOSED'; lifecycleState?: string; legs?: StrategyLeg[];
  entryDebit?: number; entryCredit?: number; entryValue?: number; maxLoss?: number;
  maxProfit?: number; breakevens?: number[]; unrealizedPnl?: number; realizedPnl?: number;
  combinedStructureValue?: number; netGreeks?: { delta?: number; gamma?: number; theta?: number; vega?: number };
  markStatus?: string; exitReason?: string; enteredAt?: string; exitedAt?: string;
};

const LEGACY_STRATEGIES = new Set([
  'LONG_CALL', 'LONG_PUT', 'BULL_PUT_CREDIT_SPREAD', 'BEAR_CALL_CREDIT_SPREAD', 'IRON_CONDOR',
]);

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
  futuresRegime: 'Futures regime',
  volatilityEdge: 'IV edge',
  definedRisk: 'Defined risk',
  thetaCarry: 'Theta',
  tailBuffer: 'Tail buffer',
  timeWindow: 'Time window',
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
  if (row.state === 'ELIGIBLE') return row.strategyMode === 'SELL_PREMIUM' ? 'Defined-risk seller gates passed' : 'All gates passed';
  if (row.state === 'WATCH') return row.strategyMode === 'SELL_PREMIUM' ? 'Seller score below 82' : 'Score below 80';
  if (row.reason === 'SELLER_STRUCTURE_UNAVAILABLE') return 'No executable hedged seller structure';
  if (row.reason.startsWith('SELLER_CONSTRUCTION_FAILED:')) {
    const construction = row.gateEvidence?.construction;
    const reason = construction?.reason?.replaceAll('_', ' ').toLowerCase() ?? 'structure unavailable';
    const missing = construction?.missingLegs?.map((leg) => leg.replaceAll('_', ' ').toLowerCase()).join(' + ');
    return `Cannot construct: ${missing || reason}`;
  }
  if (row.reason.startsWith('SELLER_GATE_FAILED:')) {
    return `Blocked: ${row.failedGates.map((key) => GATE_LABEL[key] ?? key).join(' · ')}`;
  }
  if (row.reason.startsWith('SELLER_DATA_INCOMPLETE:')) return 'Waiting for seller evidence';
  if (row.reason.startsWith('HARD_GATE_FAILED:') && row.failedGates.includes('fresh')) {
    return bars === 0 ? 'Quotes not live' : 'Stale quotes';
  }
  if (row.reason.startsWith('HARD_GATE_FAILED:') && row.failedGates.length === 1 && row.failedGates[0] === 'breadth') {
    const breadthReason = row.gateEvidence?.breadth?.reason;
    if (breadthReason === 'BREADTH_OPPOSES_DIRECTION') return `Blocked: constituents oppose ${row.direction ?? 'direction'}`;
    if (breadthReason === 'BREADTH_TOO_NEUTRAL') return 'Blocked: constituent breadth is neutral';
    if (breadthReason === 'PARTIAL_BREADTH_MISSING_STRONG_CONFIRMATION') return 'Blocked: partial breadth lacks strong confirmation';
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

function compactSellerEvidence(row: Candidate) {
  const evidence = row.gateEvidence;
  if (!evidence) return [];
  const construction = evidence.construction;
  if (construction) {
    return [
      { label: 'Chain', value: `${construction.chainContracts ?? 0} contracts · ${construction.uniqueStrikes ?? 0} strikes`, aligned: false },
      { label: 'Usable', value: `${construction.usableContracts ?? 0} with depth + Greeks`, aligned: (construction.usableContracts ?? 0) > 0 },
      { label: 'Range', value: construction.lowestStrike == null ? 'Unavailable' : `${fmtNum(construction.lowestStrike, 0)}—${fmtNum(construction.highestStrike, 0)}`, aligned: construction.lowestStrike != null },
      { label: 'Structure', value: construction.structureStatus?.replaceAll('_', ' ') ?? 'Unavailable', aligned: construction.structureStatus === 'NO_BREAKOUT' || construction.structureStatus === 'CONFIRMED' },
    ];
  }
  const vol = evidence.volatilityEdge;
  const risk = evidence.definedRisk;
  const theta = evidence.thetaCarry;
  const buffer = evidence.tailBuffer;
  return [
    { label: 'IV edge', value: vol?.ivEdgePoints == null ? 'Missing' : `${fmtNum(vol.ivEdgePoints)} pts · IV/VIX ${fmtNum(vol.ivToVix)}×`, aligned: vol?.aligned },
    { label: 'Credit/risk', value: risk?.creditToRisk == null ? 'Missing' : `${fmtNum(risk.creditToRisk)} · max loss ₹${fmtNum(risk.maxLossPerLot, 0)}`, aligned: risk?.aligned },
    { label: 'Theta', value: theta?.netTheta == null ? 'Missing' : `+${fmtNum(theta.netTheta)} · Γ ${fmtNum(theta.netGamma, 5)}`, aligned: theta?.aligned },
    { label: 'Buffer', value: buffer?.minimumBufferAtr == null ? 'Missing' : `${fmtNum(buffer.minimumBufferAtr)} ATR`, aligned: buffer?.aligned },
  ];
}

function compactEvidence(row: Candidate) {
  const evidence = row.gateEvidence;
  if (!evidence) return [];
  const breadth = evidence.breadth;
  const futures = evidence.futuresOi;
  const chain = evidence.optionChain;
  const rr = evidence.riskReward;
  const breadthFloor = breadth?.confirmationMode === 'EARLY_EXCEPTIONAL_EVIDENCE'
    ? breadth.earlyFloor == null ? null : breadth.earlyFloor * 100
    : breadth?.confirmationMode === 'ADAPTIVE_STRONG_EVIDENCE'
      ? breadth.adaptiveFloor == null ? null : breadth.adaptiveFloor * 100
      : breadth?.alignmentFloor == null ? null : breadth.alignmentFloor * 100;
  const breadthThresholdKind = breadth?.confirmationMode === 'EARLY_EXCEPTIONAL_EVIDENCE'
    ? 'early need'
    : breadth?.confirmationMode === 'ADAPTIVE_STRONG_EVIDENCE'
      ? 'adaptive need'
      : 'need';
  const breadthNeed = breadthFloor == null || !row.direction
    ? ''
    : row.direction === 'CALL'
      ? `${breadthThresholdKind} ≥+${breadthFloor.toFixed(0)}%`
      : `${breadthThresholdKind} ≤−${breadthFloor.toFixed(0)}%`;
  const breadthClass = breadth?.classification?.replaceAll('_', ' ') ?? '';
  const breadthMode = breadth?.confirmationMode === 'ADAPTIVE_STRONG_EVIDENCE'
    ? ' · adaptive pass'
    : breadth?.confirmationMode === 'EARLY_EXCEPTIONAL_EVIDENCE'
      ? ' · early 3R pass'
      : '';
  return [
    { label: 'Fut OI', value: futures?.state?.replaceAll('_', ' ') ?? 'Missing', aligned: futures?.aligned },
    { label: 'Breadth', value: breadth?.score == null ? 'Missing' : `${breadthClass ? `${breadthClass} ` : ''}${(breadth.score * 100).toFixed(0)}% · ${breadthNeed} · ${fmtNum(breadth.coveragePct, 0)}% cov${breadthMode}`, aligned: breadth?.aligned },
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
  const modularCandidates = (radar?.modularCandidates ?? []).filter((row) => !LEGACY_STRATEGIES.has(row.strategyId ?? row.strategyType ?? ''));
  const modularSelected = new Set((radar?.modularSelected ?? []).map((row) => `${row.strategyId ?? row.strategyType}-${row.key}`));

  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    let timer: number | undefined;
    const refresh = () => {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true;
      loadRadar('/api/index-options', controller.signal)
        .then((data) => {
          setRadar(data);
          if (data.huntActive !== false && !controller.signal.aborted) {
            timer = window.setTimeout(refresh, 15_000);
          }
        })
        .catch((error) => {
          if (!controller.signal.aborted) setRadar({ success: false, candidates: [], selected: [], error: error instanceof Error ? error.message : 'Radar unavailable' });
        })
        .finally(() => {
          inFlight = false;
          if (!controller.signal.aborted) setLoading(false);
        });
    };
    refresh();
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
      controller.abort();
    };
  }, [refreshToken]);

  return (
    <section className="ix-radar space-y-3" aria-label="Index options radar">
      <div className="desk-card signal-widget signal-widget--radar p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="signal-live-orb" aria-hidden />
              <h2 className="desk-panel-title text-[var(--fg-strong)]">INDEX OPTIONS RADAR</h2>
            </div>
            <p className="mt-1 text-[11px] text-[var(--fg-muted)]">Long premium breakouts · defined-risk credit spreads · range iron condors · portfolio tail controls</p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="desk-pill desk-pill--ok">Auto paper only</span>
            <span className="desk-pill desk-pill--muted">{radar?.huntActive === false ? 'Session closed' : 'Continuous hunt'}</span>
            <span className="desk-pill desk-pill--muted">No minimum</span>
            <span className="desk-pill desk-pill--muted">Max {radar?.limits?.maxDailyEntries ?? 20}/day</span>
            <span className="desk-pill desk-pill--muted">Max {radar?.limits?.maxConcurrent ?? 2} open</span>
            {radar?.cacheStatus === 'STALE' && <span className="desk-pill desk-pill--warn">Cached</span>}
            {radar?.cacheStatus === 'REFRESHING' && <span className="desk-pill desk-pill--muted">Refreshing</span>}
            <span className={radar?.huntActive === false ? 'desk-pill desk-pill--muted' : radar?.streamStatus?.connected ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--warn'}>
              {radar?.huntActive === false ? 'Radar frozen' : `Stream ${radar?.streamStatus?.connected ? 'live' : 'REST fallback'}`}
            </span>
          </div>
        </div>
      </div>

      {modularCandidates.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <div>
              <div className="desk-panel-title">AUTOMATIC MULTI-LEG PAPER STRATEGIES</div>
              <div className="mt-0.5 text-[10px] text-[var(--fg-muted)]">Debit spreads, long volatility and butterflies · conservative atomic fills · no broker orders</div>
            </div>
            <span className="desk-pill desk-pill--ok">{radar?.modularSelected?.length ?? 0} selected</span>
          </div>
          <div className="desk-metric-grid grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {modularCandidates.map((row) => {
              const identity = `${row.strategyId ?? row.strategyType}-${row.key}`;
              const isSelected = modularSelected.has(identity);
              return (
                <article key={identity} className={`desk-metric-tile signal-card signal-card--${row.state.toLowerCase()} flex-col items-stretch justify-start`} style={{ ['--tile-accent' as string]: tileAccent(row.state) }}>
                  <div className="flex w-full items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="desk-metric-label">{(row.strategyId ?? row.strategyType ?? 'STRATEGY').replaceAll('_', ' ')}</div>
                      <div className="text-[10px] uppercase tracking-wider text-[var(--fg-subtle)]">{row.label} · {row.family?.replaceAll('_', ' ')}</div>
                    </div>
                    <span className={isSelected ? 'desk-pill desk-pill--ok' : row.eligible ? 'desk-pill desk-pill--muted' : 'desk-pill desk-pill--warn'}>{isSelected ? 'Selected' : row.state}</span>
                  </div>
                  <div className="mt-2 grid w-full grid-cols-3 gap-2 text-[10px]">
                    <div><div className="uppercase tracking-wider text-[var(--fg-subtle)]">Debit</div><div className="font-bold tabular-nums">₹{fmtNum(row.entryDebit)}</div></div>
                    <div><div className="uppercase tracking-wider text-[var(--fg-subtle)]">Credit</div><div className="font-bold tabular-nums">₹{fmtNum(row.entryCredit)}</div></div>
                    <div><div className="uppercase tracking-wider text-[var(--fg-subtle)]">R:R</div><div className="font-bold tabular-nums">{fmtNum(row.rewardRisk)}</div></div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(row.legs ?? []).map((leg, index) => {
                      const side = leg.side ?? leg.action;
                      return <span key={`${identity}-${leg.symbol ?? index}`} className={side === 'SELL' ? 'desk-pill desk-pill--warn' : 'desk-pill desk-pill--ok'}>{side} {fmtNum(leg.strike, 0)} {leg.optionType === 'CALL' ? 'CE' : 'PE'} @ ₹{fmtNum(leg.entryPrice)}</span>;
                    })}
                  </div>
                  <div className="mt-2 border-t border-[var(--terminal-line)] pt-2 text-[9px] tabular-nums text-[var(--fg-muted)]">Max profit ₹{fmtNum(row.maxProfit, 0)} · Max loss ₹{fmtNum(row.maxLoss, 0)} · Δ {fmtNum(row.delta)} · Θ {fmtNum(row.theta)}</div>
                  {row.paperEntryState && <div className="mt-1 text-[9px] uppercase tracking-wider text-[var(--fg-subtle)]">{row.paperEntryState.replaceAll('_', ' ')}{row.paperEntryReason ? ` · ${row.paperEntryReason.replaceAll('_', ' ')}` : ''}</div>}
                </article>
              );
            })}
          </div>
        </>
      )}

      {radar?.error && (
        <div className="desk-card border border-red-500/40 p-3 text-[12px] text-red-600">{radar.error}</div>
      )}

      <div className="flex items-center justify-between px-1">
        <div className="desk-panel-title">LONG PREMIUM · CONVEX BREAKOUT</div>
        <span className="desk-pill desk-pill--muted">Debit risk capped at premium</span>
      </div>
      <div className="desk-metric-grid grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {(radar?.candidates ?? []).map((row) => {
          const pill = statePill(row.state);
          const chips = gateChips(row);
          const evidence = compactEvidence(row);
          return (
            <article
              key={row.key}
              className={`desk-metric-tile signal-card signal-card--${row.state.toLowerCase()} flex-col items-stretch justify-start`}
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
                  <div className="uppercase tracking-wider text-[var(--fg-subtle)]" title="Weighted setup quality; every hard gate must still pass">Setup</div>
                  <div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">{row.score == null ? 'Pending' : row.score.toFixed(1)}</div>
                </div>
                <div>
                  <div className="uppercase tracking-wider text-[var(--fg-subtle)]">5m</div>
                  <div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">{row.structure?.barCount ?? '—'}</div>
                </div>
              </div>
              <div className="mt-2 text-[11px] leading-snug text-[var(--fg-muted)]">{candidateHeadline(row)}</div>
              {Object.keys(row.componentFreshness ?? {}).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {Object.entries(row.componentFreshness ?? {}).map(([key, item]) => (
                    <span key={key} className={item.status === 'LIVE' ? 'desk-pill desk-pill--ok' : 'desk-pill desk-pill--muted'}>
                      {key === 'spotQuote' ? 'Quote' : key === 'optionChain' ? 'Chain' : key === 'futuresOi' ? 'Fut OI' : key === 'candles5m' ? '5m' : 'Greeks'} {item.status?.toLowerCase()}
                    </span>
                  ))}
                </div>
              )}
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
              {row.oiResearch?.source && (
                <div className="mt-2 flex items-center gap-1 text-[9px] text-[var(--fg-muted)]">
                  <span className="desk-pill desk-pill--muted">SIGQ OI</span>
                  <span>PCR {fmtNum(row.oiResearch.pcr)}</span>
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

      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div>
          <div className="desk-panel-title">DEFINED-RISK PREMIUM SELLING</div>
          <div className="mt-0.5 text-[10px] text-[var(--fg-muted)]">Credit spreads and iron condors only · hedge wing mandatory · no naked shorts</div>
        </div>
        <span className="desk-pill desk-pill--ok">Institutional seller sleeve</span>
      </div>
      <div className="desk-metric-grid grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {(radar?.sellerCandidates ?? []).map((row) => {
          const pill = statePill(row.state);
          const chips = gateChips(row);
          const evidence = compactSellerEvidence(row);
          return (
            <article
              key={`seller-${row.key}`}
              className={`desk-metric-tile signal-card signal-card--${row.state.toLowerCase()} flex-col items-stretch justify-start`}
              style={{ ['--tile-accent' as string]: tileAccent(row.state) }}
            >
              <div className="flex w-full items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="desk-metric-label">{row.label}</div>
                  <div className="text-[10px] uppercase tracking-wider text-[var(--fg-subtle)]">{row.strategyType?.replaceAll('_', ' ') ?? 'SELLER SCAN'}</div>
                </div>
                <span className={pill.className}>{pill.label}</span>
              </div>
              <div className="desk-metric-value desk-num mt-2 w-full">{fmtSpot(row.spot)}</div>
              <div className="mt-2 grid w-full grid-cols-3 gap-2 text-[10px]">
                <div><div className="uppercase tracking-wider text-[var(--fg-subtle)]">Bias</div><div className="mt-0.5 font-bold text-[var(--fg-strong)]">{row.bias ?? '—'}</div></div>
                <div><div className="uppercase tracking-wider text-[var(--fg-subtle)]">Seller score</div><div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">{row.score == null ? 'Pending' : row.score.toFixed(1)}</div></div>
                <div><div className="uppercase tracking-wider text-[var(--fg-subtle)]">Credit</div><div className="mt-0.5 font-bold tabular-nums text-[var(--fg-strong)]">₹{fmtNum(row.risk?.entryCredit)}</div></div>
              </div>
              <div className="mt-2 text-[11px] leading-snug text-[var(--fg-muted)]">{candidateHeadline(row)}</div>
              {chips.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{chips.map((chip) => <span key={chip} className="desk-pill desk-pill--muted">{chip}</span>)}</div>}
              {evidence.length > 0 && (
                <div className="mt-2 grid w-full grid-cols-2 gap-1 border-t border-[var(--terminal-line)] pt-2 text-[9px]">
                  {evidence.map((item) => (
                    <div key={item.label} className="min-w-0">
                      <span className="uppercase tracking-wider text-[var(--fg-subtle)]">{item.label} </span>
                      <span className={item.aligned === true ? 'text-emerald-600' : item.aligned === false ? 'text-red-500' : 'text-[var(--fg-muted)]'}>{item.value}</span>
                    </div>
                  ))}
                </div>
              )}
              {(row.legs?.length ?? 0) > 0 && (
                <div className="mt-2 border-t border-[var(--terminal-line)] pt-2 text-[9px]">
                  <div className="flex flex-wrap gap-1">
                    {row.legs?.map((leg) => (
                      <span key={`${leg.action}-${leg.symbol}`} className={leg.action === 'SELL' ? 'desk-pill desk-pill--warn' : 'desk-pill desk-pill--ok'}>
                        {leg.action} {fmtNum(leg.strike, 0)} {leg.optionType === 'CALL' ? 'CE' : 'PE'} @ ₹{fmtNum(leg.entryPrice)}
                      </span>
                    ))}
                  </div>
                  <div className="mt-1 tabular-nums text-[var(--fg-muted)]">
                    Max profit ₹{fmtNum(row.risk?.maxProfitPerLot, 0)} · Max loss ₹{fmtNum(row.risk?.maxLossPerLot, 0)} · C/R {fmtNum(row.risk?.creditToRisk)}
                  </div>
                  <div className="mt-0.5 tabular-nums text-[var(--fg-subtle)]">B/E {fmtNum(row.risk?.lowerBreakEven)} — {fmtNum(row.risk?.upperBreakEven)}</div>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {radar?.paperBook && (
        <div className="desk-card signal-widget signal-widget--book p-3 sm:p-4">
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
                <tr><th className="pb-2">Contract / structure</th><th>Index</th><th>Qty</th><th>Entry</th><th>Mark</th><th>Risk exit</th><th>Profit exit</th><th>P&amp;L</th><th>Status</th></tr>
              </thead>
              <tbody>
                {[...(radar.paperBook.open ?? []), ...(radar.paperBook.closed ?? []).slice().reverse()].map((position) => {
                  const pnl = position.status === 'OPEN' ? position.unrealizedPnl : position.pnl;
                  const seller = position.strategyMode === 'SELL_PREMIUM';
                  return (
                    <tr key={position.id} className="border-t border-[var(--terminal-line)] tabular-nums">
                      <td className="py-2 font-bold text-[var(--fg-strong)]">{seller ? position.strategyType?.replaceAll('_', ' ') : position.symbol}</td><td>{position.index}</td><td>{position.quantity}</td>
                      <td>{seller ? `₹${fmtNum(position.entryCredit)} credit` : `₹${fmtNum(position.entryPremium)}`}</td>
                      <td>{seller ? `₹${fmtNum(position.currentDebit)} debit` : `₹${fmtNum(position.currentPremium)}`}</td>
                      <td>₹{fmtNum(seller ? position.stopDebit : position.effectiveStopPremium)}</td>
                      <td>₹{fmtNum(seller ? position.profitTargetDebit : position.targetPremium)}</td>
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

      {radar?.strategyBook && (
        <div className="desk-card signal-widget signal-widget--book p-3 sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><div className="desk-panel-title">MULTI-LEG PAPER BOOK</div><div className="mt-1 text-[10px] text-[var(--fg-muted)]">Durable strategy positions · leg-level marks · lifecycle exits</div></div>
            <div className="flex gap-1.5"><span className="desk-pill desk-pill--ok">{radar.strategyBook.open?.length ?? 0} open</span><span className="desk-pill desk-pill--muted">{radar.strategyBook.closed?.length ?? 0} closed</span></div>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-[10px]">
              <thead className="uppercase tracking-wider text-[var(--fg-subtle)]"><tr><th className="pb-2">Strategy</th><th>Index</th><th>Legs</th><th>Entry</th><th>Structure mark</th><th>Max loss</th><th>Greeks Δ / Γ / Θ / V</th><th>P&amp;L</th><th>Status</th></tr></thead>
              <tbody>
                {[...(radar.strategyBook.open ?? []), ...(radar.strategyBook.closed ?? []).slice().reverse()].map((position) => {
                  const pnl = position.status === 'OPEN' ? position.unrealizedPnl : position.realizedPnl;
                  return (
                    <tr key={position.strategyPositionId} className="border-t border-[var(--terminal-line)] align-top tabular-nums">
                      <td className="py-2 font-bold text-[var(--fg-strong)]">{position.strategyId.replaceAll('_', ' ')}</td><td>{position.index}</td>
                      <td><div className="flex max-w-[320px] flex-wrap gap-1">{(position.legs ?? []).map((leg, index) => <span key={`${position.strategyPositionId}-${leg.symbol ?? index}`} className={(leg.side ?? leg.action) === 'SELL' ? 'desk-pill desk-pill--warn' : 'desk-pill desk-pill--ok'}>{leg.side ?? leg.action} {fmtNum(leg.strike, 0)} {leg.optionType === 'CALL' ? 'CE' : 'PE'} @ ₹{fmtNum(leg.entryFill)} → ₹{fmtNum(leg.exitFill ?? leg.currentPrice)}</span>)}</div></td>
                      <td>{position.entryDebit ? `₹${fmtNum(position.entryDebit)} debit` : `₹${fmtNum(position.entryCredit)} credit`}</td><td>₹{fmtNum(position.combinedStructureValue)}</td><td>₹{fmtNum(position.maxLoss, 0)}</td>
                      <td>{fmtNum(position.netGreeks?.delta)} / {fmtNum(position.netGreeks?.gamma, 4)} / {fmtNum(position.netGreeks?.theta)} / {fmtNum(position.netGreeks?.vega)}</td>
                      <td className={(pnl ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-500'}>₹{fmtNum(pnl)}</td><td><div>{position.status === 'CLOSED' ? position.exitReason ?? 'CLOSED' : position.lifecycleState ?? 'OPEN'}</div><div className="text-[8px] text-[var(--fg-subtle)]">{position.markStatus}</div></td>
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
        <span className="text-[var(--fg-muted)]">Seller: hedge wing mandatory · 50% credit target · 35% max-loss budget · 15:20 exit</span>
        <span className="tabular-nums text-[var(--fg-muted)]">
          Re-entry {radar?.reentryPolicy?.maxAttemptsPerIndex ?? 2}× · {radar?.reentryPolicy?.targetCooldownMin ?? 20}m / {radar?.reentryPolicy?.profitTrailCooldownMin ?? 30}m / {radar?.reentryPolicy?.sameDirectionStopCooldownMin ?? 45}m · {(radar?.reentryPolicy?.riskScale ?? 0.5) * 100}% risk
        </span>
      </div>
    </section>
  );
}
