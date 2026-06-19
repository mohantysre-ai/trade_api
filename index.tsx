import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";

// @ts-ignore
export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "IROS — Live Market Intelligence Terminal" },
      { name: "description", content: "Real-time global indices, commodities, India markets and AI-driven terminal intelligence." },
      { name: "og:title", content: "IROS Market Intelligence" },
      { name: "og:description", content: "Pro-grade live market terminal with AI thesis and forensic screen." },
    ],
  }),
  component: Index,
});

/* ---------------------------------- data ---------------------------------- */

type Tick = { label: string; value: string; delta: number; unit?: string };

const GLOBAL_INDICES: Tick[] = [
  { label: "DJI (US 30)", value: "51,202.26", delta: 0.7 },
  { label: "S&P 500", value: "7,431.46", delta: 0.5 },
  { label: "NASDAQ 100", value: "29,635.95", delta: 0.64 },
  { label: "NIKKEI 225", value: "66,020.04", delta: 2.81 },
  { label: "HANG SENG", value: "24,718.10", delta: 1.93 },
  { label: "SHANGHAI COMP", value: "4,031.51", delta: 1.12 },
  { label: "DAX", value: "24,635.30", delta: 1.76 },
  { label: "CAC 40", value: "8,350.87", delta: 1.83 },
  { label: "FTSE 100", value: "10,471.72", delta: 1.63 },
  { label: "EURO STOXX 50", value: "6,187.63", delta: 2.16 },
  { label: "S&P/ASX 200", value: "8,912.40", delta: 0.85 },
  { label: "BOVESPA", value: "134,280.00", delta: 1.45 },
];

const COMMODITIES: Tick[] = [
  { label: "GOLD", value: "4,238.80", delta: 3.03, unit: "/oz" },
  { label: "SILVER", value: "67.97", delta: 6.21, unit: "/oz" },
  { label: "BRENT CRUDE", value: "87.33", delta: -3.37, unit: "/bbl" },
  { label: "WTI CRUDE", value: "84.88", delta: -3.23, unit: "/bbl" },
  { label: "NATURAL GAS", value: "3.120", delta: 1.07, unit: "/MMBtu" },
];

const INDIA: Tick[] = [
  { label: "NIFTY 100", value: "23,622.90", delta: 1.99 },
  { label: "SENSEX", value: "75,527.95", delta: 2.30 },
  { label: "NIFTY BANK", value: "56,814.80", delta: 2.97 },
  { label: "NIFTY IT", value: "27,795.75", delta: -0.09 },
  { label: "NIFTY PHARMA", value: "24,380.05", delta: 0.30 },
  { label: "USD / INR", value: "95.10", delta: -0.68 },
  { label: "INDIA VIX", value: "14.72", delta: -1.72 },
];

/* ---------------------------- heatmap data -------------------------------- */

type HeatMapItem = {
  symbol: string;
  price: number;
  changePct: number;
  colorClass: string;
};

const HEATMAP_COLORS = [
  { min: 5, class: "heat-five", label: "5%+" },
  { min: 3, class: "heat-four", label: "3-5%" },
  { min: 2, class: "heat-three", label: "2-3%" },
  { min: 1, class: "heat-two", label: "1-2%" },
  { min: 0, class: "heat-one", label: "0-1%" },
  { min: -1, class: "heat-neg-one", label: "0 to -1%" },
  { min: -2, class: "heat-neg-two", label: "-1 to -2%" },
  { min: -3, class: "heat-neg-three", label: "-2 to -3%" },
  { min: -Infinity, class: "heat-neg-four", label: "< -3%" },
];

function getHeatColor(pct: number): string {
  for (const c of HEATMAP_COLORS) {
    if (pct >= c.min) return c.class;
  }
  return "heat-neg-four";
}

