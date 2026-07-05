import { NextResponse } from "next/server";

export const runtime = "nodejs";

/* Map of index labels (uppercased) to Moneycontrol symbol codes */
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

function resolveSymbol(label: string): string | null {
  const upper = label.toUpperCase().trim();
  if (MC_SYMBOL_MAP[upper]) return MC_SYMBOL_MAP[upper];
  /* fuzzy match */
  for (const [key, val] of Object.entries(MC_SYMBOL_MAP)) {
    if (upper.includes(key) || key.includes(upper)) return val;
  }
  return null;
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const label = url.searchParams.get("label");
    if (!label) {
      return NextResponse.json({ error: "label param required" }, { status: 400 });
    }

    const symbol = resolveSymbol(label);
    if (!symbol) {
      return NextResponse.json({ error: `No Moneycontrol symbol for "${label}"`, sparkline: [] }, { status: 200 });
    }

    const to = Math.floor(Date.now() / 1000);
    const from = to - 30 * 24 * 60 * 60; // 30 days ago

    /* GIFT NIFTY uses a different API endpoint (global market intra) */
    const isGlobalSymbol = symbol === 'in;gsx';
    const mcUrl = isGlobalSymbol
      ? `https://priceapi.moneycontrol.com/globaltechCharts/globalMarket/index/intra?symbol=${encodeURIComponent(symbol)}&duration=1D&firstCall=true`
      : `https://priceapi.moneycontrol.com/techCharts/indianMarket/index/history?symbol=${encodeURIComponent(symbol)}&resolution=1D&from=${from}&to=${to}&countback=30&currencyCode=INR`;

    const res = await fetch(mcUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Referer: "https://www.moneycontrol.com/",
      },
      cache: "no-store",
    });

    if (!res.ok) {
      return NextResponse.json({ error: `Moneycontrol HTTP ${res.status}`, sparkline: [] }, { status: 200 });
    }

    const data = await res.json();
    if (data.s !== "ok") {
      return NextResponse.json({ error: "No chart data available", sparkline: [] }, { status: 200 });
    }

    /* Handle two response formats:
     * 1. History API: { s:"ok", c: [number, ...] }
     * 2. Intra API:   { s:"ok", data: [{time, value}, ...] } */
    let sparkline: number[] = [];
    if (Array.isArray(data.c) && data.c.length >= 2) {
      sparkline = data.c as number[];
    } else if (Array.isArray(data.data) && data.data.length >= 2) {
      sparkline = data.data.map((d: { time: number; value: number }) => d.value);
    }

    if (sparkline.length < 2) {
      return NextResponse.json({ error: "No chart data available", sparkline: [] }, { status: 200 });
    }

    return NextResponse.json({ sparkline, label, symbol });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message, sparkline: [] }, { status: 200 });
  }
}