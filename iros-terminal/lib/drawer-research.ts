import type { AITickerNewsReport, TerminalIntelligence } from "@/lib/market-api";
import type { TrendlyneCardSummary } from "@/lib/intelligence-summary";

export type IntradayMetrics = {
  rsi?: number | null;
  atr_pct?: number | null;
  volume_multiplier?: number | null;
  turnover_cr?: number | null;
  price_above_vwap?: boolean | null;
  price_above_ema9?: boolean | null;
  passes_hard_filters?: boolean | null;
  passes_quality_filters?: boolean | null;
  promoter_holding_pct?: number | null;
  vwap?: number | null;
  data_source?: string | null;
  hard_filter_reasons?: string[] | null;
};

export type DrawerStockFacts = {
  promoter_holding_pct?: number;
  passes_quality_filters?: boolean;
  bulk_deal_signal?: boolean;
};

export function parseNumeric(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(String(value).replace(/[^\d.-]/g, ""));
  return Number.isFinite(n) ? n : null;
}

function snapshotBarSource(intraday?: IntradayMetrics | null): "candles" | "daily_candles" | "" {
  if (!intraday) return "";
  const reasons = (intraday.hard_filter_reasons || []).map(String);
  if (reasons.some((reason) => reason.includes("not in intraday candidate set"))) return "";
  const src = String(intraday.data_source || "");
  if (src === "candles" || src === "daily_candles") return src;
  return "";
}

export function buildTechnicalSignals(
  intraday?: IntradayMetrics | null,
  trendlyne?: TrendlyneCardSummary | null,
): {
  rsi: number | null;
  macd: number | null;
  stochastic: number | null;
  maSignal: "BUY" | "SELL" | "NEUTRAL";
  strength: number | null;
  volume: number | null;
  volatility: number | null;
  hasData: boolean;
  aboveVwap: boolean | null;
  aboveEma9: boolean | null;
  vwapLabel: string;
  emaLabel: string;
  metricSource: "5m" | "daily" | "trendlyne" | "mixed" | "none";
} {
  const src = snapshotBarSource(intraday);
  const snapshotRsi = src ? parseNumeric(intraday?.rsi) : null;
  const snapshotAtr = src ? parseNumeric(intraday?.atr_pct) : null;
  const volMult = src ? parseNumeric(intraday?.volume_multiplier) : null;
  const snapshotVwap = src === "candles" ? (intraday?.price_above_vwap ?? null) : null;
  const snapshotEma9 = src === "candles" ? (intraday?.price_above_ema9 ?? null) : null;

  const rsi = snapshotRsi ?? parseNumeric(trendlyne?.rsi);
  const atr = snapshotAtr ?? parseNumeric(trendlyne?.atrPct);
  const aboveVwap = snapshotVwap ?? trendlyne?.priceAboveSma5 ?? null;
  const aboveEma9 = snapshotEma9 ?? trendlyne?.priceAboveEma9 ?? trendlyne?.priceAboveEma5 ?? null;
  const vwapLabel = snapshotVwap != null ? "VWAP" : "SMA5 (Trendlyne)";
  const emaLabel = snapshotEma9 != null ? "EMA9" : "EMA (Trendlyne)";

  let maSignal: "BUY" | "SELL" | "NEUTRAL" = "NEUTRAL";
  if (aboveVwap === true && aboveEma9 === true) maSignal = "BUY";
  else if (aboveVwap === false && aboveEma9 === false) maSignal = "SELL";
  else if (snapshotVwap == null && snapshotEma9 == null && trendlyne?.maBullish != null && trendlyne.maTotal) {
    const ratio = trendlyne.maBullish / trendlyne.maTotal;
    if (ratio >= 0.65) maSignal = "BUY";
    else if (ratio <= 0.35) maSignal = "SELL";
  }

  const snapshotMacd =
    snapshotVwap === true && snapshotEma9 === true
      ? 1
      : snapshotVwap === false && snapshotEma9 === false
        ? -1
        : snapshotVwap != null || snapshotEma9 != null
          ? 0.2
          : null;
  const macd = snapshotMacd ?? parseNumeric(trendlyne?.macd);
  const stochastic = parseNumeric(trendlyne?.stochastic);

  const strength = rsi != null ? Math.min(100, Math.max(0, rsi)) : null;
  const volume = volMult != null ? Math.min(100, Math.max(0, volMult * 25)) : null;
  const volatility = atr != null ? Math.min(100, Math.max(0, atr * 20)) : null;
  const hasTrendlyne = Boolean(
    trendlyne &&
      (trendlyne.rsi != null ||
        trendlyne.macd != null ||
        trendlyne.atrPct != null ||
        trendlyne.maTotal != null ||
        trendlyne.priceAboveSma5 != null ||
        trendlyne.priceAboveEma5 != null ||
        trendlyne.priceAboveEma9 != null),
  );
  const hasSnapshot = snapshotRsi != null || snapshotAtr != null || volMult != null || snapshotVwap != null || snapshotEma9 != null;
  const hasData = hasSnapshot || hasTrendlyne;
  const metricSource: "5m" | "daily" | "trendlyne" | "mixed" | "none" =
    hasSnapshot && hasTrendlyne && src
      ? "mixed"
      : src === "candles"
        ? "5m"
        : src === "daily_candles"
          ? "daily"
          : hasTrendlyne
            ? "trendlyne"
            : "none";

  return {
    rsi,
    macd,
    stochastic,
    maSignal,
    strength,
    volume,
    volatility,
    hasData,
    aboveVwap,
    aboveEma9,
    vwapLabel,
    emaLabel,
    metricSource,
  };
}

