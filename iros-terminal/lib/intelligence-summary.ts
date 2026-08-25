import type { AITickerNewsReport, DhanSwingPick, TerminalIntelligence } from '@/lib/market-api';

export type { DhanSwingPick };

/** Fund-house conviction tiers for Asset Matrix swing candidates (no reject verdict). */
export type ConvictionTier = 'CORE' | 'SATELLITE' | 'TACTICAL';

/** @deprecated Use ConvictionTier — kept for any legacy imports */
export type CardVerdict = ConvictionTier;

export type TechnicalBias = 'bullish' | 'bearish' | 'neutral';

/** Intraday engine scores span ~0–25 (backend: 12 moderate, 18 strong). */
export const SCORE_STRONG = 18;
export const SCORE_MODERATE = 12;
export const SCORE_WEAK = 8;

/** Minimum intraday score for Asset Matrix BUY cards (strong quant bar). */
export const MATRIX_BUY_MIN_SCORE = 15;

/** Minimum BUY cards shown when the ranked pool has enough names (mandatory floor). */
export const MATRIX_BUY_MIN_DISPLAY = 10;

/** Top-N cap for Asset Matrix display (max cards shown). */
export const MATRIX_BUY_TOP_N = 12;

/** Client profile — branch institutional gates for ₹1cr+ books. */
export const CLIENT_AUM_CR = Number(
  process.env.NEXT_PUBLIC_CLIENT_AUM_CR ?? process.env.CLIENT_AUM_CR ?? 0,
);
export const CLIENT_TIER = String(
  process.env.NEXT_PUBLIC_CLIENT_TIER ?? process.env.CLIENT_TIER ?? 'retail',
).toLowerCase();

export const INSTITUTIONAL_MATRIX_TOP_N = 10;
export const INSTITUTIONAL_MIN_RR = 2.0;
export const INSTITUTIONAL_BOOK_INR = 10_000_000;
export const INSTITUTIONAL_RISK_PCT = 1;
export const INSTITUTIONAL_MAX_NAME_PCT = 10;
export const INSTITUTIONAL_CHECKLIST_MIN = 70;

export type ScoreScale = 'angel' | 'dhan' | 'unknown';

export type MatrixSourceChip = {
  label: 'QUANT' | 'DHAN' | 'SIGQ';
  active: boolean;
};

export type MatrixEvaluationContext = {
  dhanPick?: DhanSwingPick | null;
  atrPct?: number;
  institutional?: boolean;
  /** Snapshot / cache serve — intraday volume gates unreliable. */
  isSnapshotFallback?: boolean;
  /** True when any ranked pool name passes hard filters (live session signal). */
  poolHasHardFilterPasses?: boolean;
  selectionMetaMode?: string;
  hardFilterReasons?: string[];
};

const OFF_HOURS_FILTER_REASON_PATTERNS = [
  /candle api unavailable/i,
  /metrics estimated from quote/i,
  /quote-only/i,
  /opening volume/i,
  /turnover under/i,
  /not in intraday candidate/i,
  /volume pad/i,
  /non-qualifier/i,
];

/** Pool-level off-hours: snapshot serve or zero hard-filter passers in ranked pool. */
export function isInstitutionalOffHoursContext(
  ctx?: Pick<
    MatrixEvaluationContext,
    'isSnapshotFallback' | 'poolHasHardFilterPasses' | 'selectionMetaMode'
  >,
): boolean {
  if (ctx?.isSnapshotFallback) return true;
  if (ctx?.selectionMetaMode === 'snapshot') return true;
  if (ctx?.poolHasHardFilterPasses === false) return true;
  return false;
}

function isOffHoursStyleFilterReasons(reasons?: string[]): boolean {
  if (!reasons?.length) return false;
  return reasons.every((r) =>
    OFF_HOURS_FILTER_REASON_PATTERNS.some((pattern) => pattern.test(r)),
  );
}

export type InstitutionalSizingHint = {
  display: string;
  source: string;
};

export function isInstitutionalClient(): boolean {
  return CLIENT_TIER === 'institutional' || CLIENT_AUM_CR >= 100;
}

export function isInstitutionalMatrixMode(): boolean {
  return isInstitutionalClient();
}

export type WinEdgeResult = {
  /** Newbie-facing label, e.g. "Win edge 68%" or "Conviction 4/5" */
  display: string;
  kind: 'win_edge' | 'conviction';
  value: number;
  source: string;
};

export type ConvictionInput = {
  score: number;
  riskFlag?: string;
  action?: string;
  passesHardFilters?: boolean;
  passesQualityFilters?: boolean;
  isVolumePad?: boolean;
  winLossRatio?: string;
  scoreScale?: ScoreScale;
  hasDhanSignal?: boolean;
};

export type ConvictionResult = {
  tier: ConvictionTier;
  reason: string;
  rankScore: number;
};
export type IntelligenceChipTone = 'bullish' | 'bearish' | 'neutral' | 'info';

export type IntelligenceChip = {
  label: string;
  tone: IntelligenceChipTone;
};