const NIFTY_100_HEATMAP: HeatMapItem[] = [
  { symbol: "MAXHEALTH", price: 1092.45, changePct: 6.46, colorClass: "heat-five" },
  { symbol: "ADANIPOWER", price: 231.90, changePct: 5.22, colorClass: "heat-five" },
  { symbol: "VISL", price: 24.37, changePct: 5.00, colorClass: "heat-four" },
  { symbol: "ADANIGREEN", price: 1517.00, changePct: 3.49, colorClass: "heat-four" },
  { symbol: "UNITDSPR", price: 1352.60, changePct: 3.41, colorClass: "heat-four" },
  { symbol: "ADANIENSOL", price: 1535.80, changePct: 3.00, colorClass: "heat-three" },
  { symbol: "DLF", price: 642.00, changePct: 2.96, colorClass: "heat-three" },
  { symbol: "INDIGO", price: 5014.00, changePct: 2.78, colorClass: "heat-three" },
  { symbol: "ADANIENT", price: 3032.00, changePct: 2.71, colorClass: "heat-three" },
  { symbol: "TRENT", price: 3182.00, changePct: 2.55, colorClass: "heat-three" },
  { symbol: "BEL", price: 428.10, changePct: 1.96, colorClass: "heat-two" },
  { symbol: "BOSCHLTD", price: 39990.00, changePct: 1.94, colorClass: "heat-two" },
  { symbol: "SHREECEM", price: 25445.00, changePct: 1.90, colorClass: "heat-two" },
  { symbol: "TATACAP", price: 343.30, changePct: 1.84, colorClass: "heat-two" },
  { symbol: "BAJAJHLDNG", price: 10690.00, changePct: 1.81, colorClass: "heat-two" },
  { symbol: "NTPC", price: 362.00, changePct: 1.81, colorClass: "heat-two" },
  { symbol: "SOLARINDS", price: 17770.00, changePct: 1.79, colorClass: "heat-two" },
  { symbol: "INDHOTEL", price: 711.50, changePct: 1.77, colorClass: "heat-two" },
  { symbol: "HDFCBANK", price: 800.80, changePct: 1.74, colorClass: "heat-two" },
  { symbol: "HDFCLIFE", price: 591.20, changePct: 1.62, colorClass: "heat-two" },
  { symbol: "DIVISLAB", price: 6768.00, changePct: 1.57, colorClass: "heat-two" },
  { symbol: "SBIN", price: 1042.50, changePct: 1.56, colorClass: "heat-two" },
  { symbol: "AMBUJACEM", price: 432.65, changePct: 1.45, colorClass: "heat-two" },
  { symbol: "UNIONBANK", price: 176.25, changePct: 1.44, colorClass: "heat-two" },
  { symbol: "ZYDUSLIFE", price: 1074.00, changePct: 1.19, colorClass: "heat-two" },
  { symbol: "EICHERMOT", price: 7593.50, changePct: 1.13, colorClass: "heat-two" },
  { symbol: "ABB", price: 7244.00, changePct: 1.12, colorClass: "heat-two" },
  { symbol: "TMCV", price: 407.00, changePct: 1.04, colorClass: "heat-two" },
  { symbol: "TMPV", price: 364.55, changePct: 1.00, colorClass: "heat-one" },
  { symbol: "POWERGRID", price: 289.20, changePct: 1.00, colorClass: "heat-one" },
  { symbol: "NESTLEIND", price: 1400.00, changePct: -0.52, colorClass: "heat-neg-one" },
  { symbol: "M&M", price: 3116.50, changePct: -0.52, colorClass: "heat-neg-one" },
  { symbol: "BPCL", price: 316.25, changePct: -0.53, colorClass: "heat-neg-one" },
  { symbol: "MUTHOOTFIN", price: 3171.90, changePct: -0.59, colorClass: "heat-neg-one" },
  { symbol: "HCLTECH", price: 1159.60, changePct: -0.62, colorClass: "heat-neg-one" },
  { symbol: "COALINDIA", price: 452.30, changePct: -0.76, colorClass: "heat-neg-one" },
  { symbol: "WIPRO", price: 182.95, changePct: -0.82, colorClass: "heat-neg-one" },
  { symbol: "MAZDOCK", price: 2530.00, changePct: -0.88, colorClass: "heat-neg-one" },
  { symbol: "HAL", price: 4420.00, changePct: -0.91, colorClass: "heat-neg-one" },
  { symbol: "TCS", price: 2202.50, changePct: -0.92, colorClass: "heat-neg-one" },
  { symbol: "MARUTI", price: 13505.00, changePct: -0.92, colorClass: "heat-neg-one" },
  { symbol: "TECHM", price: 1447.80, changePct: -1.00, colorClass: "heat-neg-two" },
  { symbol: "CGPOWER", price: 953.00, changePct: -1.12, colorClass: "heat-neg-two" },
  { symbol: "GODREJCP", price: 1008.40, changePct: -1.14, colorClass: "heat-neg-two" },
  { symbol: "TATACONSUM", price: 1111.00, changePct: -1.20, colorClass: "heat-neg-two" },
  { symbol: "VEDPOWER", price: 41.19, changePct: -1.93, colorClass: "heat-neg-two" },
  { symbol: "VBL", price: 532.10, changePct: -2.20, colorClass: "heat-neg-three" },
  { symbol: "VAML", price: 455.00, changePct: -2.23, colorClass: "heat-neg-three" },
  { symbol: "INFY", price: 1127.40, changePct: -2.62, colorClass: "heat-neg-three" },
  { symbol: "VOGL", price: 31.25, changePct: -4.11, colorClass: "heat-neg-four" },
];

