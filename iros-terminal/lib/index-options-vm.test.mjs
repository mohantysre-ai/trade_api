import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { buildIndexOptionsView, aggregateOpenGreeks } from './index-options-vm.ts';

const here = dirname(fileURLToPath(import.meta.url));
const panelSource = readFileSync(join(here, '..', 'app', 'components', 'QuantIndexOptionsPanel.tsx'), 'utf8');

const metric = (view, id) => view.metrics.find((m) => m.id === id);

/* -------------------------------------------------------------------------- */
/*  Case A — live no-trade                                                    */
/* -------------------------------------------------------------------------- */

const liveNoTrade = {
  success: true,
  sessionStatus: 'OPEN',
  streamStatus: { connected: true },
  modularCandidates: [],
  modularSelected: [],
  quantDecision: {
    engine: 'INDEX_OPTIONS_QUANT_V2',
    model: 'COMMON_SCENARIO_DISTRIBUTION_REPRICER',
    decision: 'NO_TRADE',
    noTradeUtility: 0,
    ranked: [],
    selected: [],
    portfolioRisk: { pass: true, stressLoss: 0, greeks: { delta: 0, gamma: 0, theta: 0, vega: 0 } },
  },
  strategyBook: { authority: 'INDEX_OPTIONS_QUANT_V2', positions: [], open: [], closed: [] },
};

test('Case A live no-trade: decision NO_TRADE, open 0, empty state valid', () => {
  const view = buildIndexOptionsView(liveNoTrade, { sessionDate: '', loading: false });
  assert.equal(view.isHistorical, false);
  assert.equal(view.decision, 'NO_TRADE');
  assert.equal(view.open, 0);
  assert.equal(view.hasTradeData, false);
  assert.equal(view.listMode, 'EMPTY');
  assert.equal(metric(view, 'decision').value, 'NO TRADE');
  assert.equal(metric(view, 'open').value, '0');
  assert.equal(metric(view, 'candidates').value, '0');
  assert.equal(metric(view, 'selected').value, '0');
});

/* -------------------------------------------------------------------------- */
/*  Case B — historical session, one executed closed trade                    */
/* -------------------------------------------------------------------------- */

const closedTrade = {
  strategyPositionId: 'sp-1',
  strategyId: 'LONG_STRADDLE',
  index: 'NIFTY',
  status: 'CLOSED',
  expiry: '2026-09-24',
  enteredAt: '2026-09-15T09:20:00+05:30',
  exitedAt: '2026-09-15T15:25:00+05:30',
  entryValue: 25000,
  entryDebit: 25000,
  realizedPnl: 1250,
  unrealizedPnl: 0,
  maxLoss: 25000,
  maxProfit: 180000,
  exitReason: 'TARGET',
  exitGreeks: { delta: 0, gamma: 0, theta: 0, vega: 0 },
  legs: [
    { side: 'BUY', symbol: 'NIFTY2480022000CE', strike: 22000, optionType: 'CE', qty: 1, lotSize: 75, entryPrice: 160, exitFill: 176 },
    { side: 'BUY', symbol: 'NIFTY2480022000PE', strike: 22000, optionType: 'PE', qty: 1, lotSize: 75, entryPrice: 160, exitFill: 180 },
  ],
};

const historicalOneTrade = {
  success: true,
  sessionStatus: 'CLOSED',
  sessionDate: '2026-09-15',
  strategyBook: {
    authority: 'INDEX_OPTIONS_QUANT_V2',
    sessionDate: '2026-09-15',
    positions: [closedTrade],
    open: [],
    closed: [closedTrade],
  },
  historicalExecution: {
    authority: 'INDEX_OPTIONS_QUANT_V2_DURABLE_LEDGER',
    source: 'shared_state.db',
    entryCount: 1,
    openCount: 0,
    closedCount: 1,
  },
  // Replay found no qualified candidate — must NOT collapse the durable trade.
  modularCandidates: [],
  modularSelected: [],
  replayDiagnostics: { mode: 'SESSION_REPLAY', limitations: ['LIVE_ELIGIBILITY_GATES_NOT_ARCHIVED'], implemented: [] },
  qualificationHistoryAvailable: false,
  qualificationLimitations: ['LIVE_ELIGIBILITY_GATES_NOT_ARCHIVED'],
};