export type TrendlyneCardSummary = {
  ticker: string;
  checklistPassed?: number;
  checklistTotal?: number;
  checklistPassPct?: number;
  checklistInsight?: string;
  technicalBias?: TechnicalBias;
  technicalMomentumScore?: number;
  maBullish?: number;
  maTotal?: number;
  oscillatorBullish?: number;
  oscillatorTotal?: number;
  swotStrengths?: number;
  swotWeaknesses?: number;
  swotOpportunities?: number;
  swotThreats?: number;
  swotNet?: number;
  swotStrengthItems?: string[];
  swotWeaknessItems?: string[];
  swotOpportunityItems?: string[];
  swotThreatItems?: string[];
  swotAvailable?: boolean;
  checklistAvailable?: boolean;
  technicalAvailable?: boolean;
  rsi?: number;
  macd?: number;
  atrPct?: number;
  stochastic?: number;
  volumeMomentum?: number;
  priceAboveSma5?: boolean;
  priceAboveEma5?: boolean;
  priceAboveEma9?: boolean;
  lastModified?: string;
  fetchedAt?: string;
  error?: string;
};

export type DrawerIntelligenceSummary = {
  marketScore?: number;
  recommendation?: string;
  newsSentiment?: AITickerNewsReport['sentiment_overall'];
  forensicHighlights?: string;
  gateHint?: string;
};

export type MergedIntelligenceSummary = {
  chips: IntelligenceChip[];
  hasReliableSignals: boolean;
  hasTrendlyneData: boolean;
  drawer: DrawerIntelligenceSummary;
  trendlyne?: TrendlyneCardSummary;
};

export type ParsedNewsCatalysts = {
  catalysts?: string;
  outlook?: string;
  sector?: string;
  score?: string;
  recommendation?: string;
};

/** Shared with RightDrawer — parses structured sections from news_catalysts_card. */
export function parseNewsCatalystsCard(text: string | undefined): ParsedNewsCatalysts | null {
  if (!text) return null;

  const sections: Record<string, string> = {};
  const lines = text.split('\n');
  let currentSection = '';
  let sectionContent: string[] = [];

  const flush = () => {
    if (currentSection && sectionContent.length) {
      sections[currentSection] = sectionContent.join('\n').trim();
    }
  };

  for (const line of lines) {
    if (line.includes('KEY CATALYSTS:')) {
      flush();
      currentSection = 'catalysts';
      sectionContent = [];
    } else if (line.includes('ACTIONABLE OUTLOOK:')) {
      flush();
      currentSection = 'outlook';
      sectionContent = [];
    } else if (line.includes('SECTOR WATCH:')) {
      flush();
      currentSection = 'sector';
      sectionContent = [];
    } else if (line.includes('MARKET SCORE:')) {
      flush();
      currentSection = 'score';
      sectionContent = [];
    } else if (line.includes('RECOMMENDATION:')) {
      flush();
      currentSection = 'recommendation';
      sectionContent = [];
    } else if (line.trim()) {
      sectionContent.push(line);
    }
  }
  flush();

  if (!Object.keys(sections).length) return null;

  return {
    catalysts: sections.catalysts,
    outlook: sections.outlook,
    sector: sections.sector,
    score: sections.score?.match(/\d+/)?.[0],
    recommendation: sections.recommendation?.trim().toUpperCase(),
  };
}

function chipToneFromRecommendation(rec: string | undefined): IntelligenceChipTone {
  if (!rec) return 'neutral';
  if (rec.includes('BUY')) return 'bullish';
  if (rec.includes('SELL') || rec.includes('AVOID')) return 'bearish';
  if (rec.includes('HOLD')) return 'neutral';
  return 'info';
}

function chipToneFromSentiment(sentiment: string | undefined): IntelligenceChipTone {
  if (sentiment === 'Bullish') return 'bullish';
  if (sentiment === 'Bearish') return 'bearish';
  return 'neutral';
}

function chipToneFromPassPct(pct: number | undefined): IntelligenceChipTone {
  if (pct == null) return 'neutral';
  if (pct >= 65) return 'bullish';
  if (pct <= 40) return 'bearish';
  return 'neutral';
}

function technicalBiasLabel(bias: TechnicalBias | undefined): string | null {
  if (!bias || bias === 'neutral') return null;
  return bias === 'bullish' ? 'Tech Bullish' : 'Tech Bearish';
}

function summarizeForensic(matrix: Record<string, string | number> | undefined): string | undefined {
  if (!matrix) return undefined;
  const parts = Object.entries(matrix)
    .filter(([, value]) => value != null && String(value).trim() && !/^(n\/a|na|-)$/i.test(String(value)))
    .slice(0, 2)
    .map(([key, value]) => `${key.replace(/_/g, ' ')} ${value}`);
  return parts.length ? parts.join(' · ') : undefined;
}

function summarizeGateHint(gates: Record<string, string> | undefined): string | undefined {
  if (!gates) return undefined;
  const q6 = gates.q6_quantitative_milestone ?? '';
  if (/hard-filter pass|quantitative milestone: hard-filter pass/i.test(q6)) {
    return 'IC gate pass';
  }
  if (/watch|fail/i.test(q6)) {
    return 'IC gate watch';
  }
  return undefined;
}