type Asset = {
  ticker: string;
  price: number;
  score: number;
  kelly: string;
  ret: number;
  thesis: "BUY" | "HOLD" | "SELL";
};

const ASSETS: Asset[] = [
  { ticker: "AIIL", price: 530.15, score: 98.5, kelly: "5.67 : 1", ret: 16.4, thesis: "BUY" },
  { ticker: "AEGISVOPAK", price: 217.85, score: 96.2, kelly: "5.67 : 1", ret: 16.0, thesis: "BUY" },
  { ticker: "ABDL", price: 644.45, score: 94.1, kelly: "5.67 : 1", ret: 15.7, thesis: "BUY" },
  { ticker: "ABCAPITAL", price: 358.10, score: 93.8, kelly: "5.67 : 1", ret: 15.6, thesis: "BUY" },
  { ticker: "AAVAS", price: 1405.70, score: 92.5, kelly: "5.67 : 1", ret: 15.4, thesis: "BUY" },
  { ticker: "AADHARHFC", price: 473.65, score: 91.2, kelly: "5.67 : 1", ret: 15.2, thesis: "BUY" },
  { ticker: "ACE", price: 931.05, score: 89.7, kelly: "5.67 : 1", ret: 15.0, thesis: "BUY" },
  { ticker: "ADANIPOWER", price: 223.07, score: 88.4, kelly: "5.67 : 1", ret: 14.7, thesis: "BUY" },
  { ticker: "ABLBL", price: 98.34, score: 87.1, kelly: "5.67 : 1", ret: 14.5, thesis: "BUY" },
  { ticker: "360ONE", price: 1096.80, score: 86.5, kelly: "5.67 : 1", ret: 14.4, thesis: "BUY" },
  { ticker: "ABSLAMC", price: 1101.20, score: 85.9, kelly: "5.67 : 1", ret: 14.3, thesis: "BUY" },
  { ticker: "AARTIIND", price: 440.60, score: 84.2, kelly: "5.67 : 1", ret: 14.0, thesis: "BUY" },
  { ticker: "AFCONS", price: 326.00, score: 83.5, kelly: "5.67 : 1", ret: 13.9, thesis: "BUY" },
  { ticker: "ABFRL", price: 59.90, score: 82.1, kelly: "5.67 : 1", ret: 13.7, thesis: "BUY" },
  { ticker: "ACC", price: 1336.60, score: 81.4, kelly: "5.67 : 1", ret: 13.6, thesis: "BUY" },
  { ticker: "ADANIGREEN", price: 1485.70, score: 80.8, kelly: "5.67 : 1", ret: 13.5, thesis: "BUY" },
  { ticker: "AEGISLOG", price: 944.40, score: 79.5, kelly: "5.67 : 1", ret: 13.3, thesis: "BUY" },
  { ticker: "ADANIENSOL", price: 1489.60, score: 78.2, kelly: "5.67 : 1", ret: 13.0, thesis: "BUY" },
  { ticker: "ABREL", price: 1198.40, score: 77.9, kelly: "5.67 : 1", ret: 13.0, thesis: "BUY" },
  { ticker: "ADANIPORTS", price: 1812.90, score: 76.5, kelly: "5.67 : 1", ret: 12.8, thesis: "BUY" },
];

