/**
 * INDEX OPTIONS · QUANT V2 view model.
 *
 * Pure payload → display mapping for the Index Options desk. No React, no
 * fetching: every field the panel renders is derived here so the fallback
 * priority (live session vs historical session) is explicit and testable.
 *
 * Binding priority (canonical first, never mask durable data with a zero):
 *   Decision   ← quantDecision.decision → marketDecision → durable ledger → session state
 *   Candidates ← modularCandidates.length → quantDecision.ranked.length → candidates.length
 *   Selected   ← live: quantDecision.selected.length → modularSelected.length
 *                historical: historicalExecution.entryCount → strategyBook.positions.length
 *   Open       ← strategyBook.open.length → historicalExecution.openCount → paperBook.openCount
 *   Closed     ← strategyBook.closed.length → historicalExecution.closedCount → paperBook.closedCount
 *   Net Greeks ← open-position netGreeks aggregate → quantDecision.portfolioRisk.greeks
 */

export type Leg = {
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
  exitFill?: number;
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  markedAt?: string;
};

export type Position = {
  strategyPositionId: string;
  strategyId: string;
  index?: string;
  status?: string;
  expiry?: string;
  enteredAt?: string;
  updatedAt?: string;
  exitedAt?: string;
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
  exitReason?: string;
  breakevens?: number[];
  exitGreeks?: Record<string, number>;
  netGreeks?: Record<string, number>;
  entryGreeks?: Record<string, number>;
  legs?: Leg[];
};

export type Decision = {
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

export type CandidateHistoryRow = {
  timestamp?: string;
  index?: string;
  strategyId?: string;
  status?: string;
  rank?: number;
  utility?: number;
  riskGatePassed?: boolean;
  selected?: boolean;
  executed?: boolean;
  reasons?: string[];
  gates?: Record<string, boolean>;
  marketEvidence?: Record<string, unknown>;
};
export type Radar = {
  success?: boolean;
  updatedAt?: string;
  sessionDate?: string;
  sessionStatus?: string;
  huntActive?: boolean;
  selectionAuthority?: string;
  executionPolicy?: string;
  marketDecision?: string;
  limits?: Record<string, unknown> & { huntMode?: string; selectionAuthority?: string };
  streamStatus?: { connected?: boolean; subscribed?: number; wanted?: number; lastTickAt?: string };
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
  modularCandidates?: Array<Record<string, unknown>>;
  modularSelected?: Array<Record<string, unknown>>;
  candidates?: Array<Record<string, unknown>>;
  sellerCandidates?: Array<Record<string, unknown>>;
  strategyBook?: {
    authority?: string;
    sessionDate?: string;
    positions?: Position[];
    open?: Position[];
    closed?: Position[];
  };
  paperBook?: {
    entryCount?: number;
    openCount?: number;
    closedCount?: number;
    realizedPnl?: number;
    openPnl?: number;
    totalPnl?: number;
  };
  historicalExecution?: {
    authority?: string;
    source?: string;
    entryCount?: number;
    openCount?: number;
    closedCount?: number;
  };
  replayDiagnostics?: {
    mode?: string;
    limitations?: string[];
    indices?: unknown[];
    implemented?: unknown[];
    buySideContracts?: unknown[];
  };
  qualificationHistoryAvailable?: boolean;
  qualificationLimitations?: string[];
  historicalQualification?: {
    evaluatedCount?: number;
    eligibleCount?: number;
    qualifiedCount?: number;
    selectedCount?: number;
    executedCount?: number;
    rejectedCount?: number;
    entryBlockedCount?: number;
    rejectionSummary?: Record<string, number>;
  };
  candidateHistory?: CandidateHistoryRow[];
  error?: string;
};
export type MetricId =
  | 'decision'
  | 'candidates'
  | 'selected'
  | 'executed'
  | 'closed'
  | 'open'
  | 'delta'
  | 'gamma'
  | 'theta'
  | 'vega'
  | 'qualification'
  | 'replay';

export type MetricTone = 'ok' | 'warn' | 'danger' | 'muted';

export type Metric = {
  id: MetricId;
  label: string;
  value: string;
  raw: number | string | null;
  source: string;
  hint?: string;
  tone?: MetricTone;
  /** null == payload genuinely has no such field (render "—"), 0 == a real zero */
  nullable: boolean;
};

export type GreekSemantics = 'OPEN_EXPOSURE' | 'CURRENT_EXPOSURE' | 'FLAT' | 'UNAVAILABLE';

export type IndexOptionsView = {
  isHistorical: boolean;
  isClosed: boolean;
  decision: string | null;
  candidates: number | null;
  selected: number | null;
  executed: number | null;
  open: number | null;
  closed: number | null;
  qualificationAvailable: boolean;
  replayCandidateCount: number | null;
  metrics: Metric[];
  greeks: Record<string, number | null>;
  greekSemantics: GreekSemantics;
  openPositions: Position[];
  closedPositions: Position[];
  listMode: 'OPEN' | 'CLOSED' | 'MIXED' | 'EMPTY';
  hasTradeData: boolean;
  bookAuthority: string;
  bookSource: string;
  /** dev-only provenance map: metric id → payload path that produced the value */
  provenance: Record<string, string>;
};
/* -------------------------------------------------------------------------- */
/*  Formatting helpers (shared with the panel so both stay identical)          */
/* -------------------------------------------------------------------------- */

export const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/** `null`/`undefined`/NaN → "—". Never coerces a missing value into a zero. */
export const fmtNum = (value?: number | null, digits = 2): string =>
  isNumber(value) ? value.toLocaleString('en-IN', { maximumFractionDigits: digits }) : '—';

export const fmtMoney = (value?: number | null): string =>
  isNumber(value) ? `₹${fmtNum(value, 0)}` : '—';

export const fmtLabel = (value?: string | null): string => {
  const text = typeof value === 'string' ? value.trim() : '';
  return text ? text.replaceAll('_', ' ') : '—';
};

const fmtCount = (value: number | null): string => (value == null ? '—' : value.toLocaleString('en-IN'));

const fmtGreek = (value: number | null, digits: number): string =>
  value == null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: digits });