export function extractDrawerIntelligenceSummary(
  intel?: TerminalIntelligence | null,
  news?: AITickerNewsReport | null,
): DrawerIntelligenceSummary {
  const parsedNews = parseNewsCatalystsCard(intel?.news_catalysts_card);
  return {
    marketScore: parsedNews?.score ? parseInt(parsedNews.score, 10) : undefined,
    recommendation: parsedNews?.recommendation,
    newsSentiment: news?.sentiment_overall,
    forensicHighlights: summarizeForensic(intel?.active_scoring_matrix),
    gateHint: summarizeGateHint(intel?.active_seven_ic_gates),
  };
}

/** One compact chip per Trendlyne drawer widget (checklist, technical, SWOT) + optional filler. */
export function buildIntelligenceChips(
  drawer: DrawerIntelligenceSummary,
  trendlyne?: TrendlyneCardSummary | null,
): IntelligenceChip[] {
  const chips: IntelligenceChip[] = [];

  // Widget 1 — Confidence Checker (checklist)
  if (trendlyne?.checklistPassed != null && trendlyne.checklistTotal) {
    chips.push({
      label: `Checklist ${trendlyne.checklistPassed}/${trendlyne.checklistTotal}`,
      tone: chipToneFromPassPct(trendlyne.checklistPassPct),
    });
  } else if (trendlyne?.checklistInsight) {
    const insight = trendlyne.checklistInsight.trim();
    chips.push({
      label: insight.length > 16 ? `${insight.slice(0, 14)}…` : insight,
      tone: chipToneFromPassPct(trendlyne.checklistPassPct),
    });
  }

  // Widget 2 — Technical Analysis
  const techLabel = technicalBiasLabel(trendlyne?.technicalBias);
  if (techLabel) {
    chips.push({
      label: techLabel,
      tone: trendlyne?.technicalBias === 'bullish' ? 'bullish' : 'bearish',
    });
  } else if (typeof trendlyne?.technicalMomentumScore === 'number') {
    const score = trendlyne.technicalMomentumScore;
    chips.push({
      label: `Momentum ${score.toFixed(0)}`,
      tone: score >= 70 ? 'bullish' : score <= 35 ? 'bearish' : 'neutral',
    });
  }

  // Widget 3 — SWOT Analysis
  if (
    trendlyne?.swotStrengths != null ||
    trendlyne?.swotWeaknesses != null ||
    trendlyne?.swotOpportunities != null ||
    trendlyne?.swotThreats != null
  ) {
    const s = trendlyne.swotStrengths ?? 0;
    const w = trendlyne.swotWeaknesses ?? 0;
    const o = trendlyne.swotOpportunities ?? 0;
    const t = trendlyne.swotThreats ?? 0;
    const net = s + o - w - t;
    chips.push({
      label: net >= 0 ? `SWOT +${net}` : `SWOT ${net}`,
      tone: net >= 3 ? 'bullish' : net <= -3 ? 'bearish' : 'neutral',
    });
  }

  // 4th slot — secondary technical signal or drawer intelligence
  if (chips.length < 4) {
    if (trendlyne?.maBullish != null && trendlyne.maTotal) {
      const ratio = trendlyne.maBullish / trendlyne.maTotal;
      chips.push({
        label: `MA ${trendlyne.maBullish}/${trendlyne.maTotal}`,
        tone: ratio >= 0.65 ? 'bullish' : ratio <= 0.35 ? 'bearish' : 'neutral',
      });
    } else if (trendlyne?.oscillatorBullish != null && trendlyne.oscillatorTotal) {
      const ratio = trendlyne.oscillatorBullish / trendlyne.oscillatorTotal;
      chips.push({
        label: `Osc ${trendlyne.oscillatorBullish}/${trendlyne.oscillatorTotal}`,
        tone: ratio >= 0.6 ? 'bullish' : ratio <= 0.4 ? 'bearish' : 'neutral',
      });
    }
  }

  if (chips.length < 4) {
    if (drawer.recommendation) {
      chips.push({
        label: drawer.recommendation.length > 12 ? drawer.recommendation.slice(0, 12) : drawer.recommendation,
        tone: chipToneFromRecommendation(drawer.recommendation),
      });
    } else if (drawer.newsSentiment) {
      chips.push({
        label: `${drawer.newsSentiment} news`,
        tone: chipToneFromSentiment(drawer.newsSentiment),
      });
    } else if (typeof drawer.marketScore === 'number') {
      chips.push({
        label: `Score ${drawer.marketScore}/10`,
        tone: drawer.marketScore >= 8 ? 'bullish' : drawer.marketScore <= 4 ? 'bearish' : 'neutral',
      });
    } else if (drawer.gateHint) {
      chips.push({
        label: drawer.gateHint,
        tone: drawer.gateHint.includes('pass') ? 'bullish' : 'neutral',
      });
    }
  }

  return chips.slice(0, 4);
}

export function mergeIntelligenceSummary(
  intel?: TerminalIntelligence | null,
  news?: AITickerNewsReport | null,
  trendlyne?: TrendlyneCardSummary | null,
): MergedIntelligenceSummary {
  const drawer = extractDrawerIntelligenceSummary(intel, news);
  const hasTrendlyneData = Boolean(
    trendlyne &&
      !trendlyne.error &&
      (trendlyne.checklistTotal ||
        trendlyne.checklistInsight ||
        trendlyne.technicalBias ||
        typeof trendlyne.technicalMomentumScore === 'number' ||
        trendlyne.maBullish != null ||
        trendlyne.swotNet != null),
  );
  const hasDrawerSignals = Boolean(
    drawer.recommendation ||
      drawer.newsSentiment ||
      typeof drawer.marketScore === 'number' ||
      drawer.gateHint ||
      drawer.forensicHighlights,
  );

  return {
    chips: buildIntelligenceChips(drawer, trendlyne),
    hasReliableSignals: hasTrendlyneData || hasDrawerSignals,
    hasTrendlyneData,
    drawer,
    trendlyne: trendlyne ?? undefined,
  };
}

