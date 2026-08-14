'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { fetchLiveDeskSnapshot, subscribeLiveDesk } from '@/lib/live-desk';
import type { MarketDataResponse, TerminalIntelligence, LiveStock, SparkFlag } from '@/lib/market-api';
import { fetchNseSparkline } from '@/lib/market-api';
import {
  chipToneClass,
  buildMatrixSourceChips,
  computeInstitutionalSizingHint,
  convictionTierBadgeLabel,
  convictionTierStyles,
  dhanRrValue,
  evaluateMatrixBuyCandidate,
  estimateStructuralRr,
  isInstitutionalMatrixMode,
  isInstitutionalOffHoursContext,
  MATRIX_BUY_MIN_DISPLAY,
  MATRIX_BUY_MIN_SCORE,
  MATRIX_BUY_TOP_N,
  INSTITUTIONAL_MATRIX_TOP_N,
  mergeIntelligenceSummary,
  matrixSourceChipClass,
  SCORE_STRONG,
  selectMatrixDisplayRows,
  SCORE_MODERATE,
  SCORE_WEAK,
  type ConvictionTier,
  type DhanSwingPick,
  type MergedIntelligenceSummary,
  type TrendlyneCardSummary,
  type WinEdgeResult,
} from '@/lib/intelligence-summary';
import type { DhanSwingPicksPayload } from '@/lib/market-api';
import { DeskCardTilt, DeskGaugeFill, IcStatusChip, LiveTickNumber, motion, useReducedMotion } from '@/lib/desk-motion';
import { duration } from '@/lib/motion-tokens';
import { formatPtsPctLabel, formatSeriesDelta } from '@/lib/format-delta';

const MAX_TRENDLYNE_CARDS = 12;
const TRENDLYNE_BATCH_SIZE = 4;

/* ── Smooth sparkline SVG with Catmull-Rom spline ─────────────────────── */
const SPARK_FLAGS: SparkFlag[] = ['1D', '1M', '1Y'];

let assetSparkIdCounter = 0;

/**
 * Convert Catmull-Rom spline points to smooth cubic bezier path.
 * Produces organic, flowing curves instead of jagged line segments.
 */
function catmullRomToBezier(points: readonly (readonly [number, number])[]): string {
  if (points.length < 2) return '';
  if (points.length === 2) {
    return `M ${points[0][0].toFixed(2)},${points[0][1].toFixed(2)} L ${points[1][0].toFixed(2)},${points[1][1].toFixed(2)}`;
  }
  const tension = 0.5;
  let d = `M ${points[0][0].toFixed(2)},${points[0][1].toFixed(2)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6 * tension * 2;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6 * tension * 2;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6 * tension * 2;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6 * tension * 2;
    d += ` C ${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

function StockSparklineSVG({ data }: { data: number[] }) {
  const [id] = useState(() => `asset-spk-${++assetSparkIdCounter}`);
  const [glowId] = useState(() => `asset-glow-${++assetSparkIdCounter}`);
  const reduce = useReducedMotion();
  if (!data || data.length < 2) return null;

  const first = data[0];
  const last = data[data.length - 1];
  const positive = last >= first;
  const color = positive ? '#10b981' : '#ef4444';

  const W = 200;
  const H = 56;
  const pad = 8;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad * 2);
    const y = pad + (1 - (v - min) / range) * (H - pad * 2);
    return [x, y] as const;
  });

  const pathD = catmullRomToBezier(points);
  const areaD = `${pathD} L ${points[points.length - 1][0].toFixed(2)},${H} L ${points[0][0].toFixed(2)},${H} Z`;
  const lastPt = points[points.length - 1];
  const gridLines = [0.25, 0.5, 0.75].map((f) => pad + f * (H - pad * 2));
  const minIdx = data.indexOf(Math.min(...data));
  const maxIdx = data.indexOf(Math.max(...data));

  return (
    <svg className="w-full h-14" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="50%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
        <filter id={glowId} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="1.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {gridLines.map((gy, i) => (
        <line
          key={`grid-${i}`}
          x1={pad}
          y1={gy}
          x2={W - pad}
          y2={gy}
          stroke="rgba(148,163,184,0.12)"
          strokeWidth="0.3"
          strokeDasharray="2,3"
        />
      ))}
      <motion.path
        d={areaD}
        fill={`url(#${id})`}
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: reduce ? 0.01 : duration.sparkDraw * 0.45, delay: reduce ? 0 : 0.35 }}
      />
      <motion.path
        d={pathD}
        stroke={color}
        strokeWidth="1.2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${glowId})`}
        pathLength={1}
        initial={reduce ? false : { pathLength: 0, opacity: 0.85 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: reduce ? 0.01 : duration.sparkDraw, ease: [0.16, 1, 0.3, 1] }}
      />
      <circle cx={points[maxIdx][0]} cy={points[maxIdx][1]} r="1.5" fill={color} stroke="white" strokeWidth="0.8" opacity="0.6" />
      <circle cx={points[minIdx][0]} cy={points[minIdx][1]} r="1.5" fill={color} stroke="white" strokeWidth="0.8" opacity="0.6" />
      <circle cx={lastPt[0]} cy={lastPt[1]} r="2.5" fill={color} stroke="white" strokeWidth="1.2">
        {!reduce && (
          <>
            <animate attributeName="r" values="2.5;3.5;2.5" dur="2s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="1;0.7;1" dur="2s" repeatCount="indefinite" />
          </>
        )}
      </circle>
    </svg>
  );
}

function useStockSparklines(tickers: string[], flag: SparkFlag): Record<string, Record<SparkFlag, number[]>> {
  const [sparklines, setSparklines] = useState<Record<string, Record<SparkFlag, number[]>>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const missing = tickers.filter((t) => t && !fetchedRef.current.has(`${t}:${flag}`));
    if (missing.length === 0) return;

    let cancelled = false;

    const fetchAll = async () => {
      const results = await Promise.allSettled(
        missing.map(async (ticker) => {
          let sparkline: number[] = [];

          try {
            const res = await fetch(`/api/stock-sparkline?ticker=${encodeURIComponent(ticker)}&flag=${flag}`, { cache: 'no-store' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            sparkline = (data.sparkline as number[]) ?? [];
          } catch {
            try {
              sparkline = await fetchNseSparkline(ticker, flag);
            } catch {
              sparkline = [];
            }
          }

          return { ticker, sparkline };
        })
      );

      if (cancelled) return;

      const updates: Record<string, Record<SparkFlag, number[]>> = {};
      for (const result of results) {
        if (result.status === 'fulfilled' && result.value.sparkline.length >= 2) {
          if (!updates[result.value.ticker]) updates[result.value.ticker] = {} as Record<SparkFlag, number[]>;
          updates[result.value.ticker][flag] = result.value.sparkline;
          fetchedRef.current.add(`${result.value.ticker}:${flag}`);
        }
      }

      if (Object.keys(updates).length > 0) {
        setSparklines((prev) => {
          const next = { ...prev };
          for (const [tkr, flagData] of Object.entries(updates)) {
            next[tkr] = { ...(next[tkr] ?? {} as Record<SparkFlag, number[]>), ...flagData };
          }
          return next;
        });
      }
    };

    void fetchAll();

    return () => {
      cancelled = true;
    };
  }, [tickers, flag]);

  return sparklines;
}

function sparkPeriodChange(data: number[] | undefined): { label: string; pct: number; positive: boolean } | null {
  if (!data || data.length < 2 || !data[0]) return null;
  const first = data[0];
  const last = data[data.length - 1];
  return formatSeriesDelta(first, last);
}