test('Case B historical 1 durable trade: executed 1, closed 1, open 0 — never misleading zeros', () => {
  const view = buildIndexOptionsView(historicalOneTrade, { sessionDate: '2026-09-15' });
  assert.equal(view.isHistorical, true);
  assert.equal(view.executed, 1);
  assert.equal(view.selected, 1);
  assert.equal(view.open, 0);
  assert.equal(view.closed, 1);
  assert.equal(metric(view, 'executed').value, '1');
  assert.equal(metric(view, 'closed').value, '1');
  assert.equal(metric(view, 'open').value, '0');
  assert.equal(view.hasTradeData, true);
  assert.equal(view.listMode, 'CLOSED');
});

test('Case B: durable trade renders as a closed-position row (not the empty state)', () => {
  const view = buildIndexOptionsView(historicalOneTrade, { sessionDate: '2026-09-15' });
  assert.equal(view.closedPositions.length, 1);
  const trade = view.closedPositions[0];
  assert.equal(trade.strategyId, 'LONG_STRADDLE');
  assert.equal(trade.index, 'NIFTY');
  assert.equal(trade.legs.length, 2);
  assert.equal(trade.realizedPnl, 1250);
  assert.equal(trade.status, 'CLOSED');
});

test('Case B: replay candidate count 0 does not override durable execution count', () => {
  const withReplay = { ...historicalOneTrade, modularSelected: [], replayDiagnostics: { mode: 'SESSION_REPLAY', limitations: ['X'], implemented: [] } };
  const view = buildIndexOptionsView(withReplay, { sessionDate: '2026-09-15' });
  assert.equal(metric(view, 'executed').value, '1');
  assert.notEqual(metric(view, 'executed').value, '0');
});

test('Case B: qualification unavailable shows "Not Archived" semantics, not a zero', () => {
  const view = buildIndexOptionsView(historicalOneTrade, { sessionDate: '2026-09-15' });
  assert.equal(view.qualificationAvailable, false);
  const qual = metric(view, 'qualification');
  assert.equal(qual.value, 'Not Archived');
  assert.equal(qual.tone, 'warn');
  assert.equal(qual.nullable, false);
});

test('Case B: qualification available renders archived funnel counts', () => {
  const payload = {
    ...historicalOneTrade,
    qualificationHistoryAvailable: true,
    historicalQualification: { evaluatedCount: 12, eligibleCount: 6, qualifiedCount: 2, selectedCount: 1, executedCount: 1, rejectedCount: 9, entryBlockedCount: 0 },
  };
  const view = buildIndexOptionsView(payload, { sessionDate: '2026-09-15' });
  assert.equal(view.qualificationAvailable, true);
  assert.equal(metric(view, 'qualification').value, '2 qualified');
});

/* -------------------------------------------------------------------------- */
/*  Case C — live/current session with an open Quant position                 */
/* -------------------------------------------------------------------------- */

const openTrade = {
  strategyPositionId: 'sp-open',
  strategyId: 'IRON_CONDOR',
  index: 'BANKNIFTY',
  status: 'OPEN',
  markStatus: 'LIVE',
  expiry: '2026-09-24',
  enteredAt: '2026-09-15T09:25:00+05:30',
  updatedAt: '2026-09-15T11:05:00+05:30',
  entryValue: 31000,
  entryDebit: 31000,
  unrealizedPnl: 820,
  maxLoss: 31000,
  maxProfit: 62000,
  netGreeks: { delta: -1.5, gamma: 0.00042, theta: 18.4, vega: -22.7 },
  legs: [
    { side: 'SELL', symbol: 'BANKNIFTY2450048000CE', strike: 48000, optionType: 'CE', qty: 1, lotSize: 15, entryPrice: 210, currentPrice: 180 },
    { side: 'SELL', symbol: 'BANKNIFTY2450048000PE', strike: 48000, optionType: 'PE', qty: 1, lotSize: 15, entryPrice: 205, currentPrice: 176 },
  ],
};

const liveOpen = {
  success: true,
  sessionStatus: 'OPEN',
  streamStatus: { connected: true },
  modularCandidates: [{}, {}, {}],
  modularSelected: [{}],
  quantDecision: {
    engine: 'INDEX_OPTIONS_QUANT_V2',
    decision: 'ADMIT',
    ranked: [{ strategy_id: 'IRON_CONDOR', index: 'BANKNIFTY', utility: 12.4, expected_value: 3000, cvar95: -31000, stress_loss: -31000, transaction_cost: 120, decision: 'ADMIT' }],
    selected: [{}],
    portfolioRisk: { pass: true, stressLoss: -31000, greeks: { delta: -1.5, gamma: 0.00042, theta: 18.4, vega: -22.7 } },
  },
  strategyBook: { authority: 'INDEX_OPTIONS_QUANT_V2', positions: [openTrade], open: [openTrade], closed: [] },
};