function parseWinLossRatio(value: string | undefined): number | null {
  const text = String(value ?? '').trim();
  const match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$/);
  if (!match) return null;
  const wins = parseFloat(match[1]);
  const losses = parseFloat(match[2]);
  if (!Number.isFinite(wins) || !Number.isFinite(losses) || losses <= 0) return null;
  return wins / losses;
}

function winProbFromRatio(ratioText: string | undefined): number | null {
  const text = String(ratioText ?? '').trim();
  const match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$/);
  if (!match) return null;
  const wins = parseFloat(match[1]);
  const losses = parseFloat(match[2]);
  if (!Number.isFinite(wins) || !Number.isFinite(losses) || wins + losses <= 0) return null;
  return Math.round((wins / (wins + losses)) * 100);
}

function scoreToConvictionBars(score: number): number {
  if (score <= 0) return 0;
  if (score < SCORE_WEAK) return 1;
  if (score < SCORE_MODERATE) return 2;
  if (score < 15) return 3;
  if (score < SCORE_STRONG) return 4;
  return 5;
}

function isActionBuySignal(action: string | undefined): boolean {
  const text = String(action ?? '').toLowerCase();
  return /buy|long|accumul|breakout|momentum|trigger/i.test(text);
}

function tierRank(tier: ConvictionTier): number {
  switch (tier) {
    case 'CORE':
      return 3;
    case 'SATELLITE':
      return 2;
    default:
      return 1;
  }
}

/**
 * Primary newbie signal — only shows Win edge % when derived from real W/L or checklist data.
 * Otherwise shows Conviction X/5 from intraday score bands.
 */
export function computeWinEdge(
  row: ConvictionInput,
  trendlyne?: TrendlyneCardSummary | null,
): WinEdgeResult | null {
  const checklistPct = trendlyne?.checklistPassPct;
  const wlProb = winProbFromRatio(row.winLossRatio);

  if (typeof checklistPct === 'number' && Number.isFinite(checklistPct)) {
    return {
      display: `Win edge ${Math.round(checklistPct)}%`,
      kind: 'win_edge',
      value: Math.round(checklistPct),
      source: 'SIGQ Research checklist pass rate',
    };
  }

  if (wlProb !== null) {
    return {
      display: `Win edge ${wlProb}%`,
      kind: 'win_edge',
      value: wlProb,
      source: 'Historical W/L ratio',
    };
  }

  const bars = scoreToConvictionBars(row.score);
  if (bars > 0) {
    return {
      display: `Conviction ${bars}/5`,
      kind: 'conviction',
      value: bars,
      source: `Intraday score ${row.score.toFixed(1)} (bands: 8/12/18/15/18)`,
    };
  }

  return null;
}

/** Base conviction tier from quant score, risk flag, and filter status. */
export function computeConvictionTier(row: ConvictionInput): ConvictionResult {
  const flag = String(row.riskFlag ?? '').toUpperCase();
  const actionBuy = isActionBuySignal(row.action);
  const hardPass = row.passesHardFilters !== false;

  let tier: ConvictionTier = 'TACTICAL';
  let reason = 'Swing candidate — starter position size';

  if (
    row.score >= SCORE_STRONG &&
    hardPass &&
    !flag.includes('HIGH_RISK') &&
    !flag.includes('EXTREME')
  ) {
    tier = 'CORE';
    reason = flag.includes('LOW_RISK')
      ? 'Strong swing setup — size up'
      : 'High-score momentum — core allocation';
  } else if (actionBuy && row.score >= 15 && hardPass) {
    tier = 'CORE';
    reason = 'Active ledger buy — prioritize sizing';
  } else if (row.score >= SCORE_MODERATE && hardPass) {
    tier = 'SATELLITE';
    reason = 'Solid swing setup — standard satellite weight';
  } else if (flag.includes('MODERATE_RISK') && row.score >= SCORE_WEAK) {
    tier = 'SATELLITE';
    reason = 'Moderate risk swing — keep position modest';
  } else if (row.score > 0 && row.score < SCORE_MODERATE) {
    tier = 'TACTICAL';
    reason = 'Early momentum — tactical probe only';
  } else if (!hardPass) {
    tier = 'TACTICAL';
    reason = 'Building confirmation — small tactical stake';
  }

  const wlRatio = parseWinLossRatio(row.winLossRatio);
  let rankScore = tierRank(tier) * 100 + row.score;
  if (hardPass) rankScore += 12;
  if (wlRatio !== null) rankScore += Math.min(wlRatio * 5, 20);
  if (flag.includes('LOW_RISK')) rankScore += 8;

  return { tier, reason, rankScore };
}

type ConvictionAdjustRow = {
  isMetaRow?: boolean;
};

