import { NextResponse } from "next/server";

export const runtime = "nodejs";

const MC_SYMBOL_MAP: Record<string, string> = {
  "NIFTY 50": "in;nsx",
  "NIFTY": "in;nsx",
  "SENSEX": "in;bsx",
  "NIFTY BANK": "in;nbx",
  "NIFTY IT": "in;nitx",
  "NIFTY PHARMA": "in;niftypharma",
  "NIFTY MIDCAP 100": "in;midcp",
  "NIFTY MIDCAP": "in;midcp",
  "NIFTY SMALLCAP 100": "in;cnxs",
  "NIFTY SMALLCAP": "in;cnxs",
  "NIFTY 100": "in;nsx100",
  "GIFT NIFTY": "in;gsx",
  "INDIA VIX": "in;vix",
  "USD / INR": "in;usdinr",
  "USD/INR": "in;usdinr",
  "USD / INR SPOT": "in;usdinr",
};

const YAHOO_SYMBOL_MAP: Record<string, string> = {
  "DJI (US 30)": "^DJI",
  "DJI": "^DJI",
  "DOW JONES": "^DJI",
  "S&P 500": "^GSPC",
  "NASDAQ 100": "^NDX",
  "NIKKEI 225": "^N225",
  "HANG SENG": "^HSI",
  "SHANGHAI COMP": "000001.SS",
  "DAX": "^GDAXI",
  "CAC 40": "^FCHI",
  "FTSE 100": "^FTSE",
  "EURO STOXX 50": "^STOXX50E",
  "S&P/ASX 200": "^AXJO",
  "BOVESPA": "^BVSP",
  "KOSPI": "^KS11",
  "GOLD": "GC=F",
  "SILVER": "SI=F",
  "BRENT CRUDE": "BZ=F",
  "BRENT CRUDE OIL": "BZ=F",
  "WTI CRUDE": "CL=F",
  "NATURAL GAS": "NG=F",
  "BITCOIN": "BTC-USD",
  "COPPER": "HG=F",
  "PLATINUM": "PL=F",
  "PALLADIUM": "PA=F",
  "WHEAT": "ZW=F",
};

type RangeKey = "1D" | "1W" | "1M" | "3M" | "1Y" | "5Y";

const RANGE_CONFIG: Record<RangeKey, { seconds: number; mcResolution: string; countback: number; yahooRange: string; yahooInterval: string }> = {
  "1D": { seconds: 2 * 24 * 60 * 60, mcResolution: "5", countback: 160, yahooRange: "1d", yahooInterval: "5m" },
  "1W": { seconds: 8 * 24 * 60 * 60, mcResolution: "30", countback: 180, yahooRange: "5d", yahooInterval: "15m" },
  "1M": { seconds: 35 * 24 * 60 * 60, mcResolution: "1D", countback: 35, yahooRange: "1mo", yahooInterval: "1d" },
  "3M": { seconds: 100 * 24 * 60 * 60, mcResolution: "1D", countback: 100, yahooRange: "3mo", yahooInterval: "1d" },
  "1Y": { seconds: 370 * 24 * 60 * 60, mcResolution: "1D", countback: 370, yahooRange: "1y", yahooInterval: "1d" },
  "5Y": { seconds: 5 * 370 * 24 * 60 * 60, mcResolution: "1W", countback: 280, yahooRange: "5y", yahooInterval: "1wk" },
};

function normalizeLabel(label: string) {
  return label.toUpperCase().replace(/\s+/g, " ").trim();
}

function resolveMoneycontrolSymbol(label: string): string | null {
  const upper = normalizeLabel(label);
  if (MC_SYMBOL_MAP[upper]) return MC_SYMBOL_MAP[upper];
  for (const [key, val] of Object.entries(MC_SYMBOL_MAP)) {
    if (upper.includes(key) || key.includes(upper)) return val;
  }
  return null;
}