const NEWS_OPPORTUNITY_KEYS: Array<keyof AITickerNewsReport> = [
  "future_expansion_capex",
  "new_orders_contracts",
  "earnings_results",
  "institutional_activity",
  "dividend_news",
];

function newsLine(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  const normalized = trimmed.toLowerCase().replace(/[.!]+$/g, "");
  if (!trimmed || new Set([
    "none", "n/a", "na", "nil", "not available", "no data",
    "no recent news found", "no significant risk", "no significant risks",
  ]).has(normalized)) return null;
  return trimmed;
}

function distinctMeaningful(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values) {
    const value = newsLine(raw);
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

export function buildFactSwot(params: {
  ticker: string;
  intraday?: IntradayMetrics | null;
  tickerNews?: AITickerNewsReport | null;
  terminalAnalysis?: TerminalIntelligence | null;
  stock?: DrawerStockFacts | null;
  trendlyne?: TrendlyneCardSummary | null;
}): {
  strengths: string[];
  weaknesses: string[];
  opportunities: string[];
  threats: string[];
  scores: {
    overall: number | null;
    strength: number | null;
    opportunity: number | null;
    weakness: number | null;
    threat: number | null;
  };
  hasData: boolean;
  partial: boolean;
  coverage: string[];
  source: "trendlyne+snapshot" | "trendlyne" | "snapshot" | "none";
} {
  const strengths: string[] = [];
  const weaknesses: string[] = [];
  const opportunities: string[] = [];
  const threats: string[] = [];
  const intra = params.intraday;
  const news = params.tickerNews;
  const stock = params.stock;
  const trendlyne = params.trendlyne;

  strengths.push(...distinctMeaningful(trendlyne?.swotStrengthItems ?? []));
  weaknesses.push(...distinctMeaningful(trendlyne?.swotWeaknessItems ?? []));
  opportunities.push(...distinctMeaningful(trendlyne?.swotOpportunityItems ?? []));
  threats.push(...distinctMeaningful(trendlyne?.swotThreatItems ?? []));

  if (intra?.price_above_vwap && intra?.price_above_ema9) {
    strengths.push("Price above VWAP and EMA9 — intraday trend alignment.");
  } else if (intra?.price_above_vwap) {
    strengths.push("Price above VWAP — positive intraday anchor.");
  }
  if (intra?.passes_hard_filters) {
    strengths.push("Passes desk hard-filter screen on live intraday metrics.");
  }

  const rsi = parseNumeric(intra?.rsi);
  if (rsi != null && rsi >= 45 && rsi <= 65) {
    strengths.push(`RSI ${rsi.toFixed(1)} in balanced momentum zone.`);
  }

  const volMult = parseNumeric(intra?.volume_multiplier);
  if (volMult != null && volMult >= 1.2) {
    strengths.push(`Volume ${volMult.toFixed(2)}× vs reference — elevated participation.`);
  }

  const promoter = parseNumeric(stock?.promoter_holding_pct ?? intra?.promoter_holding_pct);
  if (promoter != null && promoter >= 50) {
    strengths.push(`Promoter holding ${promoter.toFixed(1)}%.`);
  }
  if (stock?.bulk_deal_signal) {
    strengths.push("Bulk deal signal flagged in snapshot.");
  }

  if (intra?.price_above_vwap === false) {
    weaknesses.push("Trading below VWAP — weak intraday bid.");
  }
  if (intra?.passes_hard_filters === false) {
    weaknesses.push("Fails desk hard-filter screen.");
  }
  if (rsi != null && rsi > 70) {
    weaknesses.push(`RSI ${rsi.toFixed(1)} — overbought stretch.`);
  }
  if (rsi != null && rsi < 35) {
    weaknesses.push(`RSI ${rsi.toFixed(1)} — weak momentum.`);
  }

  const atr = parseNumeric(intra?.atr_pct);
  if (atr != null && atr > 3) {
    weaknesses.push(`ATR ${atr.toFixed(2)}% — elevated volatility.`);
  }
  if (stock?.passes_quality_filters === false || intra?.passes_quality_filters === false) {
    weaknesses.push("Quality filter screen marked fail.");
  }

  for (const key of NEWS_OPPORTUNITY_KEYS) {
    const line = newsLine(news?.[key]);
    if (line) opportunities.push(line);
  }
  const headline = newsLine(news?.summary_headline);
  if (headline && news?.sentiment_overall?.toLowerCase() === "bullish") {
    opportunities.push(headline);
  }

  const riskFlags = newsLine(news?.risk_flags);
  if (riskFlags && !riskFlags.toLowerCase().includes("no significant")) {
    threats.push(riskFlags);
  }
  if (headline && news?.sentiment_overall?.toLowerCase() === "bearish") {
    threats.push(headline);
  }
  const regulatory = newsLine(news?.regulatory_filings);
  if (regulatory) threats.push(regulatory);

  const gates = params.terminalAnalysis?.active_seven_ic_gates;
  if (gates && typeof gates === "object") {
    for (const [key, value] of Object.entries(gates)) {
      const text = String(value ?? "").toLowerCase();
      if (text.includes("fail") || text.includes("reject") || text.includes("concern")) {
        threats.push(`${key.replace(/_/g, " ")}: ${String(value)}`);
      }
    }
  }

  const cleanStrengths = distinctMeaningful(strengths);
  const cleanWeaknesses = distinctMeaningful(weaknesses);
  const cleanOpportunities = distinctMeaningful(opportunities);
  const cleanThreats = distinctMeaningful(threats);
  const hasData = cleanStrengths.length + cleanWeaknesses.length + cleanOpportunities.length + cleanThreats.length > 0;
  const hasTrendlyne = trendlyne?.swotAvailable === true;
  const hasSnapshot = Boolean(intra || news || stock || params.terminalAnalysis);
  const balance = cleanStrengths.length + cleanOpportunities.length - cleanWeaknesses.length - cleanThreats.length;
  const overall = hasData ? Math.round(Math.min(92, Math.max(12, 50 + balance * 7))) : null;
  const score = (count: number, base: number) => count ? Math.min(88, base + count * 11) : null;
  const coverage = [
    hasTrendlyne ? "Trendlyne SWOT" : null,
    intra ? "intraday metrics" : null,
    news ? "ticker news" : null,
    params.terminalAnalysis ? "IC gates" : null,
    stock ? "snapshot facts" : null,
  ].filter((value): value is string => Boolean(value));

  return {
    strengths: cleanStrengths.slice(0, 5),
    weaknesses: cleanWeaknesses.slice(0, 5),
    opportunities: cleanOpportunities.slice(0, 5),
    threats: cleanThreats.slice(0, 5),
    scores: {
      overall,
      strength: score(cleanStrengths.length, 35),
      opportunity: score(cleanOpportunities.length, 35),
      weakness: score(cleanWeaknesses.length, 30),
      threat: score(cleanThreats.length, 30),
    },
    hasData,
    partial: !hasTrendlyne || !news || rsi == null,
    coverage,
    source: hasTrendlyne && hasSnapshot
      ? "trendlyne+snapshot"
      : hasTrendlyne
        ? "trendlyne"
        : hasSnapshot
          ? "snapshot"
          : "none",
  };
}