export function adjustConvictionWithIntelligence(
  base: ConvictionResult,
  summary: MergedIntelligenceSummary,
  row: ConvictionAdjustRow,
): ConvictionResult {
  if (row.isMetaRow || !summary.hasReliableSignals) {
    return base;
  }

  let { tier, reason, rankScore } = base;
  const boosts: string[] = [];
  const drags: string[] = [];

  const tl = summary.trendlyne;
  if (tl?.checklistPassPct != null) {
    if (tl.checklistPassPct >= 65) {
      boosts.push(`checklist ${Math.round(tl.checklistPassPct)}% pass`);
    } else if (tl.checklistPassPct <= 40) {
      drags.push(`checklist ${Math.round(tl.checklistPassPct)}% pass`);
    }
  }

  if (tl?.technicalBias === 'bullish') {
    boosts.push('technical bias bullish');
  } else if (tl?.technicalBias === 'bearish') {
    drags.push('technical bias bearish');
  } else if (typeof tl?.technicalMomentumScore === 'number') {
    if (tl.technicalMomentumScore >= 70) boosts.push('strong momentum');
    else if (tl.technicalMomentumScore <= 35) drags.push('weak momentum');
  }

  if (tl?.maBullish != null && tl.maTotal) {
    const maRatio = tl.maBullish / tl.maTotal;
    if (maRatio >= 0.65) boosts.push('MA trend supportive');
    else if (maRatio <= 0.35) drags.push('MA trend weak');
  }

  if (typeof tl?.swotNet === 'number') {
    if (tl.swotNet >= 4) boosts.push('SWOT positive');
    else if (tl.swotNet <= -4) drags.push('SWOT negative');
  }

  const drawer = summary.drawer;
  if (drawer.recommendation?.includes('BUY')) boosts.push('AI buy signal');
  if (drawer.recommendation?.includes('AVOID') || drawer.recommendation?.includes('SELL')) {
    drags.push('AI caution flag');
  }
  if (drawer.newsSentiment === 'Bullish') boosts.push('bullish news');
  if (drawer.newsSentiment === 'Bearish') drags.push('bearish news');
  if (typeof drawer.marketScore === 'number') {
    if (drawer.marketScore >= 8) boosts.push(`market score ${drawer.marketScore}/10`);
    else if (drawer.marketScore <= 4) drags.push(`market score ${drawer.marketScore}/10`);
  }

  const boostScore = boosts.length;
  const dragScore = drags.length;

  if (tier === 'TACTICAL' && boostScore >= 2 && dragScore === 0) {
    tier = 'SATELLITE';
    reason = 'SIGQ Research confirms swing — satellite weight';
    rankScore += 15;
  } else if (tier === 'SATELLITE' && boostScore >= 2 && dragScore === 0) {
    tier = 'CORE';
    reason = 'Multi-signal alignment — size up';
    rankScore += 25;
  } else if (tier === 'CORE' && dragScore >= 2) {
    tier = 'SATELLITE';
    reason = 'Trim conviction — mixed secondary signals';
    rankScore -= 20;
  } else if (tier !== 'TACTICAL' && dragScore >= 3 && boostScore === 0) {
    tier = 'TACTICAL';
    reason = 'Reduce sizing — secondary headwinds';
    rankScore -= 15;
  }

  const hint = boosts[0] ?? drags[0];
  if (hint && !reason.toLowerCase().includes(hint.split(' ')[0])) {
    reason = `${reason} · ${hint}`;
  }

  rankScore += boostScore * 4 - dragScore * 3;

  return { tier, reason, rankScore };
}

/** @deprecated Use adjustConvictionWithIntelligence */
export function adjustVerdictWithIntelligence(
  base: { verdict: ConvictionTier; reason: string },
  summary: MergedIntelligenceSummary,
  row: ConvictionAdjustRow & { isVolumePad?: boolean; passesHardFilters?: boolean },
): { verdict: ConvictionTier; reason: string } {
  const conviction = adjustConvictionWithIntelligence(
    { tier: base.verdict, reason: base.reason, rankScore: 0 },
    summary,
    row,
  );
  return { verdict: conviction.tier, reason: conviction.reason };
}

export type MatrixBuyEvaluation = {
  eligible: boolean;
  tier: ConvictionTier;
  reason: string;
  rankScore: number;
  winEdge: WinEdgeResult | null;
};

function isRejectAction(action: string | undefined): boolean {
  const text = String(action ?? '').trim().toUpperCase();
  if (!text) return false;
  return /\b(AVOID|WATCH|SELL|REJECT)\b/.test(text);
}

function isRejectRecommendation(rec: string | undefined): boolean {
  if (!rec) return false;
  const upper = rec.toUpperCase();
  return upper.includes('AVOID') || upper.includes('SELL') || upper.includes('HOLD');
}

/** Shared hard-reject gate for Asset Matrix (strict BUY and filler paths). */
export function isMatrixHardReject(row: ConvictionInput, recommendation?: string): boolean {
  const flag = String(row.riskFlag ?? '').toUpperCase();
  return (
    Boolean(row.isVolumePad) ||
    flag.includes('VOLUME_FILL') ||
    flag === 'UNRATED' ||
    flag.includes('HIGH_RISK') ||
    flag.includes('EXTREME') ||
    isRejectAction(row.action) ||
    isRejectRecommendation(recommendation)
  );
}

