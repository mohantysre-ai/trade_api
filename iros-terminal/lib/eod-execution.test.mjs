import test from 'node:test';
import assert from 'node:assert/strict';
import { isLiveSessionFill, isExplicitNonFill, canOverlayIntradayBook } from './eod-execution.ts';

test('explicit NOT_TRIGGERED defeats stale positive fill evidence', () => {
  assert.equal(isLiveSessionFill({status: 'NOT_TRIGGERED', triggered: true, executionStatus: 'FILLED', realizedPnl: 0}), false);
  assert.equal(isLiveSessionFill({skipped: true, triggered: true}), false);
  assert.equal(isLiveSessionFill({triggered: false, executionStatus: 'EXECUTED'}), false);
  assert.equal(isExplicitNonFill({executionStatus: 'NOT_TRIGGERED'}), true);
});

test('zero P&L, planned quantity and open/closed flags do not prove execution', () => {
  for (const mark of [{realizedPnl: 0}, {remainingQty: 372}, {closed: false}, {status: 'RUNNING'}, {realizedPnl: -100}]) {
    assert.equal(isLiveSessionFill(mark), false);
  }
});

test('an explicit confirmed fill can promote a stale skipped book while open', () => {
  assert.equal(isLiveSessionFill({triggered: true}), true);
  assert.equal(isLiveSessionFill({executionStatus: 'FILLED'}), true);
  assert.equal(canOverlayIntradayBook('OPEN', true), true);
});

test('closed EOD never receives quote-based repricing', () => {
  assert.equal(canOverlayIntradayBook('CLOSED', false), false);
  assert.equal(canOverlayIntradayBook('CLOSED', true), false);
  assert.equal(canOverlayIntradayBook('OPEN', false), false);
});

test('September 1 non-fills cannot add the phantom -5798.65 MTM', () => {
  const rows = ['LICHSGFIN', 'AMBER', 'VEDL', 'DLF', 'EICHERMOT'].map(symbol => ({symbol, status: 'NOT_TRIGGERED', realizedPnl: 0}));
  assert.equal(rows.filter(isLiveSessionFill).length, 0);
  const closed = [101.27, -473.22, -492.8];
  assert.equal(Number(closed.reduce((sum, pnl) => sum + pnl, 0).toFixed(2)), -864.75);
});
