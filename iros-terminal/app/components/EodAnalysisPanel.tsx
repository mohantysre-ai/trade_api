'use client';

import React, { useEffect, useState, useCallback } from 'react';

/* -------------------------------------------------------------------------- */
/*  Types for EOD report responses from the backend                          */
/* -------------------------------------------------------------------------- */

type IntradayTrade = {
  symbol: string;
  direction: string;
  entryPrice: number;
  exitPrice: number;
  exitReason: string;
  qty: number;
  deployedCapital: number;
  pnl: number;
  pnlPct: number | null;
  missAnalysis: string | null;
};

type IntradayReport = {
  date: string;
  capital: number;
  totalDeployed: number;
  totalPnl: number;
  remainingCapital: number;
  hitBreakdown: { T1_HIT: number; T2_HIT: number; SL_HIT: number; EOD_SQUAREOFF: number };
  hitRatePct: number;
  trades: IntradayTrade[];
};

type SwingPick = {
  symbol: string;
  direction: string;
  entryDate: string | null;
  daysHeld: number | null;
  dayBucket: number | null;
  status: string;
  entryPrice: number;
  refPrice930: number;
  currentPrice: number;
  stopLoss: number;
  target1: number;
  target2: number;
  qty: number;
  deployedCapital: number;
  pnl: number;
  pnlPct: number;
  alertsFired: unknown[];
};

type SwingReport = {
  date: string;
  totalPicks: number;
  totalDeployed: number;
  totalPnl: number;
  totalPnlPct: number | null;
  winCount: number;
  lossCount: number;
  bestPerformer: SwingPick | null;
  worstPerformer: SwingPick | null;
  pnlByDayBucket: Record<string, number>;
  picks: SwingPick[];
  isMock?: boolean;
  referenceDate?: string;
  referenceLabel?: string;
};

/* -------------------------------------------------------------------------- */
/*  Helper: color classes for exit reasons                                    */
/* -------------------------------------------------------------------------- */
function exitReasonBadge(reason: string) {
  switch (reason) {
    case 'T2_HIT': return { bg: 'bg-emerald-100', txt: 'text-emerald-800', label: 'T2 ✓' };
    case 'T1_HIT': return { bg: 'bg-emerald-50', txt: 'text-emerald-700', label: 'T1 ✓' };
    case 'SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'SL ✗' };
    case 'EOD_SQUAREOFF': return { bg: 'bg-amber-100', txt: 'text-amber-800', label: 'EOD ∎' };
    default: return { bg: 'bg-slate-100', txt: 'text-slate-600', label: reason };
  }
}

function statusBadge(status: string) {
  switch (status) {
    case 'T2_HIT': return { bg: 'bg-emerald-100', txt: 'text-emerald-800', label: 'T2 ✓' };
    case 'T1_HIT': return { bg: 'bg-emerald-50', txt: 'text-emerald-700', label: 'T1 ✓' };
    case 'SL_HIT': return { bg: 'bg-red-100', txt: 'text-red-800', label: 'SL ✗' };
    case 'NOT_TRIGGERED': return { bg: 'bg-slate-200', txt: 'text-slate-600', label: 'Not Triggered' };
    case 'OPEN': return { bg: 'bg-blue-100', txt: 'text-blue-800', label: 'Open ◇' };
    default: return { bg: 'bg-slate-100', txt: 'text-slate-600', label: status };
  }
}