/** Looser gate for mandatory top-N floor — retail only; disabled in institutional mode. */
export function isMatrixFillerCandidate(
  row: ConvictionInput,
  summary: MergedIntelligenceSummary,
): boolean {
  if (isInstitutionalMatrixMode()) return false;
  if (isMatrixHardReject(row, summary.drawer.recommendation)) return false;
  if (row.score < SCORE_MODERATE) return false;
  return true;
}

function isPreferredRiskFlag(flag: string): boolean {
  const f = flag.toUpperCase();
  return f.includes('LOW_RISK') || f.includes('MODERATE_RISK');
}

function hasTrendlyneInstitutionalConfirm(summary: MergedIntelligenceSummary): boolean {
  const tl = summary.trendlyne;
  if (!tl || tl.error) return false;
  if (tl.technicalBias === 'bearish') return false;
  if (typeof tl.checklistPassPct === 'number' && tl.checklistPassPct >= INSTITUTIONAL_CHECKLIST_MIN) {
    return true;
  }
  if (tl.technicalBias === 'bullish') return true;
  if (typeof tl.technicalMomentumScore === 'number' && tl.technicalMomentumScore >= 70) return true;
  if (typeof tl.swotNet === 'number' && tl.swotNet >= 4) return true;
  return false;
}

function isDhanPickStructurallyValid(pick: DhanSwingPick | null | undefined): boolean {
  if (!pick?.symbol) return false;
  const entry = Number(pick.buyAbove ?? 0);
  const stop = Number(pick.stopLoss ?? 0);
  return entry > 0 && stop > 0 && entry > stop;
}

export function dhanRrValue(pick: DhanSwingPick | null | undefined): number | null {
  if (!pick) return null;
  const rr = pick.rrT2;
  if (typeof rr === 'number' && Number.isFinite(rr) && rr > 0) return rr;
  const entry = Number(pick.buyAbove ?? 0);
  const stop = Number(pick.stopLoss ?? 0);
  const target2 = Number(pick.target2 ?? 0);
  if (entry > stop && target2 > entry) {
    const risk = entry - stop;
    const reward = target2 - entry;
    if (risk > 0) return reward / risk;
  }
  return null;
}

export type EstimatedRrResult = {
  ok: boolean;
  display: string;
  value: number | null;
  isEstimate: boolean;
};

/** Estimated 2:1 R:R from ATR% when Dhan rrT2 absent — labeled estimate only. */
export function estimateStructuralRr(atrPct: number | undefined): EstimatedRrResult | null {
  if (typeof atrPct !== 'number' || !Number.isFinite(atrPct) || atrPct <= 0) return null;
  return {
    ok: true,
    value: 2.0,
    display: 'R:R est 2:1 (2×ATR stop)',
    isEstimate: true,
  };
}

export function buildMatrixSourceChips(
  hasQuant: boolean,
  hasDhan: boolean,
  hasTrendlyne: boolean,
): MatrixSourceChip[] {
  const chips: MatrixSourceChip[] = [
    { label: 'QUANT', active: hasQuant },
    { label: 'DHAN', active: hasDhan },
    { label: 'SIGQ', active: hasTrendlyne },
  ];
  return chips.filter((c) => c.active);
}

function parsePercentValueFromPolicy(value: unknown): number | null {
  const text = String(value ?? '').trim();
  const match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*%$/);
  return match ? parseFloat(match[1]) : null;
}

/** ₹1cr book sizing — facts from policy_allocation or 1% risk with entry/stop. */
export function computeInstitutionalSizingHint(
  entry: number | undefined,
  stop: number | undefined,
  kellyPolicy?: string,
): InstitutionalSizingHint | null {
  const book = INSTITUTIONAL_BOOK_INR;
  const riskAmt = book * (INSTITUTIONAL_RISK_PCT / 100);
  const maxName = book * (INSTITUTIONAL_MAX_NAME_PCT / 100);

  const kellyPct = parsePercentValueFromPolicy(kellyPolicy);
  if (kellyPct !== null && kellyPct > 0) {
    const alloc = Math.min(book * (kellyPct / 100), maxName);
    return {
      display: `₹1cr: ${kellyPct}% (~₹${(alloc / 100000).toFixed(1)}L cap)`,
      source: 'policy_allocation',
    };
  }

  if (typeof entry === 'number' && typeof stop === 'number' && entry > stop && entry > 0) {
    const riskPerShare = entry - stop;
    const sharesByRisk = Math.floor(riskAmt / riskPerShare);
    let capital = sharesByRisk * entry;
    capital = Math.min(capital, maxName);
    const shares = Math.floor(capital / entry);
    const pct = (capital / book) * 100;
    return {
      display: `₹1cr: ${pct.toFixed(1)}% (~${shares} sh, 1% risk ₹${(riskAmt / 1000).toFixed(0)}k)`,
      source: '1% risk cap',
    };
  }

  return null;
}

function hasTrendlyneBuyConfirmation(summary: MergedIntelligenceSummary): boolean {
  const tl = summary.trendlyne;
  if (!tl) return false;
  if (typeof tl.checklistPassPct === 'number' && tl.checklistPassPct >= 65) return true;
  if (tl.technicalBias === 'bullish') return true;
  if (typeof tl.technicalMomentumScore === 'number' && tl.technicalMomentumScore >= 70) return true;
  if (typeof tl.swotNet === 'number' && tl.swotNet >= 4) return true;
  if (summary.drawer.recommendation?.includes('BUY')) return true;
  return false;
}

