import type { AITickerNewsReport, TerminalIntelligence } from "@/lib/market-api";

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

export function buildTechnicalSignals(
  intraday?: IntradayMetrics | null,
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
} {
  const rsi = parseNumeric(intraday?.rsi);
  const atr = parseNumeric(intraday?.atr_pct);
  const volMult = parseNumeric(intraday?.volume_multiplier);
  const aboveVwap = intraday?.price_above_vwap ?? null;
  const aboveEma9 = intraday?.price_above_ema9 ?? null;

  let maSignal: "BUY" | "SELL" | "NEUTRAL" = "NEUTRAL";
  if (aboveVwap === true && aboveEma9 === true) maSignal = "BUY";
  else if (aboveVwap === false && aboveEma9 === false) maSignal = "SELL";

  const macd =
    aboveVwap === true && aboveEma9 === true
      ? 1
      : aboveVwap === false && aboveEma9 === false
        ? -1
        : aboveVwap != null || aboveEma9 != null
          ? 0.2
          : null;

  const strength = rsi != null ? Math.min(100, Math.max(0, rsi)) : null;
  const volume = volMult != null ? Math.min(100, Math.max(0, volMult * 25)) : null;
  const volatility = atr != null ? Math.min(100, Math.max(0, atr * 20)) : null;
  const hasData = rsi != null || atr != null || volMult != null || aboveVwap != null || aboveEma9 != null;

  return {
    rsi,
    macd,
    stochastic: rsi,
    maSignal,
    strength,
    volume,
    volatility,
    hasData,
    aboveVwap,
    aboveEma9,
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
  if (!trimmed || trimmed.toLowerCase() === "no recent news found.") return null;
  return trimmed;
}

export function buildFactSwot(params: {
  ticker: string;
  intraday?: IntradayMetrics | null;
  tickerNews?: AITickerNewsReport | null;
  terminalAnalysis?: TerminalIntelligence | null;
  stock?: DrawerStockFacts | null;
}): {
  strengths: string[];
  weaknesses: string[];
  opportunities: string[];
  threats: string[];
  scores: {
    overall: number;
    strength: number;
    opportunity: number;
    weakness: number;
    threat: number;
  };
  hasData: boolean;
  partial: boolean;
} {
  const strengths: string[] = [];
  const weaknesses: string[] = [];
  const opportunities: string[] = [];
  const threats: string[] = [];
  const intra = params.intraday;
  const news = params.tickerNews;
  const stock = params.stock;

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

  const hasData = strengths.length + weaknesses.length + opportunities.length + threats.length > 0;
  const balance = strengths.length + opportunities.length - weaknesses.length - threats.length;
  const overall = hasData ? Math.round(Math.min(92, Math.max(12, 50 + balance * 7))) : 0;

  return {
    strengths: strengths.slice(0, 5),
    weaknesses: weaknesses.slice(0, 5),
    opportunities: opportunities.slice(0, 5),
    threats: threats.slice(0, 5),
    scores: {
      overall,
      strength: strengths.length ? Math.min(88, 35 + strengths.length * 11) : 0,
      opportunity: opportunities.length ? Math.min(88, 35 + opportunities.length * 11) : 0,
      weakness: weaknesses.length ? Math.min(88, 30 + weaknesses.length * 11) : 0,
      threat: threats.length ? Math.min(88, 30 + threats.length * 11) : 0,
    },
    hasData,
    partial: !news || rsi == null,
  };
}