test('Case C live open position: open > 0, selected>0, greeks from open book', () => {
  const view = buildIndexOptionsView(liveOpen, { sessionDate: '' });
  assert.equal(view.isHistorical, false);
  assert.equal(view.open, 1);
  assert.equal(view.selected, 1);
  assert.equal(view.candidates, 3);
  assert.equal(metric(view, 'open').value, '1');
  assert.equal(metric(view, 'selected').value, '1');
  assert.equal(metric(view, 'candidates').value, '3');
  assert.equal(view.greekSemantics, 'OPEN_EXPOSURE');
  assert.equal(view.greeks.delta, -1.5);
  assert.equal(view.greeks.theta, 18.4);
  assert.equal(metric(view, 'delta').value, '-1.5');
});

test('live payload with empty selection list but durable open position does not render Selected 0', () => {
  const payload = {
    ...liveOpen,
    modularSelected: [],
    quantDecision: { ...liveOpen.quantDecision, selected: [] },
  };
  const view = buildIndexOptionsView(payload, { sessionDate: '' });
  assert.equal(view.selected, 1);
  assert.equal(metric(view, 'selected').value, '1');
  assert.equal(metric(view, 'selected').source, 'strategyBook.open.length (live selection list empty)');
});

/* -------------------------------------------------------------------------- */
/*  strategyBook.open / closed mapping                                        */
/* -------------------------------------------------------------------------- */

test('strategyBook.open maps to Open, strategyBook.closed maps to Closed', () => {
  const payload = {
    success: true,
    strategyBook: { open: [openTrade], closed: [closedTrade], positions: [openTrade, closedTrade] },
    quantDecision: { decision: 'ADMIT' },
  };
  const view = buildIndexOptionsView(payload, { sessionDate: '2026-09-15' });
  assert.equal(view.open, 1);
  assert.equal(view.closed, 1);
  assert.equal(view.listMode, 'MIXED');
  assert.equal(metric(view, 'open').source, 'strategyBook.open.length');
  assert.equal(metric(view, 'closed').source, 'strategyBook.closed.length');
});

/* -------------------------------------------------------------------------- */
/*  Greeks aggregation + fallbacks                                            */
/* -------------------------------------------------------------------------- */

test('aggregateOpenGreeks sums net greeks across open positions', () => {
  const aggregate = aggregateOpenGreeks([
    { strategyPositionId: 'a', strategyId: 's', netGreeks: { delta: 1, gamma: 0.1, theta: 2, vega: 3 } },
    { strategyPositionId: 'b', strategyId: 's', netGreeks: { delta: 2, gamma: 0.2, theta: 4, vega: 6 } },
  ]);
  assert.equal(aggregate.delta, 3);
  assert.ok(Math.abs(aggregate.gamma - 0.3) < 1e-9);
  assert.equal(aggregate.theta, 6);
  assert.equal(aggregate.vega, 9);
});

test('missing greeks render "—" (never coerced to 0) when no source exists', () => {
  const payload = { success: true, strategyBook: { open: [], closed: [] }, quantDecision: { decision: 'NO_TRADE' } };
  const view = buildIndexOptionsView(payload, { sessionDate: '' });
  assert.equal(view.greekSemantics, 'UNAVAILABLE');
  assert.equal(metric(view, 'delta').nullable, true);
  assert.equal(metric(view, 'delta').value, '—');
});

test('all-zero portfolio risk greeks render a real 0 (flat exposure, not missing data)', () => {
  const payload = {
    success: true,
    strategyBook: { open: [], closed: [] },
    quantDecision: {
      decision: 'NO_TRADE',
      portfolioRisk: { greeks: { delta: 0, gamma: 0, theta: 0, vega: 0 } },
    },
  };
  const view = buildIndexOptionsView(payload, { sessionDate: '' });
  assert.equal(view.greekSemantics, 'CURRENT_EXPOSURE');
  assert.equal(metric(view, 'delta').nullable, false);
  assert.equal(metric(view, 'delta').value, '0');
});

test('historical closed-only session reports current exposure 0 with closed evidence', () => {
  const view = buildIndexOptionsView(historicalOneTrade, { sessionDate: '2026-09-15' });
  assert.equal(view.greekSemantics, 'CURRENT_EXPOSURE');
  assert.equal(metric(view, 'delta').value, '0');
  assert.match(metric(view, 'delta').source, /no live exposure/);
});

/* -------------------------------------------------------------------------- */
/*  Decision fallback priority                                                */
/* -------------------------------------------------------------------------- */

test('decision prefers quantDecision.decision then marketDecision', () => {
  assert.equal(buildIndexOptionsView({ quantDecision: { decision: 'ADMIT' }, marketDecision: 'NO_TRADE' }).decision, 'ADMIT');
  assert.equal(buildIndexOptionsView({ marketDecision: 'NO_TRADE' }).decision, 'NO_TRADE');
});