function resolveYahooSymbol(label: string): string | null {
  const upper = normalizeLabel(label);
  if (YAHOO_SYMBOL_MAP[upper]) return YAHOO_SYMBOL_MAP[upper];
  for (const [key, val] of Object.entries(YAHOO_SYMBOL_MAP)) {
    if (upper.includes(key) || key.includes(upper)) return val;
  }
  return null;
}

function downsample(values: number[], maxPoints = 120): number[] {
  if (values.length <= maxPoints) return values;
  const stride = Math.ceil(values.length / maxPoints);
  const sampled = values.filter((_, index) => index % stride === 0);
  const last = values[values.length - 1];
  if (sampled[sampled.length - 1] !== last) sampled.push(last);
  return sampled;
}

async function fetchYahoo(symbol: string, range: RangeKey): Promise<number[]> {
  const cfg = RANGE_CONFIG[range];
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${cfg.yahooRange}&interval=${cfg.yahooInterval}&includePrePost=false&events=div%2Csplits`;
  const res = await fetch(url, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
    headers: { "User-Agent": "Mozilla/5.0" },
  });
  if (!res.ok) return [];
  const data = await res.json();
  const closes = data?.chart?.result?.[0]?.indicators?.quote?.[0]?.close;
  if (!Array.isArray(closes)) return [];
  return downsample(closes.filter((value: unknown): value is number => typeof value === "number" && Number.isFinite(value)));
}

async function fetchMoneycontrol(symbol: string, range: RangeKey): Promise<number[]> {
  const cfg = RANGE_CONFIG[range];
  const to = Math.floor(Date.now() / 1000);
  const from = to - cfg.seconds;
  const isGlobalSymbol = symbol === "in;gsx";
  const mcUrl = isGlobalSymbol && range === "1D"
    ? `https://priceapi.moneycontrol.com/globaltechCharts/globalMarket/index/intra?symbol=${encodeURIComponent(symbol)}&duration=1D&firstCall=true`
    : `https://priceapi.moneycontrol.com/techCharts/indianMarket/index/history?symbol=${encodeURIComponent(symbol)}&resolution=${cfg.mcResolution}&from=${from}&to=${to}&countback=${cfg.countback}&currencyCode=INR`;

  const res = await fetch(mcUrl, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      Referer: "https://www.moneycontrol.com/",
    },
  });
  if (!res.ok) return [];
  const data = await res.json();
  let values: number[] = [];
  if (Array.isArray(data?.c)) {
    values = data.c.filter((value: unknown): value is number => typeof value === "number" && Number.isFinite(value));
  } else if (Array.isArray(data?.data)) {
    values = data.data
      .map((row: { value?: unknown }) => row.value)
      .filter((value: unknown): value is number => typeof value === "number" && Number.isFinite(value));
  }
  return downsample(values);
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const label = url.searchParams.get("label");
    const rawRange = (url.searchParams.get("range") || "1D").toUpperCase();
    const range: RangeKey = rawRange in RANGE_CONFIG ? rawRange as RangeKey : "1D";
    if (!label) return NextResponse.json({ error: "label param required" }, { status: 400 });

    const mcSymbol = resolveMoneycontrolSymbol(label);
    const yahooSymbol = resolveYahooSymbol(label);
    let sparkline: number[] = [];
    let source = "";

    if (mcSymbol) {
      sparkline = await fetchMoneycontrol(mcSymbol, range);
      source = "moneycontrol";
    }
    if (sparkline.length < 2 && yahooSymbol) {
      sparkline = await fetchYahoo(yahooSymbol, range);
      source = "yahoo";
    }

    if (sparkline.length < 2) {
      return NextResponse.json({ error: `No chart data available for "${label}"`, sparkline: [], label, range }, { status: 200 });
    }
    return NextResponse.json({ sparkline, label, range, source, symbol: mcSymbol || yahooSymbol });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message, sparkline: [] }, { status: 200 });
  }
}