/** Non-empty string accessor — treats '' / whitespace as absent. */
const text = (value?: unknown): string | null => {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
};

const count = (value?: unknown): number | null => (Array.isArray(value) ? value.length : null);

const firstCount = (...candidates: Array<number | null>): number | null =>
  candidates.find((value) => value != null) ?? null;

const greekKeys = ['delta', 'gamma', 'theta', 'vega'] as const;
/* -------------------------------------------------------------------------- */
/*  Aggregate greeks from the durable strategy book                            */
/* -------------------------------------------------------------------------- */

export function aggregateOpenGreeks(openPositions: Position[]): Record<string, number> | null {
  const totals: Record<string, number> = {};
  let found = false;
  for (const position of openPositions) {
    const source = position.netGreeks ?? position.exitGreeks ?? position.entryGreeks;
    if (!source) continue;
    for (const key of greekKeys) {
      const value = source[key];
      if (!isNumber(value)) continue;
      totals[key] = (totals[key] ?? 0) + value;
      found = true;
    }
  }
  return found ? totals : null;
}

const num = (value?: unknown): number | null => (isNumber(value) ? value : null);

/** True when every supplied greek is a real zero (flat exposure, not missing data). */
const isFlatGreeks = (greeks?: Record<string, number> | null): boolean =>
  Boolean(greeks) && greekKeys.every((key) => num(greeks?.[key]) === 0);
/* -------------------------------------------------------------------------- */
/*  Main builder                                                               */
/* -------------------------------------------------------------------------- */