/* -------------------------------------------------------------------------- */
/*  Single-number Sparkline (mini bar chart)                                  */
/* -------------------------------------------------------------------------- */
function MiniSparklineBar({ positive, width = 100 }: { positive: boolean; width?: number }) {
  const color = positive ? '#10b981' : '#ef4444';
  return (
    <svg className="w-full h-6" viewBox={`0 0 ${width} 20`} preserveAspectRatio="none">
      <rect x="0" y="8" width="20%" height="10" rx="1.5" fill={color} opacity="0.6" />
      <rect x="22%" y="5" width="20%" height="13" rx="1.5" fill={color} opacity="0.8" />
      <rect x="44%" y="2" width="20%" height="16" rx="1.5" fill={color} opacity="0.9" />
      <rect x="66%" y="6" width="20%" height="12" rx="1.5" fill={color} />
      <rect x="88%" y="0" width="12%" height="18" rx="1.5" fill={color} />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/*  EOD Analysis Panel — fetches both reports and renders a dashboard         */
/* -------------------------------------------------------------------------- */
export default function EodAnalysisPanel() {
  const [intraday, setIntraday] = useState<IntradayReport | null>(null);
  const [swing, setSwing] = useState<SwingReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dateStr, setDateStr] = useState(() => new Date().toISOString().slice(0, 10));
  const [swingDateStr, setSwingDateStr] = useState(() => '');

  const fetchReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const intradayParam = dateStr ? `?date=${dateStr}` : '';
      const swingParam = swingDateStr ? `?date=${swingDateStr}` : '';

      const [intraRes, swingRes] = await Promise.all([
        fetch(`/api/reports/eod-intraday${intradayParam}`, { cache: 'no-store' }),
        fetch(`/api/reports/eod-swing${swingParam}`, { cache: 'no-store' }),
      ]);

      if (!intraRes.ok) {
        const text = await intraRes.text().catch(() => '');
        throw new Error(`Intraday API ${intraRes.status}: ${text}`);
      }
      if (!swingRes.ok) {
        const text = await swingRes.text().catch(() => '');
        throw new Error(`Swing API ${swingRes.status}: ${text}`);
      }

      const intraData: IntradayReport = await intraRes.json();
      const swingData: SwingReport = await swingRes.json();
      setIntraday(intraData);
      setSwing(swingData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch EOD reports');
    } finally {
      setLoading(false);
    }
  }, [dateStr, swingDateStr]);

  useEffect(() => { fetchReports(); }, [fetchReports]);

  const noIntraday = intraday && (!intraday.trades || intraday.trades.length === 0);
  const noSwing = swing && (!swing.picks || swing.picks.length === 0);

  return (
    <div className="space-y-3">
      {/* Refresh controls */}
      <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Intraday Date</span>
            <input
              type="date"
              value={dateStr}
              onChange={(e) => setDateStr(e.target.value)}
              className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Swing Date</span>
            <input
              type="date"
              value={swingDateStr}
              onChange={(e) => setSwingDateStr(e.target.value)}
              className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-teal-300"
            />
            <span className="text-[9px] text-slate-400">(default: today)</span>
          </div>
          <button
            onClick={fetchReports}
            disabled={loading}
            className="ml-auto px-3 py-1 rounded-full bg-teal-600 text-white text-[9px] font-black uppercase tracking-wider hover:bg-teal-500 disabled:opacity-50 transition"
          >
            {loading ? 'LOADING...' : 'REFRESH'}
          </button>
        </div>
      </div>

      {loading && (
        <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl p-6 text-center text-[11px] text-slate-400 shadow-sm">
          Loading EOD reports...
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-3 text-[11px]">
          {error}
        </div>
      )}

      {!loading && !error && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {/* ── INTRADAY REPORT ── */}
          <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-teal-50 to-teal-100/50 px-3 py-2 border-b border-slate-200">
              <h3 className="text-[11px] font-black text-teal-800 uppercase tracking-wider">Intraday EOD Report</h3>
              <p className="text-[9px] text-teal-600">{intraday?.date ?? dateStr}</p>
            </div>

            {noIntraday ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">No archived intraday picks for this date.</div>
            ) : intraday ? (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Total P&L</div>
                    <div className={`text-[14px] font-black tabular-nums ${intraday.totalPnl >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                      {intraday.totalPnl >= 0 ? '+' : ''}₹{intraday.totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Deployed</div>
                    <div className="text-[14px] font-black text-slate-800 tabular-nums">₹{intraday.totalDeployed.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Remaining</div>
                    <div className="text-[14px] font-black text-slate-800 tabular-nums">₹{intraday.remainingCapital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Hit Rate</div>
                    <div className="text-[14px] font-black text-slate-800 tabular-nums">{intraday.hitRatePct}%</div>
                  </div>
                </div>

                {/* Hit breakdown */}
                <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-100 text-[9px]">
                  <span className="text-slate-500 uppercase tracking-wider font-bold">Breakdown:</span>
                  <span className="bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-bold">T2 {intraday.hitBreakdown.T2_HIT}</span>
                  <span className="bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded font-bold">T1 {intraday.hitBreakdown.T1_HIT}</span>
                  <span className="bg-red-100 text-red-800 px-1.5 py-0.5 rounded font-bold">SL {intraday.hitBreakdown.SL_HIT}</span>
                  <span className="bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-bold">EOD {intraday.hitBreakdown.EOD_SQUAREOFF}</span>
                </div>

                {/* Trades table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="text-slate-500 uppercase tracking-wider border-b border-slate-100">
                        <th className="text-left px-2 py-1.5 font-bold">Symbol</th>
                        <th className="text-right px-2 py-1.5 font-bold">Entry</th>
                        <th className="text-right px-2 py-1.5 font-bold">Exit</th>
                        <th className="text-center px-2 py-1.5 font-bold">Result</th>
                        <th className="text-right px-2 py-1.5 font-bold">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {intraday.trades.map((trade, i) => {
                        const badge = exitReasonBadge(trade.exitReason);
                        return (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-2 py-1.5">
                              <span className={`font-bold ${trade.direction === 'LONG' ? 'text-emerald-700' : 'text-red-700'}`}>
                                {trade.symbol}
                              </span>
                              <span className="text-[8px] text-slate-400 ml-1">{trade.direction}</span>
                            </td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{trade.entryPrice}</td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{trade.exitPrice}</td>
                            <td className="text-center px-2 py-1.5">
                              <span className={`${badge.bg} ${badge.txt} px-1 py-0.5 rounded text-[9px] font-bold`}>{badge.label}</span>
                            </td>
                            <td className={`text-right px-2 py-1.5 font-bold tabular-nums ${trade.pnl >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                              {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl.toFixed(2)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="p-4 text-[11px] text-slate-400 text-center">No intraday data available.</div>
            )}
          </div>

          {/* ── SWING REPORT ── */}
          <div className="bg-white border border-slate-300 border-[0.5px] rounded-xl shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-indigo-50 to-indigo-100/50 px-3 py-2 border-b border-slate-200">
              <h3 className="text-[11px] font-black text-indigo-800 uppercase tracking-wider">Swing EOD Report</h3>
              <p className="text-[9px] text-indigo-600">{swing?.date ?? dateStr}</p>
            </div>

            {noSwing ? (
              <div className="p-4 text-[11px] text-slate-400 text-center">No picks in the fixed trade plan.</div>
            ) : swing ? (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 bg-slate-50/50">
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Total P&L</div>
                    <div className={`text-[14px] font-black tabular-nums ${swing.totalPnl >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                      {swing.totalPnl >= 0 ? '+' : ''}₹{swing.totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Win / Loss</div>
                    <div className="text-[14px] font-black tabular-nums">
                      <span className="text-emerald-700">{swing.winCount}</span>
                      <span className="text-slate-400">/</span>
                      <span className="text-red-700">{swing.lossCount}</span>
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Total P&L %</div>
                    <div className={`text-[14px] font-black tabular-nums ${(swing.totalPnlPct ?? 0) >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                      {swing.totalPnlPct != null ? `${swing.totalPnlPct >= 0 ? '+' : ''}${swing.totalPnlPct}%` : 'N/A'}
                    </div>
                  </div>
                  <div className="bg-white rounded-lg p-2 border border-slate-200 text-center">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wider">Picks</div>
                    <div className="text-[14px] font-black text-slate-800 tabular-nums">{swing.totalPicks}</div>
                  </div>
                </div>

                {/* P&L by day bucket */}
                {Object.keys(swing.pnlByDayBucket).length > 0 && (
                  <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-100 text-[9px] flex-wrap">
                    <span className="text-slate-500 uppercase tracking-wider font-bold">P&L by Day:</span>
                    {Object.entries(swing.pnlByDayBucket).map(([bucket, pnl]) => (
                      <span key={bucket} className={`px-1.5 py-0.5 rounded font-bold ${pnl >= 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
                        Day {bucket}: {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}
                      </span>
                    ))}
                  </div>
                )}

                {/* Picks table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="text-slate-500 uppercase tracking-wider border-b border-slate-100">
                        <th className="text-left px-2 py-1.5 font-bold">Symbol</th>
                        <th className="text-center px-2 py-1.5 font-bold">Status</th>
                        <th className="text-right px-2 py-1.5 font-bold">Entry</th>
                        <th className="text-right px-2 py-1.5 font-bold">Current</th>
                        <th className="text-center px-2 py-1.5 font-bold">Held</th>
                        <th className="text-right px-2 py-1.5 font-bold">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {swing.picks.map((pick, i) => {
                        const badge = statusBadge(pick.status);
                        return (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-2 py-1.5">
                              <span className={`font-bold ${pick.direction === 'LONG' ? 'text-emerald-700' : 'text-red-700'}`}>
                                {pick.symbol}
                              </span>
                              <span className="text-[8px] text-slate-400 ml-1">{pick.direction}</span>
                            </td>
                            <td className="text-center px-2 py-1.5">
                              <span className={`${badge.bg} ${badge.txt} px-1 py-0.5 rounded text-[9px] font-bold`}>{badge.label}</span>
                            </td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{pick.entryPrice}</td>
                            <td className="text-right px-2 py-1.5 text-slate-700 tabular-nums">{pick.currentPrice}</td>
                            <td className="text-center px-2 py-1.5 text-slate-500">
                              {pick.daysHeld != null ? `${pick.daysHeld}d` : '-'}
                              {pick.dayBucket != null && <span className="text-[8px] text-slate-400 ml-1">(D{pick.dayBucket})</span>}
                            </td>
                            <td className={`text-right px-2 py-1.5 font-bold tabular-nums ${pick.pnl >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                              {pick.pnl >= 0 ? '+' : ''}₹{pick.pnl.toFixed(2)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="p-4 text-[11px] text-slate-400 text-center">No swing data available.</div>
            )}
          </div>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Best / Worst performer cards */}
          {swing && (swing.bestPerformer || swing.worstPerformer) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {swing.bestPerformer && (
                <div className="bg-gradient-to-r from-emerald-50 to-white border border-emerald-200 rounded-xl p-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="text-[9px] uppercase tracking-wider text-emerald-700 font-bold">Best Performer</span>
                  </div>
                  <div className="flex items-end justify-between mt-1">
                    <div>
                      <span className="text-[16px] font-black text-slate-900">{swing.bestPerformer.symbol}</span>
                      <span className="text-[10px] text-slate-500 ml-1">{swing.bestPerformer.direction}</span>
                    </div>
                    <span className="text-[16px] font-black text-emerald-600 tabular-nums">+₹{swing.bestPerformer.pnl.toFixed(2)}</span>
                  </div>
                </div>
              )}
              {swing.worstPerformer && (
                <div className="bg-gradient-to-r from-red-50 to-white border border-red-200 rounded-xl p-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                    <span className="text-[9px] uppercase tracking-wider text-red-700 font-bold">Worst Performer</span>
                  </div>
                  <div className="flex items-end justify-between mt-1">
                    <div>
                      <span className="text-[16px] font-black text-slate-900">{swing.worstPerformer.symbol}</span>
                      <span className="text-[10px] text-slate-500 ml-1">{swing.worstPerformer.direction}</span>
                    </div>
                    <span className="text-[16px] font-black text-red-600 tabular-nums">₹{swing.worstPerformer.pnl.toFixed(2)}</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Intraday miss analysis section — same card design as NIFTY TOP 5 GAINERS & LOSERS */}
          {intraday && intraday.trades.filter(t => t.missAnalysis).length > 0 && (
            <div className="bg-white border border-slate-300 border-[0.5px] rounded-lg p-2.5 shadow-sm min-h-[160px] overflow-visible">
              <div className="flex items-center gap-1.5 mb-2">
                <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                <span className="text-[13px] uppercase tracking-wider text-slate-800 font-black">Miss Analysis</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-1.5">
                {intraday.trades.filter(t => t.missAnalysis).map((trade, i) => (
                  <div key={i} className="bg-white border border-slate-200 rounded-lg p-2 min-h-[160px] overflow-visible shadow-sm">
                    <div className="flex items-center justify-between py-2 cursor-default border-b border-slate-100 last:border-b-0">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className={`w-1.5 h-1.5 rounded-full ${trade.direction === 'LONG' ? 'bg-emerald-500' : 'bg-red-500'}`} />
                          <span className="text-[12px] font-bold text-slate-800">{trade.symbol}</span>
                        </div>
                      </div>
                      <span className={`text-[11px] font-semibold tabular-nums min-w-[50px] text-right ${trade.pnl >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                        {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl.toFixed(2)}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-700 leading-relaxed mt-1 px-1">{trade.missAnalysis || 'No analysis available.'}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}