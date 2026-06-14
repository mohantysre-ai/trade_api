import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "IROS — Live Market Intelligence Terminal" },
      { name: "description", content: "Real-time global indices, commodities, India markets and AI-driven terminal intelligence." },
      { property: "og:title", content: "IROS Market Intelligence" },
      { property: "og:description", content: "Pro-grade live market terminal with AI thesis and forensic screen." },
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
];

const COMMODITIES: Tick[] = [
  { label: "GOLD", value: "4,238.80", delta: 3.03, unit: "/oz" },
  { label: "SILVER", value: "67.97", delta: 6.21, unit: "/oz" },
  { label: "BRENT CRUDE", value: "87.33", delta: -3.37, unit: "/bbl" },
  { label: "WTI CRUDE", value: "84.88", delta: -3.23, unit: "/bbl" },
  { label: "NATURAL GAS", value: "3.120", delta: 1.07, unit: "/MMBtu" },
];

const INDIA: Tick[] = [
  { label: "NIFTY 50", value: "23,622.90", delta: 1.99 },
  { label: "SENSEX", value: "75,527.95", delta: 2.30 },
  { label: "NIFTY BANK", value: "56,814.80", delta: 2.97 },
  { label: "NIFTY IT", value: "27,795.75", delta: -0.09 },
  { label: "NIFTY PHARMA", value: "24,380.05", delta: 0.30 },
  { label: "USD / INR", value: "95.10", delta: -0.68 },
  { label: "INDIA VIX", value: "14.72", delta: -1.72 },
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
  
  return (
    <div className={`group relative border px-3 py-2.5 transition-colors hover:bg-card ${isPos ? "border-positive hover:border-positive" : isNeg ? "border-negative hover:border-negative" : "border-border hover:border-primary/40"} bg-card/60`}>
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

function IcGates() {
  return (
    <div className="grid gap-4">
      <Panel label="Structured Reasoning Output" status="AVAILABLE">
        <div className="border-b border-border px-4 py-2 font-mono text-[11px] text-muted-foreground">
          Gemini / Pydantic mapped payload from the live ingestion stream.
        </div>

        <div className="grid gap-px bg-border/60 lg:grid-cols-3">
          {[
            {
              h: "News Catalysts",
              b: "Market context for AADHARHFC: top market catalysts were not available from the current news feed.",
            },
            {
              h: "Macro Anchors",
              b: "Macro anchors are drawn from live index action, global market breadth, and commodity/FX benchmarks. The current environment reflects cautious equity allocation with sector-specific headwinds.",
            },
            {
              h: "Insider / Insti Activity",
              b: "Institutional activity inferred from volume spikes and price momentum across the selected cohort. Large-block prints and accumulation patterns are consistent with mid-cap institutional rotation.",
            },
          ].map((c) => (
            <article key={c.h} className="bg-card/40 p-4">
              <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
                {c.h}
              </h3>
              <p className="mt-2 font-mono text-[12px] leading-relaxed text-foreground/80">
                {c.b}
              </p>
            </article>
          ))}
        </div>

        <div className="grid gap-px bg-border/60 lg:grid-cols-2">
          <article className="bg-card/40 p-4">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
              Structural Thesis
            </h3>
            <p className="mt-2 font-mono text-[12px] leading-relaxed text-foreground/80">
              <span className="text-muted-foreground">Why Interested:</span> AADHARHFC is in
              the active terminal universe with LTP ₹473.65, +4.55% move, and volume 542,229.
              Intraday setup: VWAP Bounce, EMA9 unavailable, ATR 0%, volume multiplier 0x.
            </p>
            <p className="mt-3 font-mono text-[12px] leading-relaxed text-foreground/80">
              <span className="text-muted-foreground">Forward Revenue:</span> forward model
              inferred from current sector momentum, order-flow quality, and live liquidity
              participation rather than static multiples.
            </p>
          </article>

          <article className="bg-card/40 p-4">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
              Risk Calc / Factor Hub
            </h3>
            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-[12px]">
              {[
                ["Ticker Score", "91.2"],
                ["Delta %", "4.55"],
                ["ATR %", "0.00"],
                ["Turnover Cr", "0.00"],
                ["Volume Mult", "0.00x"],
                ["Selection Risk", "lower"],
                ["Signal Quality", "live-derived"],
                ["Win/Loss", "5.67 : 1"],
                ["Kelly Max", "10.6%"],
                ["Risk Score", "28"],
                ["Risk Flag", "LOW_RISK"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between border-b border-border/30 pb-1">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="tabular-nums text-foreground">{v}</dd>
                </div>
              ))}
            </dl>
          </article>
        </div>
      </Panel>
    </div>
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

const TABS = ["Market Snapshot", "Asset Matrix", "IC Gates & Reasoning"] as const;
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
        {tab === "Asset Matrix" && <AssetMatrix onSelect={setSelected} />}
        {tab === "IC Gates & Reasoning" && <IcGates />}
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