export function buildIndexOptionsView(
  radar: Radar | null,
  { sessionDate = '', loading = false }: { sessionDate?: string; loading?: boolean } = {},
): IndexOptionsView {
  const isHistorical = Boolean(sessionDate);
  const isClosed = radar?.sessionStatus === 'CLOSED';
  const q = radar?.quantDecision;
  const book = radar?.strategyBook;
  const historical = radar?.historicalExecution;
  const paper = radar?.paperBook;

  const openPositions = Array.isArray(book?.open) ? book.open : [];
  const closedPositions = Array.isArray(book?.closed) ? book.closed : [];
  const bookPositions = Array.isArray(book?.positions) ? book.positions : [];

  const provenance: Record<string, string> = {};

  /* ── Decision ─────────────────────────────────────────────────────────── */
  let decision = text(q?.decision);
  if (decision) provenance.decision = 'quantDecision.decision';
  if (!decision) {
    decision = text(radar?.marketDecision);
    if (decision) provenance.decision = 'marketDecision';
  }
  if (!decision && isHistorical && (bookPositions.length || (historical?.entryCount ?? 0) > 0)) {
    decision = 'DURABLE_LEDGER';
    provenance.decision = 'historicalExecution.entryCount';
  }
  if (!decision && isClosed) {
    decision = 'SESSION_CLOSED';
    provenance.decision = 'sessionStatus';
  }
  if (!decision && loading) {
    decision = 'CALCULATING';
    provenance.decision = 'loading';
  }

  /* ── Candidates: canonical backend count, never a live-only key ───────── */
  const candidates = firstCount(
    count(radar?.modularCandidates),
    count(q?.ranked),
    count(radar?.candidates),
  );
  provenance.candidates =
    count(radar?.modularCandidates) != null
      ? 'modularCandidates.length'
      : count(q?.ranked) != null
        ? 'quantDecision.ranked.length'
        : count(radar?.candidates) != null
          ? 'candidates.length'
          : 'unavailable';

  /* ── Selected / Executed ──────────────────────────────────────────────── */
  let selected: number | null;
  let executed: number | null = null;
  if (isHistorical) {
    executed = firstCount(
      num(historical?.entryCount),
      bookPositions.length ? bookPositions.length : null,
      num(paper?.entryCount),
    );
    selected = firstCount(num(historical?.entryCount), bookPositions.length ? bookPositions.length : null);
    provenance.executed =
      num(historical?.entryCount) != null
        ? 'historicalExecution.entryCount'
        : bookPositions.length
          ? 'strategyBook.positions.length'
          : num(paper?.entryCount) != null
            ? 'paperBook.entryCount'
            : 'unavailable';
    provenance.selected = provenance.executed;
  } else {
    const selectedFromPayload = firstCount(count(q?.selected), count(radar?.modularSelected));
    // A live payload can momentarily report an empty selection list after the
    // opening cycle already filled the durable book. When that happens the open
    // positions are the real evidence that a selection occurred, so never let an
    // empty live array collapse a durable open position back to zero.
    if ((selectedFromPayload == null || selectedFromPayload === 0) && openPositions.length > 0) {
      selected = openPositions.length;
      provenance.selected = 'strategyBook.open.length (live selection list empty)';
    } else if (selectedFromPayload != null) {
      selected = selectedFromPayload;
      provenance.selected =
        count(q?.selected) != null ? 'quantDecision.selected.length' : 'modularSelected.length';
    } else {
      selected = null;
      provenance.selected = 'unavailable';
    }
  }

  /* ── Open / Closed: durable strategy book wins over derived caches ────── */
  const open = firstCount(
    Array.isArray(book?.open) ? openPositions.length : null,
    num(historical?.openCount),
    num(paper?.openCount),
  );
  const closed = firstCount(
    Array.isArray(book?.closed) ? closedPositions.length : null,
    num(historical?.closedCount),
    num(paper?.closedCount),
  );
  provenance.open = Array.isArray(book?.open)
    ? 'strategyBook.open.length'
    : num(historical?.openCount) != null
      ? 'historicalExecution.openCount'
      : num(paper?.openCount) != null
        ? 'paperBook.openCount'
        : 'unavailable';
  provenance.closed = Array.isArray(book?.closed)
    ? 'strategyBook.closed.length'
    : num(historical?.closedCount) != null
      ? 'historicalExecution.closedCount'
      : num(paper?.closedCount) != null
        ? 'paperBook.closedCount'
        : 'unavailable';
/* ── Greeks: open book exposure first, then live risk governor ────────── */
  const openAggregate = aggregateOpenGreeks(openPositions);
  const riskGreeks = q?.portfolioRisk?.greeks ?? null;
  let greeks: Record<string, number | null>;
  let greekSemantics: GreekSemantics;
  let greekSource: string;

  if (openAggregate) {
    greeks = {
      delta: num(openAggregate.delta),
      gamma: num(openAggregate.gamma),
      theta: num(openAggregate.theta),
      vega: num(openAggregate.vega),
    };
    greekSemantics = 'OPEN_EXPOSURE';
    greekSource = 'strategyBook.open[].netGreeks';
  } else if (riskGreeks && !isFlatGreeks(riskGreeks)) {
    greeks = {
      delta: num(riskGreeks.delta),
      gamma: num(riskGreeks.gamma),
      theta: num(riskGreeks.theta),
      vega: num(riskGreeks.vega),
    };
    greekSemantics = 'CURRENT_EXPOSURE';
    greekSource = 'quantDecision.portfolioRisk.greeks';
  } else if (riskGreeks) {
    greeks = { delta: 0, gamma: 0, theta: 0, vega: 0 };
    greekSemantics = 'CURRENT_EXPOSURE';
    greekSource = 'quantDecision.portfolioRisk.greeks';
  } else {
    greeks = { delta: null, gamma: null, theta: null, vega: null };
    greekSemantics = 'UNAVAILABLE';
    greekSource = 'unavailable';
  }
  if (greekSemantics === 'UNAVAILABLE' && isHistorical && closedPositions.length) {
    const exitAggregate = aggregateOpenGreeks(closedPositions);
    if (exitAggregate) {
      greeks = { delta: 0, gamma: 0, theta: 0, vega: 0 };
      greekSemantics = 'CURRENT_EXPOSURE';
      greekSource = 'no live exposure · strategyBook.closed[].netGreeks';
    }
  }
  provenance.delta = provenance.gamma = provenance.theta = provenance.vega = greekSource;

  const greekHint =
    greekSemantics === 'OPEN_EXPOSURE'
      ? `open book exposure · ${openPositions.length} open`
      : greekSemantics === 'CURRENT_EXPOSURE'
        ? closedPositions.length
          ? `current exposure 0 · ${closedPositions.length} closed`
          : 'current exposure'
        : 'exposure unavailable';
/* ── Qualification / replay provenance ───────────────────────────────── */
  const qualificationAvailable = radar?.qualificationHistoryAvailable === true;
  const replayCandidateCount = firstCount(
    count(radar?.replayDiagnostics?.implemented),
    count(radar?.modularSelected),
  );
  provenance.qualification = qualificationAvailable
    ? 'historicalQualification'
    : 'qualificationHistoryAvailable=false';
  provenance.replay =
    count(radar?.replayDiagnostics?.implemented) != null
      ? 'replayDiagnostics.implemented.length'
      : 'unavailable';

  const historicalQualified = num(radar?.historicalQualification?.qualifiedCount);
  const historicalEvaluated = num(radar?.historicalQualification?.evaluatedCount);

  /* ── Metric row (same 8-tile grid in both modes) ─────────────────────── */
  const metrics: Metric[] = [];
  metrics.push({
    id: 'decision',
    label: 'Decision',
    value: decision ? fmtLabel(decision) : '—',
    raw: decision,
    source: provenance.decision,
    tone: decision === 'ADMIT' ? 'ok' : decision === 'NO_TRADE' ? 'warn' : 'muted',
    nullable: false,
  });

  if (isHistorical) {
    metrics.push({
      id: 'executed',
      label: 'Executed',
      value: fmtCount(executed),
      raw: executed,
      source: provenance.executed,
      hint: executed == null ? 'durable ledger unavailable' : 'durable Quant V2 ledger',
      nullable: executed == null,
    });
    metrics.push({
      id: 'closed',
      label: 'Closed',
      value: fmtCount(closed),
      raw: closed,
      source: provenance.closed,
      nullable: closed == null,
    });
    metrics.push({
      id: 'open',
      label: 'Open',
      value: fmtCount(open),
      raw: open,
      source: provenance.open,
      nullable: open == null,
    });
    metrics.push({
      id: 'qualification',
      label: 'Qualification History',
      value: qualificationAvailable
        ? historicalQualified == null
          ? 'Archived'
          : `${fmtCount(historicalQualified)} qualified`
        : 'Not Archived',
      raw: qualificationAvailable ? historicalQualified : null,
      source: provenance.qualification,
      hint: qualificationAvailable
        ? `evaluated ${fmtCount(historicalEvaluated)}`
        : 'decision audit not archived for this session',
      tone: qualificationAvailable ? 'ok' : 'warn',
      nullable: false,
    });
    metrics.push({
      id: 'replay',
      label: 'Replay Diagnostics',
      value: replayCandidateCount == null ? 'Not Archived' : `${fmtCount(replayCandidateCount)} repriced`,
      raw: replayCandidateCount,
      source: provenance.replay,
      hint: 'analytical only · never overrides durable executions',
      tone: 'muted',
      nullable: false,
    });
  } else {
    metrics.push({
      id: 'candidates',
      label: 'Candidates',
      value: fmtCount(candidates),
      raw: candidates,
      source: provenance.candidates,
      nullable: candidates == null,
    });
    metrics.push({
      id: 'selected',
      label: 'Selected',
      value: fmtCount(selected),
      raw: selected,
      source: provenance.selected,
      nullable: selected == null,
    });
    metrics.push({
      id: 'open',
      label: 'Open',
      value: fmtCount(open),
      raw: open,
      source: provenance.open,
      nullable: open == null,
    });
  }
const greekTiles: Array<{ id: MetricId; label: string; key: (typeof greekKeys)[number]; digits: number }> = [
    { id: 'delta', label: 'Net Δ', key: 'delta', digits: 3 },
    { id: 'gamma', label: 'Net Γ', key: 'gamma', digits: 5 },
    { id: 'theta', label: 'Net Θ', key: 'theta', digits: 2 },
    { id: 'vega', label: 'Net Vega', key: 'vega', digits: 2 },
  ];
  for (const tile of greekTiles) {
    const value = greeks[tile.key] ?? null;
    metrics.push({
      id: tile.id,
      label: tile.label,
      value: fmtGreek(value, tile.digits),
      raw: value,
      source: greekSource,
      hint: greekHint,
      nullable: value == null,
    });
  }

  const listMode: IndexOptionsView['listMode'] =
    openPositions.length && closedPositions.length
      ? 'MIXED'
      : openPositions.length
        ? 'OPEN'
        : closedPositions.length
          ? 'CLOSED'
          : 'EMPTY';

  return {
    isHistorical,
    isClosed,
    decision,
    candidates,
    selected,
    executed,
    open,
    closed,
    qualificationAvailable,
    replayCandidateCount,
    metrics,
    greeks,
    greekSemantics,
    openPositions,
    closedPositions,
    listMode,
    hasTradeData: openPositions.length + closedPositions.length > 0,
    bookAuthority: text(book?.authority) ?? text(historical?.authority) ?? 'INDEX_OPTIONS_QUANT_V2',
    bookSource: text(historical?.source) ?? 'shared_state.db',
    provenance,
  };
}