/**
 * Asset Matrix inclusion gate.
 * Institutional (₹1cr+): score ≥18, Trendlyne confirm, LOW/MODERATE risk,
 * R:R ≥2 from Dhan when in Dhan LONG set (else ATR estimate), no fillers.
 * Hard+quality filters are absolute only in live session when pool has passers;
 * off-hours / snapshot serve rank-penalizes failed volume gates instead.
 * Retail: CORE BUY bar with optional filler floor.
 */
export function evaluateMatrixBuyCandidate(
  row: ConvictionInput,
  summary: MergedIntelligenceSummary,
  ctx?: MatrixEvaluationContext,
): MatrixBuyEvaluation {
  const institutional = ctx?.institutional ?? isInstitutionalMatrixMode();
  const dhanPick = ctx?.dhanPick;
  const base = computeConvictionTier(row);
  const adjusted = adjustConvictionWithIntelligence(base, summary, { isMetaRow: false });
  const flag = String(row.riskFlag ?? '').toUpperCase();
  const winEdge = computeWinEdge(row, summary.trendlyne);
  const hardPass = row.passesHardFilters !== false;
  const trendlyneConfirmed = hasTrendlyneBuyConfirmation(summary);

  const hardReject = isMatrixHardReject(row, summary.drawer.recommendation);

  if (institutional) {
    let eligible = !hardReject;
    let reason = adjusted.reason;
    let displayTier: ConvictionTier = adjusted.tier;

    const offHoursCtx = isInstitutionalOffHoursContext(ctx);
    const rowOffHoursFilters =
      offHoursCtx ||
      (row.passesHardFilters === false && isOffHoursStyleFilterReasons(ctx?.hardFilterReasons));
    const applyHardQualityGate = !rowOffHoursFilters;

    if (applyHardQualityGate) {
      if (row.passesHardFilters === false) eligible = false;
      if (row.passesQualityFilters === false) eligible = false;
    }

    if (!summary.hasTrendlyneData) {
      eligible = false;
      reason = 'SIGQ Research confirmation required — data pending';
    } else if (!hasTrendlyneInstitutionalConfirm(summary)) {
      eligible = false;
      reason = 'SIGQ Research confirmation below institutional bar';
    }
    if (summary.trendlyne?.technicalBias === 'bearish') {
      eligible = false;
      reason = 'SIGQ Research bearish bias — blocked';
    }

    const angelQuantStrong =
      row.scoreScale !== 'dhan' && row.score >= SCORE_STRONG;
    if (!angelQuantStrong) {
      eligible = false;
      reason = `Quant score ${row.score.toFixed(1)} below ${SCORE_STRONG} strong bar`;
    }

    if (flag && !isPreferredRiskFlag(flag)) {
      eligible = false;
      reason = `${flag.replace(/_/g, ' ')} — institutional book blocks`;
    }

    const inDhanLong = Boolean(dhanPick) && isDhanPickStructurallyValid(dhanPick);
    if (inDhanLong) {
      const rr = dhanRrValue(dhanPick);
      if (rr === null || rr < INSTITUTIONAL_MIN_RR) {
        eligible = false;
        reason = `Scanner R:R ${rr?.toFixed(1) ?? '—'} below ${INSTITUTIONAL_MIN_RR}:1`;
      }
    } else {
      const est = estimateStructuralRr(ctx?.atrPct);
      if (!est?.ok) {
        eligible = false;
        reason = 'No scanner LONG R:R — ATR estimate unavailable';
      }
    }

    if (applyHardQualityGate && adjusted.tier !== 'CORE') {
      eligible = false;
      reason = 'Conviction below CORE — institutional size gate';
    }
    displayTier = 'CORE';

    let rankScore = adjusted.rankScore;
    if (rowOffHoursFilters) {
      if (row.passesHardFilters === false) rankScore -= 15;
      if (row.passesQualityFilters === false) rankScore -= 8;
    }
    if (inDhanLong) rankScore += 35;
    const rr = dhanRrValue(dhanPick);
    if (rr !== null && rr >= INSTITUTIONAL_MIN_RR) rankScore += Math.min(rr * 8, 32);
    if (winEdge?.kind === 'win_edge') rankScore += winEdge.value;
    else if (winEdge?.kind === 'conviction') rankScore += winEdge.value * 8;

    return {
      eligible,
      tier: displayTier,
      reason,
      rankScore,
      winEdge,
    };
  }

  const scoreOk = row.score >= MATRIX_BUY_MIN_SCORE;
  let tierOk = adjusted.tier === 'CORE';
  let displayTier: ConvictionTier = adjusted.tier;
  if (!tierOk && hardPass && row.score >= SCORE_MODERATE && trendlyneConfirmed && adjusted.tier === 'SATELLITE') {
    tierOk = true;
    displayTier = 'CORE';
  }
  if (!tierOk && row.score >= SCORE_STRONG && !flag.includes('HIGH_RISK') && !flag.includes('EXTREME')) {
    tierOk = true;
    displayTier = 'CORE';
  }
  const eligible = !hardReject && scoreOk && tierOk;

  let rankScore = adjusted.rankScore;
  if (dhanPick && isDhanPickStructurallyValid(dhanPick)) rankScore += 20;
  const rr = dhanRrValue(dhanPick);
  if (rr !== null && rr >= INSTITUTIONAL_MIN_RR) rankScore += 12;
  if (winEdge?.kind === 'win_edge') rankScore += winEdge.value;
  else if (winEdge?.kind === 'conviction') rankScore += winEdge.value * 8;

  return {
    eligible,
    tier: displayTier,
    reason: adjusted.reason,
    rankScore,
    winEdge,
  };
}