const SOURCES = [
  "REUTERS INDIA", "TRADINGVIEW", "MONEYCONTROL", "INVESTING.COM", "LIVEMINT",
  "ECONOMIC TIMES", "WSJ MARKETS", "FT MARKETS", "CNBC GLOBAL", "YAHOO FINANCE",
  "MARKETWATCH", "NASDAQ", "SEEKING ALPHA", "BENZINGA", "CNN BUSINESS",
  "BARRON'S", "FORTUNE", "BUSINESS STANDARD", "FINANCIAL EXPRESS", "CNBC TV18",
  "THE HINDU", "ZEE BUSINESS", "NSE CORPORATE",
];

/* -------------------------------- helpers --------------------------------- */

const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
const fmtRet = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
const tone = (n: number) =>
  n > 0 ? "text-positive" : n < 0 ? "text-negative" : "text-muted-foreground";

/* -------------------------------- atoms ----------------------------------- */

function TickerCard({ t }: { t: Tick }) {
  const isPos = t.delta > 0;
  const isNeg = t.delta < 0;
  // Use high-contrast border indicators
  const borderColor = isPos ? "border-l-4 border-l-emerald-600" : isNeg ? "border-l-4 border-rose-600" : "border-l-4 border-l-slate-300";
  
  return (
    <div className={`group relative border border-slate-200 px-3 py-2.5 transition-colors hover:bg-slate-50 ${isPos ? "hover:border-l-emerald-600" : isNeg ? "hover:border-l-rose-600" : "hover:border-l-slate-400"} ${borderColor} bg-white`}>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {t.label}
      </div>
      <div className="mt-1 flex items-baseline gap-1 font-mono text-base font-semibold text-foreground tabular-nums">
        {t.unit && t.unit.startsWith("/") ? "" : ""}
        <span>{t.value}</span>
        {t.unit && <span className="text-[11px] font-normal text-muted-foreground">{t.unit}</span>}
      </div>
      <div className={`mt-0.5 font-mono text-[11px] tabular-nums ${tone(t.delta)}`}>
        {fmtPct(t.delta)}
      </div>
    </div>
  );
}

function Panel({
  label,
  status,
  children,
}: {
  label: string;
  status?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-border bg-card/40">
      <header className="flex items-center justify-between border-b border-border px-4 py-2">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          {label}
        </h2>
        {status && (
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-warning">
            {status}
          </span>
        )}
      </header>
      {children}
    </section>
  );
}

/* --------------------------------- views ---------------------------------- */

function MarketSnapshot() {
  return (
    <div className="grid gap-4">
      <Panel label="Global Indices" status="STALE 241M">
        <div className="grid grid-cols-2 gap-px bg-border/60 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
          {GLOBAL_INDICES.map((t) => (
            <TickerCard key={t.label} t={t} />
          ))}
        </div>
      </Panel>

      <Panel label="Commodities & FX" status="STALE 241M">
        <div className="grid grid-cols-2 gap-px bg-border/60 sm:grid-cols-3 lg:grid-cols-5">
          {COMMODITIES.map((t) => (
            <TickerCard key={t.label} t={t} />
          ))}
        </div>
      </Panel>

      <Panel label="India Markets" status="STALE 241M">
        <div className="grid grid-cols-2 gap-px bg-border/60 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-7">
          {INDIA.map((t) => (
            <TickerCard key={t.label} t={t} />
          ))}
        </div>
      </Panel>

    </div>
  );
}