test('candidates prefer modularCandidates.length over other counts', () => {
  const view = buildIndexOptionsView({ modularCandidates: [{}, {}, {}], quantDecision: { ranked: [{}] }, candidates: [{}] });
  assert.equal(view.candidates, 3);
  assert.equal(metric(view, 'candidates').source, 'modularCandidates.length');
});

/* -------------------------------------------------------------------------- */
/*  Rendering branches / design-system contract (source-level)                */
/* -------------------------------------------------------------------------- */

test('stat metric row is rendered as bordered card tiles', () => {
  assert.match(panelSource, /desk-metric-grid [^"]*grid-cols/);
  assert.match(panelSource, /className="desk-metric-tile min-w-0 overflow-hidden[^"]*"/);
  assert.match(panelSource, /function StatCard/);
});

test('every grid-cols container also sets display:grid so tiles lay out horizontally', () => {
  const gridClassNames = [...panelSource.matchAll(/className="([^"]*grid-cols[^"]*)"/g)].map((m) => m[1]);
  assert.ok(gridClassNames.length > 0, 'expected at least one grid-cols container');
  for (const className of gridClassNames) {
    const tokens = className.split(' ');
    assert.ok(tokens.includes('grid'), `grid-cols without display:grid in: ${className}`);
  }
});

test('section containers use the shared card primitive', () => {
  assert.match(panelSource, /function SectionCard/);
  assert.match(panelSource, /className=\{`desk-card min-w-0 overflow-hidden p-3 sm:p-4 \$\{className\}`\}/);
});

test('primary sections are rendered through SectionCard', () => {
  for (const title of [
    'PORTFOLIO RISK GOVERNOR',
    'NO-TRADE BENCHMARK',
    'MARKET DECISION',
    'STRUCTURE OPTIMIZER · RANKED CANDIDATES',
  ]) {
    assert.ok(panelSource.includes(`title="${title}"`), `missing SectionCard for ${title}`);
  }
});

test('panel exposes per-metric data-source diagnostics', () => {
  assert.match(panelSource, /data-metric=\{metric\.id\}/);
  assert.match(panelSource, /data-source=\{metric\.source\}/);
});

test('empty state is gated on the absence of both open and closed positions', () => {
  assert.match(panelSource, /\{!visiblePositions\.length && !loading && \(/);
});

test('empty state text is present for historical and live modes', () => {
  assert.match(panelSource, /No open Quant V2 position · NO TRADE is valid\./);
  assert.match(panelSource, /No executed Quant V2 position for this session\./);
});

test('closed historical trade renders a dedicated closed-position card', () => {
  assert.match(panelSource, /function ClosedPositionCard/);
  assert.match(panelSource, /DURABLE LEDGER/);
});

test('summary section uses responsive 1/2/3-column grid', () => {
  assert.match(panelSource, /className="(ix-summary-grid )?grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"/);
});

test('summary cards are wrapped in desk-card via SectionCard', () => {
  for (const title of ['PORTFOLIO RISK GOVERNOR', 'NO-TRADE BENCHMARK', 'MARKET DECISION']) {
    const idx = panelSource.indexOf(`title="${title}"`);
    assert.ok(idx !== -1, `missing ${title}`);
    const before = panelSource.slice(Math.max(0, idx - 200), idx);
    assert.match(before, /SectionCard/);
  }
});

test('long metric text uses compact wrapping style', () => {
  assert.match(panelSource, /isCompactMetric/);
  assert.match(panelSource, /desk-metric-value--compact/);
  assert.match(panelSource, /COMPACT_METRIC_THRESHOLD/);
});

test('help text uses multiline-safe classes', () => {
  assert.match(panelSource, /leading-snug/);
  assert.match(panelSource, /break-words/);
  assert.match(panelSource, /whitespace-normal/);
});

test('no forced single-line overflow on metric tiles', () => {
  assert.match(panelSource, /h-full flex flex-col justify-between/);
  assert.match(panelSource, /min-w-0 overflow-hidden/);
});

test('historical qualification metric remains visible', () => {
  assert.match(panelSource, /Qualification History:.*archived.*Not Archived/);
});

test('replay diagnostic text remains visible', () => {
  assert.match(
    panelSource,
    /Replay is analytical only and does not override durable executions/,
  );
});

test('long exit reason renders completely', () => {
  assert.match(panelSource, /label="Exit reason" value=\{exitReason\}/);
  assert.match(panelSource, /isCompactMetric/);
});