export type MatrixEvaluatedCandidate<T extends ConvictionInput & { ticker: string; score: number }> =
  MatrixBuyEvaluation & {
    row: T;
    intelligence: MergedIntelligenceSummary;
  };

function compareMatrixRank<T extends ConvictionInput & { score: number }>(
  a: MatrixBuyEvaluation & { row: T; winEdge: WinEdgeResult | null },
  b: MatrixBuyEvaluation & { row: T; winEdge: WinEdgeResult | null },
): number {
  return (
    b.rankScore - a.rankScore ||
    (b.winEdge?.value ?? 0) - (a.winEdge?.value ?? 0) ||
    b.row.score - a.row.score
  );
}

function compareMatrixFillerRank<T extends ConvictionInput & { score: number; passesHardFilters?: boolean }>(
  a: MatrixBuyEvaluation & { row: T; winEdge: WinEdgeResult | null },
  b: MatrixBuyEvaluation & { row: T; winEdge: WinEdgeResult | null },
): number {
  const hardA = a.row.passesHardFilters ? 1 : 0;
  const hardB = b.row.passesHardFilters ? 1 : 0;
  if (hardB !== hardA) return hardB - hardA;
  return compareMatrixRank(a, b);
}

/**
 * Pick Asset Matrix cards: strict eligible only in institutional mode (no fillers).
 * Retail may fill to MATRIX_BUY_MIN_DISPLAY from ranked pool.
 */
export function selectMatrixDisplayRows<T extends ConvictionInput & { ticker: string; score: number; passesHardFilters?: boolean }>(
  evaluated: MatrixEvaluatedCandidate<T>[],
  poolSize: number,
  institutional?: boolean,
): MatrixEvaluatedCandidate<T>[] {
  const inst = institutional ?? isInstitutionalMatrixMode();
  const cap = inst
    ? Math.min(INSTITUTIONAL_MATRIX_TOP_N, poolSize)
    : Math.min(MATRIX_BUY_TOP_N, poolSize);
  const targetMin = inst ? 0 : Math.min(MATRIX_BUY_MIN_DISPLAY, poolSize);

  const strict = evaluated.filter((item) => item.eligible).sort(compareMatrixRank);
  const display: MatrixEvaluatedCandidate<T>[] = strict.slice(0, cap);
  const used = new Set(display.map((item) => item.row.ticker));

  if (!inst && display.length < targetMin) {
    const fillers = evaluated
      .filter((item) => !item.eligible && !used.has(item.row.ticker))
      .filter((item) => isMatrixFillerCandidate(item.row, item.intelligence))
      .sort(compareMatrixFillerRank);
    const needed = Math.min(targetMin, cap) - display.length;
    for (const item of fillers.slice(0, needed)) {
      display.push(item);
      used.add(item.row.ticker);
    }
  }

  return display;
}

/** Newbie-facing badge — CORE maps to BUY. */
export function convictionTierBadgeLabel(tier: ConvictionTier): string {
  switch (tier) {
    case 'CORE':
      return 'BUY';
    case 'SATELLITE':
      return 'WATCH';
    default:
      return 'AVOID';
  }
}

export function convictionTierStyles(tier: ConvictionTier): { badge: string; border: string; glow: string } {
  switch (tier) {
    case 'CORE':
      return {
        badge: 'text-white bg-emerald-600 border-emerald-700',
        border: '#10b981',
        glow: '#10b981',
      };
    case 'SATELLITE':
      return {
        badge: 'text-amber-900 bg-amber-100 border-amber-300',
        border: '#f59e0b',
        glow: '#f59e0b',
      };
    default:
      return {
        badge: 'text-slate-100 bg-slate-600 border-slate-700',
        border: '#64748b',
        glow: '#94a3b8',
      };
  }
}

export function chipToneClass(tone: IntelligenceChipTone): string {
  switch (tone) {
    case 'bullish':
      return 'text-emerald-700 bg-emerald-50 border-emerald-200';
    case 'bearish':
      return 'text-red-700 bg-red-50 border-red-200';
    case 'info':
      return 'text-indigo-700 bg-indigo-50 border-indigo-200';
    default:
      return 'text-slate-600 bg-slate-50 border-slate-200';
  }
}

export function matrixSourceChipClass(label: MatrixSourceChip['label'], active: boolean): string {
  if (!active) return 'text-slate-400 bg-slate-50 border-slate-200 opacity-50';
  switch (label) {
    case 'QUANT':
      return 'text-slate-800 bg-slate-100 border-slate-300';
    case 'DHAN':
      return 'text-violet-800 bg-violet-50 border-violet-200';
    default:
      return 'text-sky-800 bg-sky-50 border-sky-200';
  }
}