function AssetMatrix({ onSelect }: { onSelect: (a: Asset) => void }) {
  const [q, setQ] = useState("");
  const rows = useMemo(
    () => ASSETS.filter((a) => a.ticker.toLowerCase().includes(q.toLowerCase())),
    [q],
  );
  const avgKelly = "5.67 : 1";
  const topRet = Math.max(...ASSETS.map((a) => a.ret));

  return (
    <Panel label="Asset Matrix">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
        <span>Active Nodes <span className="text-foreground">{ASSETS.length}</span></span>
        <span>· Avg Kelly <span className="text-foreground">{avgKelly}</span></span>
        <span>· Top Return <span className="text-positive">{fmtRet(topRet)}</span></span>
        <span>· Data Date <span className="text-foreground">2026-06-14</span></span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="filter ticker…"
          className="ml-auto w-44 border border-border bg-background/60 px-2 py-1 font-mono text-[11px] text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full font-mono text-[12px]">
          <thead>
            <tr className="border-b border-border text-left text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <th className="px-4 py-2 font-normal">Ticker</th>
              <th className="px-4 py-2 font-normal text-right">Price</th>
              <th className="px-4 py-2 font-normal text-right">Score</th>
              <th className="px-4 py-2 font-normal text-right">Kelly</th>
              <th className="px-4 py-2 font-normal text-right">Return</th>
              <th className="px-4 py-2 font-normal">Thesis</th>
              <th className="px-4 py-2 font-normal" />
            </tr>
          </thead>
          <tbody>
            {rows.map((a, i) => (
              <tr
                key={a.ticker}
                onClick={() => onSelect(a)}
                className={`cursor-pointer border-b border-border/40 transition-colors hover:bg-primary/5 ${
                  i % 2 === 0 ? "bg-card/20" : ""
                }`}
              >
                <td className="px-4 py-2 font-semibold text-foreground">{a.ticker}</td>
                <td className="px-4 py-2 text-right tabular-nums">₹{a.price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                <td className="px-4 py-2 text-right tabular-nums text-positive">{a.score.toFixed(1)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{a.kelly}</td>
                <td className="px-4 py-2 text-right tabular-nums text-positive">{fmtRet(a.ret)}</td>
                <td className="px-4 py-2">
                  <span className="border border-positive/40 bg-positive/10 px-1.5 py-0.5 text-[10px] tracking-[0.14em] text-positive">
                    {a.thesis}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-muted-foreground">›</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function DetailDrawer({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  return (
    <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-border bg-background shadow-2xl">
      <header className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <h2 className="font-mono text-lg font-semibold tracking-wide text-primary">
            {asset.ticker}
          </h2>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Active Terminal Node
          </p>
        </div>
        <button
          onClick={onClose}
          className="border border-border px-2 py-1 font-mono text-xs text-muted-foreground hover:border-primary hover:text-primary"
        >
          ESC ×
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        <div className="border border-border bg-card/40 p-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Last Price
          </div>
          <div className="mt-1 flex items-baseline gap-3 font-mono tabular-nums">
            <span className="text-3xl font-semibold text-foreground">
              ₹{asset.price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            </span>
            <span className="text-positive">+4.55%</span>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-px bg-border/60 font-mono text-[11px]">
            {[
              ["OPEN", "460.00"],
              ["HIGH", "476.20"],
              ["LOW", "458.00"],
            ].map(([k, v]) => (
              <div key={k} className="bg-card/60 p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{k}</div>
                <div className="mt-1 tabular-nums text-foreground">{v}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="border border-border bg-card/40 p-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
            Terminal Intelligence Payload
          </div>
          <div className="mt-3 space-y-3 font-mono text-[12px] leading-relaxed text-foreground/80">
            <p>
              <span className="text-muted-foreground">Focus.</span> {asset.ticker} is in the
              active terminal universe with LTP ₹{asset.price.toFixed(2)}, +4.55% move and
              volume 542,229. Intraday setup: VWAP Bounce, EMA9 unavailable, ATR 0%, volume
              multiplier 0x.
            </p>
            <p>
              <span className="text-muted-foreground">Forensic Screen.</span> Beneish M
              −0.41, Altman Z 2.85, OCF/EBITDA 0.67, Mansfield Relative Strength 0.76.
            </p>
            <p>
              <span className="text-muted-foreground">Selection Reason.</span> mixed trend
              around intraday anchors; delta 4.55% with score {asset.score}; volume 0.00× with
              limited turnover visibility; contained volatility; trigger VWAP Bounce;
              watch-list hard-filter state.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="border border-border bg-card/40 p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Market Sentiment
            </div>
            <div className="mt-2 font-mono text-2xl text-warning">Neutral</div>
          </div>
          <div className="border border-border bg-card/40 p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Risk Flags
            </div>
            <div className="mt-2 font-mono text-sm text-positive">No significant risks flagged</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* ---------------------------------- root ---------------------------------- */

/* ----------------------------- heat map view ------------------------------ */

function HeatMapView() {
  return (
    <div className="grid gap-4">
      <Panel label="NIFTY 100 Heat Map">
        <div className="flex flex-wrap">
          {NIFTY_100_HEATMAP.map((item) => (
            <a
              key={item.symbol}
              href={`/get-quotes/equity?symbol=${item.symbol}`}
              target="_blank"
              rel="noopener noreferrer"
              className={`heatmap-tile ${item.colorClass}`}
            >
              <div className="compName">
                <span className="indexName">{item.symbol}</span>
              </div>
              <div className="tooltipIndexData">
                <span className="currentPrice">{item.price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                <span className="perChange">{item.changePct >= 0 ? "+" : ""}{item.changePct.toFixed(2)}%</span>
              </div>
            </a>
          ))}
        </div>
        {/* color legend */}
        <div className="flex flex-wrap gap-3 border-t border-border px-4 py-3 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          {HEATMAP_COLORS.map((c) => (
            <span key={c.class} className="flex items-center gap-1.5">
              <span className={`inline-block h-3 w-3 rounded-sm ${c.class}`} />
              {c.label}
            </span>
          ))}
        </div>
      </Panel>
    </div>
  );
}

/* ---------------------------------- root ---------------------------------- */

const TABS = ["Market Snapshot", "NIFTY 100 Heat Map", "Asset Matrix"] as const;
type Tab = (typeof TABS)[number];

function Index() {
  const [tab, setTab] = useState<Tab>("Market Snapshot");
  const [selected, setSelected] = useState<Asset | null>(null);

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* top status bar */}
      <div className="border-b border-border bg-card/30">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          <span className="flex items-center gap-2 text-primary">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
            IROS LIVE · MARKET INTELLIGENCE
          </span>
          <span className="hidden text-foreground/60 md:inline">v1.4.0 · session 0xA7F2</span>
          <span className="ml-auto flex items-center gap-3">
            <span>17:45:03 IST</span>
            <button className="border border-primary/40 bg-primary/10 px-3 py-1 text-primary hover:bg-primary/20">
              Snapshot
            </button>
          </span>
        </div>

        {/* sources marquee */}
        <div className="overflow-hidden border-t border-border">
          <div className="flex animate-[scroll_60s_linear_infinite] gap-8 whitespace-nowrap px-6 py-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            {[...SOURCES, ...SOURCES].map((s, i) => (
              <span key={i} className="flex items-center gap-3">
                <span className="h-1 w-1 rounded-full bg-primary/60" />
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>

      <main className="mx-auto max-w-[1600px] px-6 py-6">
        {/* fallback banner */}
        <div className="mb-5 border border-warning/30 bg-warning/10 px-4 py-2.5 font-mono text-[11px] text-warning">
          ⚠ Snapshot fallback active — outside scheduled IST refresh window. Showing latest
          saved analysis.
        </div>

        {/* tabs */}
        <nav className="mb-5 flex border-b border-border">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative px-5 py-2.5 font-mono text-[11px] uppercase tracking-[0.18em] transition-colors ${
                tab === t
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t}
              {tab === t && (
                <span className="absolute inset-x-0 -bottom-px h-[2px] bg-primary" />
              )}
            </button>
          ))}
        </nav>

        {tab === "Market Snapshot" && <MarketSnapshot />}
        {tab === "NIFTY 100 Heat Map" && <HeatMapView />}
        {tab === "Asset Matrix" && <AssetMatrix onSelect={setSelected} />}
      </main>

      {selected && (
        <>
          <div
            className="fixed inset-0 z-40 bg-background/70 backdrop-blur-sm"
            onClick={() => setSelected(null)}
          />
          <DetailDrawer asset={selected} onClose={() => setSelected(null)} />
        </>
      )}

      <style>{`
        @keyframes scroll {
          from { transform: translateX(0); }
          to { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