function SparklineFlagSlider({ ticker, sparklines, onFlagChange, currentFlag }: {
  ticker: string;
  sparklines: Record<SparkFlag, number[]>;
  onFlagChange: (flag: SparkFlag) => void;
  currentFlag: SparkFlag;
}) {
  const data = sparklines?.[currentFlag];
  const hasData = data && data.length >= 2;
  const change = sparkPeriodChange(data);
  const positive = change?.positive ?? true;

  return (
    <div className="mb-1.5 relative z-10">
      {/* Chart band — no overflow-hidden so glow / pulse ring are not clipped */}
      <div
        className="rounded-lg transition-all px-0.5 py-0.5"
        style={{
          background: hasData
            ? positive
              ? 'linear-gradient(135deg, rgba(16,185,129,0.06) 0%, rgba(16,185,129,0.12) 100%)'
              : 'linear-gradient(135deg, rgba(239,68,68,0.06) 0%, rgba(239,68,68,0.12) 100%)'
            : 'transparent',
        }}
      >
        {hasData ? (
          <StockSparklineSVG data={data!} />
        ) : (
          <div className="h-14 flex items-center justify-center">
            <div className="flex items-center gap-1">
              <div className="w-1 h-1 rounded-full bg-slate-300 animate-pulse" />
              <div className="w-1 h-1 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: '0.2s' }} />
              <div className="w-1 h-1 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: '0.4s' }} />
            </div>
          </div>
        )}
      </div>
      {/* Flag slider + change badge */}
      <div className="flex items-center justify-between mt-0.5">
        <div className="flex items-center gap-0.5">
          {SPARK_FLAGS.map((f) => (
            <button
              key={f}
              onClick={(e) => { e.stopPropagation(); onFlagChange(f); }}
              className={`min-h-10 min-w-10 py-2 px-2.5 sm:min-h-0 sm:min-w-0 sm:px-1.5 sm:py-0.5 rounded-md desk-chip ${
                f === currentFlag ? 'is-on' : ''
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        {change && (
          <span className={`text-[10px] sm:text-[7px] font-bold tabular-nums ${change.positive ? 'text-emerald-600' : 'text-red-500'}`}>
            {change.label}
          </span>
        )}
      </div>
    </div>
  );
}

type StockIntraday = {
  atr_pct?: number;
  orb_velocity_pct?: number;
  volume_multiplier?: number;
  turnover_cr?: number;
  passes_hard_filters?: boolean;
  passes_quality_filters?: boolean;
  hard_filter_reasons?: string[];
};

type StockWithIntraday = LiveStock & {
  intraday?: StockIntraday;
  passes_hard_filters?: boolean;
};

type LedgerStockRow = {
  ticker: string;
  score?: number;
  action?: string;
  selection_reason?: string;
  live_price?: string;
  delta?: string;
  day_change_pct?: string;
  risk_flag?: string;
  policy_allocation_pct?: string;
};

function parsePercent(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const text = String(value ?? '').trim();
  const match = text.match(/^([+-]?[0-9]+(?:\.[0-9]+)?)\s*%?$/);
  return match ? parseFloat(match[1]) : 0;
}

function parseWinLossRatio(value: unknown): number | null {
  const text = String(value ?? '').trim();
  const match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$/);
  if (!match) return null;
  const left = parseFloat(match[1]);
  const right = parseFloat(match[2]);
  if (!Number.isFinite(left) || !Number.isFinite(right) || right <= 0) return null;
  return left / right;
}

function parsePercentValue(value: unknown): number | null {
  const text = String(value ?? '').trim();
  const match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*%$/);
  return match ? parseFloat(match[1]) : null;
}

/** Mirrors backend intelligence_engine._risk_flag_from_metrics thresholds. */
function riskFlagFromMetrics(
  score: number,
  delta: number,
  atr: number,
  volumeMultiplier: number,
  winLossRatioText?: unknown,
  kellyPolicyText?: unknown,
): string {
  let riskScore = 50;

  // Intraday engine scores span ~0–25 (bands: 8 weak, 12 moderate, 18 strong).
  if (score >= SCORE_STRONG) riskScore -= 18;
  else if (score >= 15) riskScore -= 10;
  else if (score >= SCORE_MODERATE) riskScore -= 2;
  else riskScore += 10;

  const absDelta = Math.abs(delta);
  if (absDelta >= 6) riskScore += 12;
  else if (absDelta >= 3) riskScore += 6;
  else if (absDelta < 1) riskScore -= 2;

  if (atr >= 4) riskScore += 18;
  else if (atr >= 3) riskScore += 10;
  else if (atr >= 2) riskScore += 4;
  else riskScore -= 4;

  if (volumeMultiplier >= 2.0) riskScore -= 8;
  else if (volumeMultiplier >= 1.0) riskScore -= 4;
  else if (volumeMultiplier < 0.5) riskScore += 8;

  const wlRatio = parseWinLossRatio(winLossRatioText);
  if (wlRatio !== null) {
    if (wlRatio >= 3.0) riskScore -= 10;
    else if (wlRatio >= 1.8) riskScore -= 5;
    else if (wlRatio < 1.0) riskScore += 8;
  }

  const kellyPct = parsePercentValue(kellyPolicyText);
  if (kellyPct !== null) {
    if (kellyPct >= 12) riskScore -= 8;
    else if (kellyPct >= 6) riskScore -= 4;
    else if (kellyPct <= 2) riskScore += 4;
  }

  riskScore = Math.max(0, Math.min(100, riskScore));

  if (riskScore < 30) return 'LOW_RISK';
  if (riskScore < 55) return 'MODERATE_RISK';
  if (riskScore < 75) return 'HIGH_RISK';
  return 'EXTREME_RISK';
}

function normalizeRiskFlag(value: unknown): string {
  const text = String(value ?? '').trim().toUpperCase().replace(/\s+/g, '_');
  if (!text || text === 'N/A' || text === 'NA' || text === 'NONE' || text === '-') return '';
  return text;
}

function isVolumePadStock(stock: StockWithIntraday | undefined): boolean {
  if (!stock) return false;
  const reasons = stock.intraday?.hard_filter_reasons ?? [];
  return reasons.some((reason) => /not in intraday candidate|volume pad|non-qualifier/i.test(reason));
}

function resolveRiskFlag(opts: {
  ledgerRiskFlag?: string;
  tickerRiskCalc?: Record<string, unknown>;
  stock?: StockWithIntraday;
  quote?: StockWithIntraday;
  score: number;
  deltaText?: string;
  kellyPolicy?: string;
  marketRisk?: Record<string, unknown>;
  allowVolumeFill?: boolean;
}): string {
  const fromLedger = normalizeRiskFlag(opts.ledgerRiskFlag);
  if (fromLedger) return fromLedger;

  const stock = opts.stock;
  const quote = opts.quote ?? stock;
  const intraday = stock?.intraday ?? quote?.intraday;
  const atr = typeof intraday?.atr_pct === 'number' ? intraday.atr_pct : 0;
  const volumeMultiplier = typeof intraday?.volume_multiplier === 'number' ? intraday.volume_multiplier : 0;
  const delta = parsePercent(opts.deltaText ?? quote?.delta ?? stock?.delta);
  const hasMetrics = atr > 0 || volumeMultiplier > 0 || opts.score > 0;

  // Intraday scores are ~0–25; prefer live metrics over stale ticker-intel EXTREME flags.
  if (hasMetrics && opts.score <= 30) {
    return riskFlagFromMetrics(
      opts.score,
      delta,
      atr,
      volumeMultiplier,
      opts.marketRisk?.win_loss_ratio,
      opts.kellyPolicy ?? opts.marketRisk?.kelly_policy_max,
    );
  }

  const fromTicker = normalizeRiskFlag(opts.tickerRiskCalc?.risk_flag);
  if (fromTicker) return fromTicker;

  // Volume-pad names are tracked via isVolumePad on the row — no VOLUME_FILL badge on cards.
  if (opts.allowVolumeFill && isVolumePadStock(opts.stock)) {
    return '';
  }

  if (hasMetrics) {
    return riskFlagFromMetrics(
      opts.score,
      delta,
      atr,
      volumeMultiplier,
      opts.marketRisk?.win_loss_ratio,
      opts.kellyPolicy ?? opts.marketRisk?.kelly_policy_max,
    );
  }

  return 'UNRATED';
}

type AssetRow = {
  ticker: string;
  price: string;
  score: number;
  scoreScale: 'angel' | 'dhan' | 'unknown';
  kellyPolicy?: string;
  winLossRatio?: string;
  dayChangePct: number | null;
  thesis: string;
  action?: string;
  riskFlag: string;
  passesHardFilters?: boolean;
  passesQualityFilters?: boolean;
  hardFilterReasons?: string[];
  isVolumePad: boolean;
  isMetaRow: boolean;
  state?: string;
  promoterPct?: number;
  bulkDealValueCr?: number;
  bulkDealSignal?: boolean;
  dhanPick?: DhanSwingPick;
  hasQuantSource: boolean;
  atrPct?: number;
  deskIcDecision?: string;
};

type MatrixCardRow = {
  row: AssetRow;
  tier: ConvictionTier;
  reason: string;
  winEdge: WinEdgeResult | null;
  intelligence: MergedIntelligenceSummary;
};

function scoreToStrengthBars(score: number): number {
  if (score <= 0) return 0;
  if (score < SCORE_WEAK) return 1;
  if (score < 12) return 2;
  if (score < 15) return 3;
  if (score < SCORE_STRONG) return 4;
  return 5;
}

function useTrendlyneSummaries(tickers: string[], maxCards = MAX_TRENDLYNE_CARDS) {
  const [summaries, setSummaries] = useState<Record<string, TrendlyneCardSummary>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const eligible = tickers
      .filter((ticker) => ticker && !/\s/.test(ticker) && !fetchedRef.current.has(ticker))
      .slice(0, maxCards);

    if (!eligible.length) return;

    let cancelled = false;

    const fetchBatches = async () => {
      for (let i = 0; i < eligible.length; i += TRENDLYNE_BATCH_SIZE) {
        if (cancelled) return;
        const batch = eligible.slice(i, i + TRENDLYNE_BATCH_SIZE);
        try {
          const res = await fetch(
            `/api/trendlyne-summary?tickers=${encodeURIComponent(batch.join(','))}`,
            { cache: 'no-store' },
          );
          if (!res.ok) continue;
          const body = await res.json();
          const batchSummaries = (body.summaries ?? {}) as Record<string, TrendlyneCardSummary>;
          if (cancelled) return;

          const updates: Record<string, TrendlyneCardSummary> = {};
          for (const ticker of batch) {
            const summary = batchSummaries[ticker];
            if (summary) {
              updates[ticker] = summary;
              fetchedRef.current.add(ticker);
            }
          }

          if (Object.keys(updates).length > 0) {
            setSummaries((prev) => ({ ...prev, ...updates }));
          }
        } catch {
          // Keep card usable with drawer / terminal intelligence only.
        }
      }
    };

    void fetchBatches();

    return () => {
      cancelled = true;
    };
  }, [tickers, maxCards]);

  return summaries;
}

function StrengthMeter({ score }: { score: number }) {
  const bars = scoreToStrengthBars(score);
  const label = bars === 0 ? '—' : `${bars}/5`;
  const pct = Math.max(0, Math.min(100, (bars / 5) * 100));
  const tone =
    bars >= 4 ? 'bg-emerald-500' : bars >= 3 ? 'bg-[var(--terminal-marigold)]' : 'bg-slate-400';
  return (
    <div className="flex items-center gap-1.5 min-w-[7.5rem]" title={`Setup strength ${label} (score ${score.toFixed(1)})`}>
      <span className="text-[10px] sm:text-[8px] font-bold uppercase tracking-wider text-slate-400">Strength</span>
      <DeskGaugeFill pct={pct} className="w-14" toneClass={tone} />
      <LiveTickNumber
        value={score > 0 ? score.toFixed(1) : '—'}
        className="text-[10px] sm:text-[8px] font-bold text-slate-500"
      />
    </div>
  );
}

const DEFAULT_POOLS = ['Nifty 500', 'Nifty 100', 'Live Universe'] as const;

type SwingLongPosition = {
  symbol?: string;
  closed?: boolean;
  status?: string | null;
  outcome?: { label?: string | null } | null;
};

function uniqueSwingLongPositions<T extends SwingLongPosition>(rows: T[] | undefined): T[] {
  if (!rows?.length) return [];
  const groups = new Map<string, T[]>();
  const order: string[] = [];
  for (const pos of rows) {
    const sym = String(pos.symbol || '').toUpperCase();
    if (!sym) continue;
    if (!groups.has(sym)) {
      groups.set(sym, []);
      order.push(sym);
    }
    groups.get(sym)!.push(pos);
  }
  return order.map((sym) => {
    const copies = groups.get(sym)!;
    const closed = copies.filter((row) => row.closed);
    const opens = copies.filter((row) => !row.closed);
    if (closed.length) {
      const stop = closed.find((row) =>
        String(row.status || row.outcome?.label || '')
          .toUpperCase()
          .includes('STOP HIT'),
      );
      return stop ?? closed[0];
    }
    return opens[opens.length - 1] ?? copies[0];
  });
}

export default function ForensicPanel({
  onSelect,
  liveMarket,
  selectedPool,
  onPoolChange,
  availablePools,
  refreshToken = 0,
}: {
  onSelect?: (ticker: string) => void;
  liveMarket?: MarketDataResponse | null;
  selectedPool?: string;
  onPoolChange?: (pool: string) => void;
  availablePools?: string[];
  /** Bumped by top desk Refresh — reloads swing session MTM. */
  refreshToken?: number;
}) {
  const [swingSession, setSwingSession] = useState<{
    locked?: boolean;
    sessionDate?: string;
    source?: string;
    cashHeld?: boolean;
    cashReason?: string;
    hunting?: boolean;
    selectionFinalized?: boolean;
    huntWindow?: { huntStart?: string; huntEnd?: string };
    entryHuntDiagnostics?: {
      evaluated?: number;
      qualified?: number;
      universeSize?: number | null;
      volumeScreened?: number;
      candleMetrics?: number;
      displayPool?: number;
      crossBookExcluded?: string[];
      swingUniverse?: string;
      topRejectionReasons?: Array<{ reason?: string; count?: number }>;
    };
    long?: Array<{
      symbol?: string;
      entryPrice?: number;
      ltp?: number | null;
      currentPrice?: number | null;
      dayChangePct?: number | null;
      unrealizedPnlPct?: number | null;
      totalPnl?: number | null;
      score?: number | null;
      stopLoss?: number;
      effectiveStop?: number | null;
      target1?: number;
      target2?: number;
      selectionReason?: string | null;
      status?: string | null;
      closed?: boolean;
      outcome?: { label?: string | null } | null;
    }>;
    portfolio?: { realizedPnl?: number; unrealizedPnl?: number; totalPnl?: number; lockedCount?: number };
  } | null>(null);
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState<string | null>(null);
  const [istClock, setIstClock] = useState(() =>
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date()),
  );

  useEffect(() => {
    const id = window.setInterval(() => {
      setIstClock(
        new Intl.DateTimeFormat('en-CA', {
          timeZone: 'Asia/Kolkata',
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
        }).format(new Date()),
      );
    }, 60_000);
    return () => window.clearInterval(id);
  }, []);

  const live = liveMarket ?? null;
  const stocks = live?.stocks ?? [];
  const intelligence = live?.terminalIntelligence ?? null;
  const pools = useMemo(() => {
    const fromApi = (availablePools ?? live?.availablePools ?? []).filter(Boolean);
    const merged = [...fromApi];
    for (const pool of DEFAULT_POOLS) {
      if (!merged.includes(pool)) merged.push(pool);
    }
    if (selectedPool && !merged.includes(selectedPool)) merged.unshift(selectedPool);
    return merged;
  }, [availablePools, live?.availablePools, selectedPool]);

  const stockPriceMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const stock of stocks) {
      map.set(stock.ticker, stock.ltp);
    }
    return map;
  }, [stocks]);

  const stockMetaMap = useMemo(() => {
    const map = new Map<string, { promoterPct?: number; bulkDealValueCr?: number; bulkDealSignal?: boolean }>();
    const quotes = live?.stockQuotes ?? {};
    for (const stock of stocks) {
      const quote = quotes[stock.ticker] ?? stock;
      const promoter = typeof quote.promoter_holding_pct === 'number' ? quote.promoter_holding_pct : undefined;
      const bulkDealValueCr = typeof quote.bulk_deal_value_cr === 'number' ? quote.bulk_deal_value_cr : undefined;
      const bulkDealSignal = typeof quote.bulk_deal_signal === 'boolean' ? quote.bulk_deal_signal : undefined;
      map.set(stock.ticker, { promoterPct: promoter, bulkDealValueCr, bulkDealSignal });
    }
    for (const [ticker, quote] of Object.entries(quotes)) {
      if (!map.has(ticker) && typeof quote.promoter_holding_pct === 'number') {
        map.set(ticker, {
          promoterPct: quote.promoter_holding_pct,
          bulkDealValueCr: quote.bulk_deal_value_cr,
          bulkDealSignal: quote.bulk_deal_signal,
        });
      }
    }
    return map;
  }, [live?.stockQuotes, stocks]);

  const stockByTicker = useMemo(() => {
    const map = new Map<string, StockWithIntraday>();
    const quotes = live?.stockQuotes ?? {};
    for (const stock of stocks) {
      map.set(stock.ticker, { ...stock, ...(quotes[stock.ticker] as StockWithIntraday | undefined) });
    }
    for (const [ticker, quote] of Object.entries(quotes)) {
      if (!map.has(ticker)) {
        map.set(ticker, quote as StockWithIntraday);
      }
    }
    return map;
  }, [live?.stockQuotes, stocks]);

  const dhanPickMap = useMemo(() => {
    const map = new Map<string, DhanSwingPick>();
    const payload = live?.dhanSwingPicks as DhanSwingPicksPayload | undefined;
    for (const p of payload?.picks ?? []) {
      const sym = (p.symbol || '').toUpperCase();
      if (sym) map.set(sym, p);
    }
    return map;
  }, [live?.dhanSwingPicks]);

  const institutionalMode = isInstitutionalMatrixMode();

  const assetRows: AssetRow[] = useMemo(() => {
    const rows: AssetRow[] = [];
    const seen = new Set<string>();
    const marketRisk = intelligence?.active_risk_calc as Record<string, unknown> | undefined;
    const tickerIntelMap = live?.tickerIntelligenceByTicker ?? {};

    const push = (row: AssetRow) => {
      if (!seen.has(row.ticker)) {
        seen.add(row.ticker);
        rows.push(row);
      }
    };

    const enrichFromStock = (
      ticker: string,
      stock: StockWithIntraday | undefined,
      quote: StockWithIntraday | undefined,
    ) => {
      const intraday = stock?.intraday ?? quote?.intraday;
      const passesHardFilters =
        typeof intraday?.passes_hard_filters === 'boolean'
          ? intraday.passes_hard_filters
          : typeof stock?.passes_hard_filters === 'boolean'
            ? stock.passes_hard_filters
            : undefined;
      const passesQualityFilters =
        typeof intraday?.passes_quality_filters === 'boolean'
          ? intraday.passes_quality_filters
          : typeof stock?.passes_quality_filters === 'boolean'
            ? stock.passes_quality_filters
            : undefined;
      return {
        passesHardFilters,
        passesQualityFilters,
        hardFilterReasons: intraday?.hard_filter_reasons ?? [],
        atrPct: typeof intraday?.atr_pct === 'number' ? intraday.atr_pct : undefined,
        dhanPick: dhanPickMap.get(ticker),
      };
    };

    if (intelligence?.ledger_stocks?.length) {
      const sorted = [...intelligence.ledger_stocks].sort(
        (a, b) => (typeof b.score === 'number' ? b.score : 0) - (typeof a.score === 'number' ? a.score : 0)
      );
      for (const rawRow of sorted) {
        const row = rawRow as LedgerStockRow;
        const action = row.action || '';
        const reason = row.selection_reason || action;
        const score = typeof row.score === 'number' ? row.score : 0;
        const stock = stockByTicker.get(row.ticker);
        const quote = live?.stockQuotes?.[row.ticker] as StockWithIntraday | undefined;
        const tickerRiskCalc = tickerIntelMap[row.ticker]?.active_risk_calc as Record<string, unknown> | undefined;
        const riskFlag = resolveRiskFlag({
          ledgerRiskFlag: row.risk_flag,
          tickerRiskCalc,
          stock,
          quote,
          score,
          deltaText: row.delta || row.day_change_pct,
          kellyPolicy: row.policy_allocation_pct,
          marketRisk,
        });
        const enriched = enrichFromStock(row.ticker, stock, quote);
        const rawDayChange = parsePercent(row.delta || row.day_change_pct) || parsePercent(quote?.delta ?? stock?.delta);
        const hasDayChangeField = Boolean(row.delta || row.day_change_pct || quote?.delta || stock?.delta);
        const kellyPolicy = row.policy_allocation_pct?.trim() || undefined;
        const wlFromTicker = tickerRiskCalc?.win_loss_ratio as string | undefined;
        const wlFromMarket = marketRisk?.win_loss_ratio as string | undefined;
        const winLossRatio =
          wlFromTicker && parseWinLossRatio(wlFromTicker) !== null
            ? wlFromTicker
            : wlFromMarket && parseWinLossRatio(wlFromMarket) !== null
              ? wlFromMarket
              : undefined;
        const deskIcDecision =
          stock?.deskIcSummary?.deskDecision ||
          live?.deskIcByTicker?.[row.ticker]?.deskDecision ||
          undefined;
        push({
          ticker: row.ticker,
          price: row.live_price || stockPriceMap.get(row.ticker) || '',
          score,
          scoreScale: 'angel',
          kellyPolicy,
          winLossRatio,
          dayChangePct: hasDayChangeField ? rawDayChange : null,
          thesis: reason || 'Score-based selection',
          action: action || undefined,
          riskFlag,
          passesHardFilters: enriched.passesHardFilters,
          passesQualityFilters: enriched.passesQualityFilters,
          hardFilterReasons: enriched.hardFilterReasons,
          isVolumePad: isVolumePadStock(stock),
          isMetaRow: false,
          state: score >= SCORE_STRONG ? 'HIGH' : score <= SCORE_WEAK ? 'LOW' : undefined,
          promoterPct: stockMetaMap.get(row.ticker)?.promoterPct,
          bulkDealValueCr: stockMetaMap.get(row.ticker)?.bulkDealValueCr,
          bulkDealSignal: stockMetaMap.get(row.ticker)?.bulkDealSignal,
          dhanPick: enriched.dhanPick,
          hasQuantSource: true,
          atrPct: enriched.atrPct,
          deskIcDecision,
        });
      }
    }

    if (!intelligence?.ledger_stocks?.length && stocks.length) {
      const sortedStocks = [...stocks].sort(
        (a, b) => (typeof b.score === 'number' ? b.score : 0) - (typeof a.score === 'number' ? a.score : 0),
      );
      for (const stock of sortedStocks) {
        const quote = live?.stockQuotes?.[stock.ticker] as StockWithIntraday | undefined;
        const merged = stockByTicker.get(stock.ticker) ?? ({ ...stock, ...quote } as StockWithIntraday);
        const score = typeof stock.score === 'number' ? stock.score : 0;
        const enriched = enrichFromStock(stock.ticker, merged, quote);
        const riskFlag = resolveRiskFlag({
          stock: merged,
          quote,
          score,
          deltaText: stock.delta,
          marketRisk,
        });
        push({
          ticker: stock.ticker,
          price: stock.ltp || stockPriceMap.get(stock.ticker) || '',
          score,
          scoreScale: 'angel',
          dayChangePct: parsePercent(stock.delta),
          thesis: 'Quant-ranked from live universe',
          riskFlag,
          passesHardFilters: enriched.passesHardFilters,
          passesQualityFilters: enriched.passesQualityFilters,
          hardFilterReasons: enriched.hardFilterReasons,
          isVolumePad: isVolumePadStock(merged),
          isMetaRow: false,
          state: score >= SCORE_STRONG ? 'HIGH' : score <= SCORE_WEAK ? 'LOW' : undefined,
          promoterPct: stockMetaMap.get(stock.ticker)?.promoterPct,
          bulkDealValueCr: stockMetaMap.get(stock.ticker)?.bulkDealValueCr,
          bulkDealSignal: stockMetaMap.get(stock.ticker)?.bulkDealSignal,
          dhanPick: enriched.dhanPick,
          hasQuantSource: true,
          atrPct: enriched.atrPct,
          deskIcDecision:
            stock.deskIcSummary?.deskDecision ||
            live?.deskIcByTicker?.[stock.ticker]?.deskDecision ||
            undefined,
        });
      }
    }

    for (const [sym, pick] of dhanPickMap) {
      if (seen.has(sym)) {
        const existing = rows.find((r) => r.ticker === sym);
        if (existing && !existing.dhanPick) existing.dhanPick = pick;
        continue;
      }
      const stock = stockByTicker.get(sym);
      const score = typeof stock?.score === 'number' ? stock.score : 0;
      if (score < SCORE_STRONG) continue;
      const quote = live?.stockQuotes?.[sym] as StockWithIntraday | undefined;
      const merged = stock ?? quote;
      const enriched = enrichFromStock(sym, merged, quote);
      push({
        ticker: sym,
        price: String(pick.scanLtp ?? pick.buyAbove ?? stock?.ltp ?? stockPriceMap.get(sym) ?? ''),
        score,
        scoreScale: 'angel',
        dayChangePct: merged ? parsePercent(merged.delta) : null,
        thesis: pick.reasons?.join(' · ') || 'Dhan ScanX swing confluence',
        action: 'BUY',
        riskFlag: resolveRiskFlag({ stock: merged, quote, score, marketRisk }),
        passesHardFilters: enriched.passesHardFilters,
        passesQualityFilters: enriched.passesQualityFilters,
        hardFilterReasons: enriched.hardFilterReasons,
        isVolumePad: isVolumePadStock(merged),
        isMetaRow: false,
        state: score >= SCORE_STRONG ? 'HIGH' : undefined,
        promoterPct: stockMetaMap.get(sym)?.promoterPct,
        bulkDealValueCr: stockMetaMap.get(sym)?.bulkDealValueCr,
        bulkDealSignal: stockMetaMap.get(sym)?.bulkDealSignal,
        dhanPick: pick,
        hasQuantSource: true,
        atrPct: enriched.atrPct,
      });
    }

    if (intelligence?.active_factor_hub) {
      const hub = intelligence.active_factor_hub;
      if (hub.thesis) {
        push({
          ticker: 'Ledger Thesis',
          price: '',
          score: 0,
          scoreScale: 'unknown',
          dayChangePct: null,
          thesis: hub.thesis,
          riskFlag: '',
          isVolumePad: false,
          isMetaRow: true,
          hasQuantSource: false,
        });
      }
      if (hub.risk_flag) {
        push({
          ticker: 'Ledger Risk',
          price: '',
          score: 0,
          scoreScale: 'unknown',
          dayChangePct: null,
          thesis: '',
          riskFlag: hub.risk_flag,
          state: 'HIGH',
          isVolumePad: false,
          isMetaRow: true,
          hasQuantSource: false,
        });
      }
    }

    return rows;
  }, [
    intelligence,
    stocks,
    stockMetaMap,
    stockByTicker,
    stockPriceMap,
    live?.stockQuotes,
    live?.tickerIntelligenceByTicker,
    dhanPickMap,
  ]);

  /* Per-ticker flag state (default 1M) */
  const [tickerFlags, setTickerFlags] = useState<Record<string, SparkFlag>>({});
  const getFlag = (ticker: string): SparkFlag => tickerFlags[ticker] ?? '1D';
  const setFlag = (ticker: string, flag: SparkFlag) => setTickerFlags((prev) => ({ ...prev, [ticker]: flag }));

  /* Collect unique flags in use for fetching */
  const activeFlags = useMemo(() => {
    const flags = new Set<SparkFlag>();
    for (const r of assetRows) flags.add(getFlag(r.ticker));
    return [...flags];
  }, [assetRows, tickerFlags]);

  /* Fetch sparkline data for all tickers x all active flags */
  const candidateTickerList = useMemo(
    () => assetRows.filter((row) => !row.isMetaRow).map((r) => r.ticker),
    [assetRows],
  );

  const poolHasHardFilterPasses = useMemo(
    () =>
      assetRows.some(
        (row) => !row.isMetaRow && row.passesHardFilters === true,
      ),
    [assetRows],
  );

  const isSnapshotFallback = live?.isSnapshotFallback ?? false;
  const selectionMetaMode = live?.selectionMeta?.mode;
  const institutionalOffHours = isInstitutionalOffHoursContext({
    isSnapshotFallback,
    poolHasHardFilterPasses,
    selectionMetaMode,
  });

  const trendlyneTickerList = useMemo(() => {
    const stockRows = assetRows.filter((row) => !row.isMetaRow);
    const byScore = [...stockRows].sort((a, b) => b.score - a.score);
    if (!institutionalMode) return byScore.map((row) => row.ticker);
    const strong = byScore.filter((row) => row.score >= SCORE_STRONG);
    const rest = byScore.filter((row) => row.score < SCORE_STRONG);
    return [...strong, ...rest].map((row) => row.ticker);
  }, [assetRows, institutionalMode]);

  const trendlyneMaxCards = useMemo(() => {
    if (!institutionalMode) return MAX_TRENDLYNE_CARDS;
    const strongCount = assetRows.filter(
      (row) => !row.isMetaRow && row.score >= SCORE_STRONG,
    ).length;
    return Math.min(assetRows.length, Math.max(MAX_TRENDLYNE_CARDS, strongCount + 4));
  }, [assetRows, institutionalMode]);

  const trendlyneSummaries = useTrendlyneSummaries(trendlyneTickerList, trendlyneMaxCards);
  const tickerNewsMap = live?.tickerNewsByTicker ?? {};
  const tickerIntelMap = live?.tickerIntelligenceByTicker ?? {};

  const displayRows: MatrixCardRow[] = useMemo(() => {
    const stockRows = assetRows.filter((row) => !row.isMetaRow);

    const evaluated = stockRows.map((row) => {
      const convictionInput = {
        score: row.score,
        riskFlag: row.riskFlag,
        action: row.action,
        passesHardFilters: row.passesHardFilters,
        passesQualityFilters: row.passesQualityFilters,
        isVolumePad: row.isVolumePad,
        winLossRatio: row.winLossRatio,
        scoreScale: row.scoreScale,
        hasDhanSignal: Boolean(row.dhanPick),
      };
      const intelligence = mergeIntelligenceSummary(
        tickerIntelMap[row.ticker],
        tickerNewsMap[row.ticker],
        trendlyneSummaries[row.ticker],
      );
      const evaluation = evaluateMatrixBuyCandidate(convictionInput, intelligence, {
        dhanPick: row.dhanPick,
        atrPct: row.atrPct,
        institutional: institutionalMode,
        isSnapshotFallback,
        poolHasHardFilterPasses,
        selectionMetaMode,
        hardFilterReasons: row.hardFilterReasons,
      });
      return { row, ...evaluation, intelligence };
    });

    return selectMatrixDisplayRows(evaluated, stockRows.length, institutionalMode);
  }, [assetRows, tickerIntelMap, tickerNewsMap, trendlyneSummaries, institutionalMode, isSnapshotFallback, poolHasHardFilterPasses, selectionMetaMode]);

  const istToday = istClock;

  useEffect(() => {
    let cancelled = false;
    const unsubscribe = subscribeLiveDesk((snapshot) => {
      if (!cancelled) setSwingSession(snapshot['swing-session'] as typeof swingSession);
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [istToday]);

  useEffect(() => {
    if (refreshToken > 0) void fetchLiveDeskSnapshot(true);
  }, [refreshToken]);

  const lockedSwingMode = Boolean(
    swingSession?.locked &&
      String(swingSession?.sessionDate || '').slice(0, 10) === istToday &&
      (swingSession?.long?.length ?? 0) > 0,
  );
  const todaySwingEmpty = Boolean(
    String(swingSession?.sessionDate || '').slice(0, 10) === istToday &&
      (swingSession?.long?.length ?? 0) === 0 &&
      !lockedSwingMode,
  );
  const huntingSwing = Boolean(
    todaySwingEmpty &&
      (swingSession?.hunting || swingSession?.cashReason === 'WAITING_FOR_QUALIFIED_BUY_ENTRY'),
  );
  const cashHeldSwing = Boolean(
    todaySwingEmpty &&
      !huntingSwing &&
      (swingSession?.cashHeld ||
        Boolean(swingSession?.cashReason) ||
        swingSession?.selectionFinalized),
  );
  const staleSwingLock = Boolean(
    swingSession?.locked &&
      String(swingSession?.sessionDate || '').slice(0, 10) &&
      String(swingSession?.sessionDate || '').slice(0, 10) !== istToday,
  );
  const swingPortfolioPnl = swingSession?.portfolio?.totalPnl ?? swingSession?.portfolio?.unrealizedPnl;

  const onLockSwing = async (force: boolean) => {
    setLocking(true);
    setLockError(null);
    try {
      const res = await fetch(`/api/swing-session/lock?force=${force ? 'true' : 'false'}`, {
        method: 'POST',
        cache: 'no-store',
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || body?.success === false) {
        setLockError(String(body?.error || body?.detail || `Lock failed (${res.status})`));
      } else if (body?.session) {
        setSwingSession(body.session);
      } else {
        const reload = await fetch('/api/swing-session?live=1', { cache: 'no-store' });
        if (reload.ok) setSwingSession(await reload.json());
      }
    } catch (err) {
      setLockError(err instanceof Error ? err.message : 'Lock failed');
    } finally {
      setLocking(false);
    }
  };

  const portfolioDisplayRows: MatrixCardRow[] = useMemo(() => {
    if (huntingSwing || cashHeldSwing) return [];
    if (!lockedSwingMode || !swingSession?.long?.length) return displayRows;
    const byTicker = new Map(displayRows.map((item) => [item.row.ticker.toUpperCase(), item]));
    return uniqueSwingLongPositions(swingSession.long)
      .map((pos) => {
        const sym = String(pos.symbol || '').toUpperCase();
        if (!sym) return null;
        const existing = byTicker.get(sym);
        const ltp = pos.ltp ?? pos.currentPrice ?? pos.entryPrice;
        const dayPct =
          typeof pos.dayChangePct === 'number'
            ? pos.dayChangePct
            : typeof pos.unrealizedPnlPct === 'number'
              ? pos.unrealizedPnlPct
              : existing?.row.dayChangePct ?? null;
        const row: AssetRow = existing
          ? {
              ...existing.row,
              price: ltp != null ? String(ltp) : existing.row.price,
              dayChangePct: dayPct,
              thesis: existing.row.thesis || pos.selectionReason || 'Locked swing book',
              riskFlag: pos.closed
                ? String(pos.status || pos.outcome?.label || 'CLOSED')
                : pos.status && String(pos.status).toUpperCase() !== 'RUNNING'
                  ? String(pos.status)
                  : existing.row.riskFlag,
              dhanPick: {
                ...(existing.row.dhanPick || { symbol: sym }),
                symbol: sym,
                buyAbove: pos.entryPrice ?? existing.row.dhanPick?.buyAbove,
                stopLoss: pos.effectiveStop ?? pos.stopLoss ?? existing.row.dhanPick?.stopLoss,
                target1: pos.target1 ?? existing.row.dhanPick?.target1,
                target2: pos.target2 ?? existing.row.dhanPick?.target2,
              } as DhanSwingPick,
            }
          : {
              ticker: sym,
              price: ltp != null ? String(ltp) : '',
              score: Number(pos.score || 0),
              scoreScale: 'angel',
              dayChangePct: dayPct,
              thesis: pos.selectionReason || 'Locked Asset Matrix swing',
              action: 'BUY',
              riskFlag: pos.closed
                ? String(pos.status || pos.outcome?.label || 'CLOSED')
                : pos.status && String(pos.status).toUpperCase() !== 'RUNNING'
                  ? String(pos.status)
                  : 'SELECTED',
              isVolumePad: false,
              isMetaRow: false,
              hasQuantSource: true,
              dhanPick: {
                symbol: sym,
                buyAbove: pos.entryPrice,
                stopLoss: pos.effectiveStop ?? pos.stopLoss,
                target1: pos.target1,
                target2: pos.target2,
              } as DhanSwingPick,
            };
        return {
          row,
          tier: existing?.tier ?? ('CORE' as ConvictionTier),
          reason: existing?.reason ?? 'LOCKED · live Book P&L',
          winEdge: existing?.winEdge ?? null,
          intelligence: existing?.intelligence ?? mergeIntelligenceSummary(
            tickerIntelMap[sym],
            tickerNewsMap[sym],
            trendlyneSummaries[sym],
          ),
        } satisfies MatrixCardRow;
      })
      .filter((x): x is MatrixCardRow => x != null);
  }, [cashHeldSwing, displayRows, huntingSwing, lockedSwingMode, swingSession, tickerIntelMap, tickerNewsMap, trendlyneSummaries]);

  const tickerList = useMemo(
    () => portfolioDisplayRows.map((item) => item.row.ticker),
    [portfolioDisplayRows],
  );

  const stockSparklines1M = useStockSparklines(tickerList, '1M');
  const stockSparklines1D = useStockSparklines(tickerList, '1D');
  const stockSparklines1Y = useStockSparklines(tickerList, '1Y');

  /* Merge into one lookup: ticker -> flag -> number[] */
  const allSparklines = useMemo(() => {
    const merged: Record<string, Record<SparkFlag, number[]>> = {};
    for (const t of tickerList) {
      merged[t] = {
        '1D': stockSparklines1D[t]?.['1D'] ?? [],
        '1M': stockSparklines1M[t]?.['1M'] ?? [],
        '1Y': stockSparklines1Y[t]?.['1Y'] ?? [],
      };
    }
    return merged;
  }, [tickerList, stockSparklines1D, stockSparklines1M, stockSparklines1Y]);

  const flagClass = (flag: string) => {
    const v = flag.toLowerCase();
    if (v.includes('extreme')) return 'text-white border-red-700 bg-red-600 animate-pulse font-black';
    if (v.includes('low_risk') || v === 'low') return 'text-teal-700 border-teal-200 bg-teal-50';
    if (v.includes('moderate_risk') || v.includes('moderate')) return 'text-amber-700 border-amber-200 bg-amber-50';
    if (v.includes('high_risk') || v.includes('structural')) return 'text-red-700 border-red-200 bg-red-50';
    if (v.includes('volume_fill')) return 'text-slate-600 border-slate-300 bg-slate-100';
    if (v.includes('unrated')) return 'text-slate-500 border-slate-200 bg-slate-50';
    if (v.includes('selected') || v === 'buy') return 'text-slate-400 border-slate-200 bg-slate-50';
    return 'text-slate-600 border-slate-200 bg-slate-50';
  };

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-3 sm:p-4 shadow-sm relative overflow-hidden min-w-0">
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-teal-400 via-cyan-400 to-transparent pointer-events-none" aria-hidden />
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
        <div className="min-w-0">
          <h3 className="desk-panel-title text-emerald-700">SWING PORTFOLIO</h3>
          <p className="text-slate-500 text-[12px] mt-0.5">
            {lockedSwingMode ? (
              <>
                <span className="inline-flex items-center rounded border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-emerald-800">
                  LOCKED · {swingSession?.sessionDate}
                </span>
                {' · '}live Book P&amp;L · auto SL/trail · {swingSession?.source || 'asset_matrix_buy'} ·{' '}
                {portfolioDisplayRows.length} names
                {typeof swingPortfolioPnl === 'number' && (
                  <>
                    {' · '}P&amp;L{' '}
                    <span className={swingPortfolioPnl >= 0 ? 'text-emerald-600 font-bold' : 'text-red-600 font-bold'}>
                      {swingPortfolioPnl >= 0 ? '+' : ''}
                      ₹{swingPortfolioPnl.toFixed(0)}
                    </span>
                  </>
                )}
              </>
            ) : huntingSwing ? (
              <>
                <span className="inline-flex items-center rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-amber-800">
                  HUNTING · {swingSession?.sessionDate}
                </span>
                {' · '}
                {swingSession?.cashReason || 'WAITING_FOR_QUALIFIED_BUY_ENTRY'}
                {' · '}lock when a fully qualified BUY appears
                {swingSession?.huntWindow?.huntStart && swingSession?.huntWindow?.huntEnd
                  ? ` · ${swingSession.huntWindow.huntStart}–${swingSession.huntWindow.huntEnd} IST`
                  : ' · 09:45–14:45 IST'}
              </>
            ) : cashHeldSwing ? (
              <>
                <span className="inline-flex items-center rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-slate-700">
                  CASH HELD · {swingSession?.sessionDate}
                </span>
                {' · '}
                {swingSession?.cashReason || 'NO_ACTIVE_VALID_SWING_SELECTIONS'}
                {' · '}entry hunt closed — no qualified BUY locked
              </>
            ) : staleSwingLock ? (
              <>
                <span className="inline-flex items-center rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-amber-800">
                  STALE · {swingSession?.sessionDate}
                </span>
                {' · '}prior-day lock — rotate to today Matrix BUY
              </>
            ) : institutionalMode
              ? institutionalOffHours
                ? `Institutional ₹1cr+ book — off-hours snapshot: score ≥ ${SCORE_STRONG}, Trendlyne confirm, LOW/MODERATE risk (volume gates rank-penalized)`
                : `Institutional ₹1cr+ book — score ≥ ${SCORE_STRONG}, Trendlyne confirm, Dhan R:R ≥2 when live`
              : live?.poolDescription || `Top ${MATRIX_BUY_MIN_DISPLAY}+ high-probability BUY setups — score ≥ ${MATRIX_BUY_MIN_SCORE}, CORE preferred`}
            {!lockedSwingMode && !staleSwingLock && typeof live?.universeSize === 'number' && live.universeSize > 0 && (
              <> · Universe {live.universeSize}</>
            )}
            {!lockedSwingMode && !staleSwingLock && typeof live?.volumeScreenedCount === 'number' && live.volumeScreenedCount > 0 && (
              <> · Top {live.volumeScreenedCount} by volume screened</>
            )}
            {!lockedSwingMode && !staleSwingLock && dhanPickMap.size > 0 && (
              <> · Dhan LONG {dhanPickMap.size}</>
            )}
            {!lockedSwingMode && !staleSwingLock && !huntingSwing && !cashHeldSwing && (
              <>
                {' · '}BUY Picks {displayRows.length}
                {institutionalMode && <> · max {INSTITUTIONAL_MATRIX_TOP_N}</>}
              </>
            )}
            {huntingSwing && (
              <>
                {' · '}Hunt {swingSession?.entryHuntDiagnostics?.qualified ?? 0}/
                {swingSession?.entryHuntDiagnostics?.evaluated ?? '—'} qualified
                {typeof swingSession?.entryHuntDiagnostics?.candleMetrics === 'number' &&
                  typeof swingSession?.entryHuntDiagnostics?.universeSize === 'number' && (
                    <>
                      {' · '}candles {swingSession.entryHuntDiagnostics.candleMetrics}/
                      {swingSession.entryHuntDiagnostics.universeSize}
                    </>
                  )}
                {swingSession?.entryHuntDiagnostics?.swingUniverse
                  ? ` · ${swingSession.entryHuntDiagnostics.swingUniverse}`
                  : ' · Nifty 500'}
              </>
            )}
            {' · '}Data Date {live?.selectionMeta?.dataDate || '—'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {onPoolChange && (
            <label className="flex items-center gap-1.5 min-w-0">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Pool</span>
              <select
                value={selectedPool ?? pools[0] ?? 'Nifty 500'}
                onChange={(e) => onPoolChange(e.target.value)}
                className="min-h-11 max-w-[min(100%,14rem)] px-2.5 py-2 text-[11px] rounded-lg bg-white border border-slate-200 text-slate-700 font-semibold hover:border-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-200 cursor-pointer"
              >
                {pools.map((pool) => (
                  <option key={pool} value={pool}>
                    {pool}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!lockedSwingMode && !cashHeldSwing && (
            <button
              type="button"
              disabled={locking}
              onClick={() => void onLockSwing(staleSwingLock)}
              className="min-h-11 px-3 py-2 text-[11px] rounded-lg bg-emerald-600 text-white font-bold uppercase tracking-wider hover:bg-emerald-700 disabled:opacity-50"
              title={staleSwingLock ? 'Force rotate stale swing lock to today Matrix BUY' : 'Lock today Asset Matrix BUY set'}
            >
              {locking ? 'Locking…' : staleSwingLock ? 'Rotate swing today' : 'Lock swing today'}
            </button>
          )}
        </div>
      </div>
      {lockError && (
        <p className="mb-2 text-[10px] text-red-600">{lockError}</p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
        {portfolioDisplayRows.map((item) => {
          const row = item.row;
          const rawPrice = Number(String(row.price ?? '').replace(/[₹,\s]/g, ''));
          const priceVal = Number.isFinite(rawPrice)
            ? `₹${rawPrice.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : '-';
          const flag = getFlag(row.ticker);
          const sparkData = allSparklines[row.ticker]?.[flag];
          const period = sparkPeriodChange(sparkData);
          const priceNum = Number(String(priceVal).replace(/[₹,\s]/g, ''));
          const dayPct =
            row.dayChangePct !== null
              ? {
                  pct: row.dayChangePct,
                  positive: row.dayChangePct >= 0,
                  label: formatPtsPctLabel(
                    Number.isFinite(priceNum) ? priceNum : null,
                    row.dayChangePct,
                  ),
                }
              : null;
          const displayChange = period ?? dayPct;
          const intelligence = item.intelligence;
          const { tier, reason } = item;
          const styles = convictionTierStyles(tier);
          const winEdge = item.winEdge;
          const badgeLabel = convictionTierBadgeLabel(tier);
          const showKelly = row.kellyPolicy && parsePercentValue(row.kellyPolicy) !== null;
          const showWl = row.winLossRatio && parseWinLossRatio(row.winLossRatio) !== null;
          const showTrendlyneHint = !intelligence.hasTrendlyneData;
          const sourceChips = buildMatrixSourceChips(
            row.hasQuantSource && row.scoreScale === 'angel',
            Boolean(row.dhanPick),
            intelligence.hasTrendlyneData,
          );
          const dhanRr = row.dhanPick ? dhanRrValue(row.dhanPick) : null;
          const rrEstimate = !dhanRr ? estimateStructuralRr(row.atrPct) : null;
          const entryPx = row.dhanPick?.buyAbove ?? parseFloat(String(row.price).replace(/[^\d.]/g, ''));
          const stopPx = row.dhanPick?.stopLoss;
          const sizingHint =
            institutionalMode && entryPx > 0
              ? computeInstitutionalSizingHint(entryPx, stopPx, row.kellyPolicy)
              : null;

          return (
            <DeskCardTilt
              key={row.ticker}
              onClick={() => onSelect?.(row.ticker)}
              className="glass-card relative overflow-hidden p-2.5 group cursor-pointer"
              style={{ borderLeft: `3px solid ${styles.border}`, '--tile-accent': styles.border } as React.CSSProperties}
              role="button"
              tabIndex={0}
              aria-label={`Open analysis for ${row.ticker}`}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect?.(row.ticker);
                }
              }}
            >
              <div
                className="absolute -top-4 -right-4 w-12 h-12 rounded-full opacity-15 blur-2xl pointer-events-none"
                style={{ backgroundColor: styles.glow }}
                aria-hidden
              />

              {/* Header: ticker + conviction tier + win edge */}
              <div className="flex items-center justify-between gap-2 mb-1 relative z-10">
                <span className="desk-metric-value font-mono truncate">{row.ticker}</span>
                <div className="flex items-center gap-1 shrink-0">
                  {winEdge && (
                    <span
                      className={`inline-block border px-1.5 py-0.5 rounded-md text-[10px] sm:text-[8px] whitespace-nowrap font-bold tabular-nums ${
                        winEdge.kind === 'win_edge'
                          ? 'text-indigo-700 bg-indigo-50 border-indigo-200'
                          : 'text-slate-600 bg-slate-50 border-slate-200'
                      }`}
                      title={winEdge.source}
                    >
                      {winEdge.display}
                    </span>
                  )}
                  <span
                    className={`inline-block border px-2 py-0.5 rounded-md text-[10px] whitespace-nowrap font-black uppercase tracking-wide ${styles.badge}`}
                  >
                    {badgeLabel}
                  </span>
                </div>
              </div>

              {/* Price + day/period change */}
              <div className="flex items-baseline gap-1.5 mb-1.5 relative z-10">
                <LiveTickNumber value={priceVal} className="desk-metric-value" />
                {displayChange && (
                  <LiveTickNumber
                    value={displayChange.label}
                    className={`text-[11px] font-bold ${displayChange.positive ? 'text-emerald-600' : 'text-red-500'}`}
                  />
                )}
                {displayChange && !period && dayPct ? (
                  <span className="text-[10px] text-slate-400">today</span>
                ) : null}
              </div>

              {/* Full-width chart band + timeframe pills */}
              <SparklineFlagSlider
                ticker={row.ticker}
                sparklines={allSparklines[row.ticker] ?? ({} as Record<SparkFlag, number[]>)}
                currentFlag={flag}
                onFlagChange={(f) => setFlag(row.ticker, f)}
              />

              {/* Core: strength meter + risk badge */}
              <div className="flex items-center justify-between gap-2 mt-1 relative z-10 flex-wrap">
                <StrengthMeter score={row.score} />
                <div className="flex items-center gap-1 flex-wrap justify-end">
                  {row.riskFlag && !row.isVolumePad && !row.riskFlag.toUpperCase().includes('VOLUME_FILL') && (
                    <span className={`inline-block border px-1.5 py-0.5 rounded text-[9px] whitespace-nowrap font-black uppercase ${flagClass(row.riskFlag)}`}>
                      {row.riskFlag}
                    </span>
                  )}
                </div>
              </div>

              <div className="desk-card-disclose relative z-10">
                <div className="desk-card-disclose-inner">
                  <p className="text-[10px] leading-snug text-slate-600 mb-1 line-clamp-2 pt-1">
                    {reason}
                  </p>

                  {sourceChips.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-1">
                      {sourceChips.map((chip) => (
                        <span
                          key={`${row.ticker}-src-${chip.label}`}
                          className={`inline-flex items-center border px-1.5 py-0.5 rounded text-[10px] sm:text-[7px] font-black uppercase tracking-wider ${matrixSourceChipClass(chip.label, chip.active)}`}
                        >
                          {chip.label}
                        </span>
                      ))}
                    </div>
                  )}

                  {intelligence.chips.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-1">
                      {intelligence.chips.map((chip) => (
                        <span
                          key={`${row.ticker}-${chip.label}`}
                          className={`inline-flex items-center border px-1.5 py-0.5 rounded text-[10px] sm:text-[8px] font-bold uppercase tracking-wide ${chipToneClass(chip.tone)}`}
                        >
                          {chip.label}
                        </span>
                      ))}
                    </div>
                  )}
                  {showTrendlyneHint && intelligence.chips.length === 0 && (
                    <p className="text-[10px] sm:text-[8px] text-slate-400 mb-1">
                      Open card for full Trendlyne analysis
                    </p>
                  )}

                  {(row.deskIcDecision && ['REJECT', 'HOLD_FOR_DATA', 'APPROVE'].includes(String(row.deskIcDecision).toUpperCase())) && (
                    <div className="flex items-center gap-1 flex-wrap mb-1">
                      {row.deskIcDecision && String(row.deskIcDecision).toUpperCase() === 'REJECT' && (
                        <IcStatusChip
                          status="REJECT"
                          className="inline-block border border-red-200 bg-red-50 text-red-700 px-1.5 py-0.5 rounded text-[9px] whitespace-nowrap font-black uppercase"
                        >
                          Desk IC REJECT
                        </IcStatusChip>
                      )}
                      {row.deskIcDecision && String(row.deskIcDecision).toUpperCase() === 'HOLD_FOR_DATA' && (
                        <IcStatusChip
                          status="HOLD"
                          className="inline-block border border-amber-200 bg-amber-50 text-amber-800 px-1.5 py-0.5 rounded text-[9px] whitespace-nowrap font-black uppercase"
                        >
                          Desk IC HOLD
                        </IcStatusChip>
                      )}
                      {row.deskIcDecision && String(row.deskIcDecision).toUpperCase() === 'APPROVE' && (
                        <IcStatusChip
                          status="APPROVE"
                          className="inline-block border border-emerald-200 bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded text-[9px] whitespace-nowrap font-black uppercase"
                        >
                          Desk IC PASS
                        </IcStatusChip>
                      )}
                    </div>
                  )}

                  {(showKelly || showWl || dhanRr !== null || rrEstimate) && (
                    <div className="flex items-center gap-1.5 text-[9px] text-slate-400 tabular-nums flex-wrap">
                      {dhanRr !== null && (
                        <span>
                          R:R <span className="font-semibold text-violet-700">{dhanRr.toFixed(1)}:1</span>
                          <span className="text-violet-400"> DHAN</span>
                        </span>
                      )}
                      {dhanRr === null && rrEstimate && (
                        <span className="text-slate-500">{rrEstimate.display}</span>
                      )}
                      {showKelly && (
                        <span>
                          Alloc <span className="font-semibold text-slate-600">{row.kellyPolicy}</span>
                        </span>
                      )}
                      {showKelly && showWl && <span className="text-slate-500">·</span>}
                      {showWl && (
                        <span>
                          W/L <span className="font-semibold text-slate-600">{row.winLossRatio}</span>
                        </span>
                      )}
                    </div>
                  )}

                  {sizingHint && (
                    <p className="text-[9px] text-slate-500 mt-0.5 tabular-nums" title={sizingHint.source}>
                      {sizingHint.display}
                    </p>
                  )}

                  {(typeof row.promoterPct === 'number' || (typeof row.bulkDealValueCr === 'number' && row.bulkDealValueCr > 0)) && (
                    <div className="flex items-center gap-1.5 mt-1 text-[9px] text-slate-400 tabular-nums flex-wrap">
                      {typeof row.promoterPct === 'number' && (
                        <span>
                          Promoter{' '}
                          <span className={`font-semibold ${row.promoterPct >= 60 ? 'text-emerald-600' : 'text-amber-600'}`}>
                            {row.promoterPct.toFixed(1)}%
                          </span>
                        </span>
                      )}
                      {typeof row.promoterPct === 'number' && typeof row.bulkDealValueCr === 'number' && row.bulkDealValueCr > 0 && (
                        <span className="text-slate-500">·</span>
                      )}
                      {typeof row.bulkDealValueCr === 'number' && row.bulkDealValueCr > 0 && (
                        <span>
                          Bulk{' '}
                          <span className={`font-semibold ${row.bulkDealSignal ? 'text-emerald-600' : 'text-slate-500'}`}>
                            {row.bulkDealValueCr.toFixed(1)} Cr
                          </span>
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </DeskCardTilt>
          );
        })}
        {!portfolioDisplayRows.length && (huntingSwing || cashHeldSwing) && (
          <div className="col-span-full space-y-3 py-2">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {[
                ['Universe', swingSession?.entryHuntDiagnostics?.universeSize ?? '—'],
                ['Hunt pool', swingSession?.entryHuntDiagnostics?.swingUniverse ?? 'Nifty 500'],
                ['Candles', swingSession?.entryHuntDiagnostics?.candleMetrics ?? '—'],
                ['Evaluated', swingSession?.entryHuntDiagnostics?.evaluated ?? '—'],
                ['Qualified BUY', swingSession?.entryHuntDiagnostics?.qualified ?? 0],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-lg border border-slate-200 bg-white/80 px-3 py-2">
                  <div className="desk-panel-title text-slate-500">{label}</div>
                  <div className="desk-metric-value text-slate-900 tabular-nums">{value}</div>
                </div>
              ))}
            </div>
            <p className="text-slate-700 text-[13px] font-semibold">
              {huntingSwing
                ? `Hunt open — ${swingSession?.entryHuntDiagnostics?.qualified ?? 0}/${swingSession?.entryHuntDiagnostics?.evaluated ?? '—'} qualified BUY`
                : `Hunt closed — ${swingSession?.cashReason || 'NO_FULLY_QUALIFIED_EXPLICIT_BUY_CANDIDATES'}`}
              {typeof swingSession?.entryHuntDiagnostics?.displayPool === 'number'
                ? ` · matrix display ${swingSession.entryHuntDiagnostics.displayPool}`
                : ''}
            </p>
            {(swingSession?.entryHuntDiagnostics?.topRejectionReasons?.length ?? 0) > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {(swingSession?.entryHuntDiagnostics?.topRejectionReasons ?? []).slice(0, 8).map((item) => (
                  <span
                    key={`${item.reason}-${item.count}`}
                    className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900"
                  >
                    {item.reason || '—'} {item.count ?? 0}
                  </span>
                ))}
              </div>
            )}
            {(swingSession?.entryHuntDiagnostics?.crossBookExcluded?.length ?? 0) > 0 && (
              <p className="text-[11px] text-slate-500">
                Cross-book excluded{' '}
                {(swingSession?.entryHuntDiagnostics?.crossBookExcluded ?? []).join(' · ')}
              </p>
            )}
          </div>
        )}
        {!portfolioDisplayRows.length && !huntingSwing && !cashHeldSwing && (
          <div className="col-span-full py-8 text-center">
            <p className="text-slate-700 text-[13px] font-semibold">
              {institutionalMode
                ? institutionalOffHours
                  ? 'No off-hours institutional BUY setups pass quant + Trendlyne gates'
                  : 'No institutional-grade BUY setups pass all gates'
                : 'No high-probability BUY setups right now'}
            </p>
            <p className="text-slate-500 text-[11px] mt-1">
              {institutionalMode
                ? institutionalOffHours
                  ? `Off-hours / snapshot mode: intraday volume gates are rank-penalized (0/${assetRows.filter((r) => !r.isMetaRow).length} hard-filter passers in pool). Still requires quant score ≥ ${SCORE_STRONG}, Trendlyne confirm, LOW/MODERATE risk, and Dhan R:R ≥2 or ATR-based estimate. No filler names — refresh after market open for live volume confirms.`
                  : `₹1cr+ book requires quant score ≥ ${SCORE_STRONG}, hard+quality filters, Trendlyne confirm (checklist ≥70% preferred), LOW/MODERATE risk, and Dhan R:R ≥2 when in Dhan LONG set. No filler names — refresh after market open.`
                : `Up to ${MATRIX_BUY_TOP_N} picks from the ranked pool. At least ${MATRIX_BUY_MIN_DISPLAY} shown when enough CORE setups exist; otherwise best hard-filter passers (score ≥ ${SCORE_MODERATE}) fill the floor. Refresh after market open for live confirms.`}
            </p>
          </div>
        )}
      </div>

      <style>{`
        @keyframes sparkline-draw {
          from { stroke-dashoffset: 300; }
          to { stroke-dashoffset: 0; }
        }
        .sparkline-draw {
          animation: sparkline-draw 1.2s ease-out forwards;
        }
        @keyframes sparkline-fade-in {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </section>
  );
}
