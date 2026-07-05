import React, { useState, useEffect, useRef } from "react";
import { Search, Radio, ExternalLink } from "lucide-react";

/**
 * IROS Wire — live market news feed
 * ----------------------------------
 * Design notes:
 * - Ground truth: a wire-service / trading-terminal feed, not a blog list.
 * - Signature element: the left "pulse strip" on each card encodes BOTH
 *   sentiment (color) and impact (thickness) — a direct visual readout of
 *   the same composite scoring your Stage 1/2 pipeline already computes
 *   (35% news sentiment + 35% Trendlyne + 30% IC gates).
 * - Fonts: IBM Plex Sans Condensed (headlines, dense/wire feel),
 *   IBM Plex Sans (body), IBM Plex Mono (tickers, timestamps, scores).
 *   In your real Next.js app, load these via next/font/google instead of
 *   the @import below (kept here only so this file previews standalone).
 * - Colors use Tailwind's default zinc/amber/emerald/red palette rather
 *   than arbitrary hex values, for portability into your existing
 *   Tailwind config without extra setup.
 */

const FONT_IMPORT = `
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600;700&display=swap');

@keyframes slideInFade {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes flashAmber {
  0% { box-shadow: 0 0 0 1px rgba(251, 191, 36, 0); }
  30% { box-shadow: 0 0 0 1px rgba(251, 191, 36, 0.6); }
  100% { box-shadow: 0 0 0 1px rgba(251, 191, 36, 0); }
}
`;

const FONT = {
  display: "'IBM Plex Sans Condensed', sans-serif",
  body: "'IBM Plex Sans', sans-serif",
  mono: "'IBM Plex Mono', monospace",
};

const SENTIMENT_STYLES = {
  bullish: { bar: "bg-emerald-500", text: "text-emerald-400", label: "BULLISH" },
  bearish: { bar: "bg-red-500", text: "text-red-400", label: "BEARISH" },
  neutral: { bar: "bg-slate-500", text: "text-slate-400", label: "NEUTRAL" },
};

const IMPACT_WIDTH = { high: "w-1.5", medium: "w-1", low: "w-0.5" };

const SEED_STORIES = [
  {
    id: "s1", time: "2m", source: "Reuters India", sentiment: "bullish", impact: "high", score: 78,
    headline: "HCL Technologies beats Street estimates, guidance revision lifts IT pack",
    snippet: "Q1 revenue growth of 8.2% YoY beat consensus by 140bps; management raised FY guidance citing deal pipeline strength.",
    tickers: [{ sym: "HCLTECH", delta: 5.74 }, { sym: "TECHM", delta: 1.57 }, { sym: "WIPRO", delta: 1.03 }],
  },
  {
    id: "s2", time: "6m", source: "CNBC-TV18", sentiment: "bearish", impact: "high", score: -84,
    headline: "PowerIndia tumbles on large order cancellation from state utility",
    snippet: "Client cited execution delays; brokerages flag near-term revenue visibility risk pending management clarification.",
    tickers: [{ sym: "POWERINDIA", delta: -8.08 }],
  },
  {
    id: "s3", time: "11m", source: "Moneycontrol", sentiment: "bullish", impact: "medium", score: 41,
    headline: "Aurobindo Pharma gets USFDA nod for key oncology generic",
    snippet: "Approval opens a ~$400M addressable US market; launch timeline still pending pricing strategy.",
    tickers: [{ sym: "AUROPHARMA", delta: 3.37 }],
  },
  {
    id: "s4", time: "18m", source: "PTI", sentiment: "neutral", impact: "low", score: 6,
    headline: "RBI keeps repo rate unchanged, tone stays data-dependent",
    snippet: "MPC statement largely in line with expectations; bond yields flat, banking names show muted reaction.",
    tickers: [{ sym: "HDFCBANK", delta: 0.70 }, { sym: "ICICIBANK", delta: 0.91 }, { sym: "SBILIFE", delta: 0.31 }],
  },
  {
    id: "s5", time: "24m", source: "Economic Times", sentiment: "bearish", impact: "medium", score: -37,
    headline: "CG Power slides as promoter pledge disclosure raises governance flags",
    snippet: "Exchange filing shows increased pledged holding; no comment yet from company on repayment plans.",
    tickers: [{ sym: "CGPOWER", delta: -4.62 }],
  },
  {
    id: "s6", time: "31m", source: "Bloomberg Quint", sentiment: "bullish", impact: "low", score: 22,
    headline: "Adani Enterprises unit signs MoU for green hydrogen pilot plant",
    snippet: "Early-stage agreement, capex undisclosed; market treating as long-dated optionality rather than near-term catalyst.",
    tickers: [{ sym: "ADANIENT", delta: 1.02 }],
  },
  {
    id: "s7", time: "39m", source: "Reuters India", sentiment: "bearish", impact: "high", score: -69,
    headline: "Union Bank of India drops on unexpected NPA slippage in SME book",
    snippet: "Q1 asset quality commentary missed expectations; management call scheduled for later today.",
    tickers: [{ sym: "UNIONBANK", delta: -3.70 }, { sym: "PNB", delta: -1.52 }],
  },
];

const QUEUE = [
  {
    id: "q1", time: "just now", source: "CNBC-TV18", sentiment: "bullish", impact: "medium", score: 55,
    headline: "Sun Pharma gains on positive Phase III trial readout",
    snippet: "Trial met primary endpoint; regulatory filing expected within two quarters per management commentary.",
    tickers: [{ sym: "SUNPHARMA", delta: 1.92 }],
  },
  {
    id: "q2", time: "just now", source: "Moneycontrol", sentiment: "neutral", impact: "low", score: -4,
    headline: "Nifty IT index flat as rupee holds steady against dollar",
    snippet: "Currency stability offsetting margin pressure narrative; sector rotation muted through the session.",
    tickers: [{ sym: "INFY", delta: 0.60 }, { sym: "TCS", delta: 0.96 }],
  },
];

function TickerChip({ sym, delta }) {
  const positive = delta >= 0;
  return (
    <a
      href={`https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(sym)}`}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center gap-1 rounded px-2 py-1 border transition-colors
        ${positive ? "border-emerald-800 bg-emerald-950 hover:bg-emerald-900" : "border-red-800 bg-red-950 hover:bg-red-900"}`}
      style={{ fontFamily: FONT.mono }}
    >
      <span className="text-xs font-medium text-zinc-100">{sym}</span>
      <span className={`text-xs ${positive ? "text-emerald-400" : "text-red-400"}`}>
        {positive ? "+" : ""}{delta.toFixed(2)}
      </span>
      <ExternalLink className="w-3 h-3 text-zinc-500" />
    </a>
  );
}

function SentimentMeter({ score }) {
  const clamped = Math.max(-100, Math.min(100, score));
  const positive = clamped >= 0;
  const width = Math.abs(clamped) / 2; // half-width max since bar spans center
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] tracking-wider text-zinc-500" style={{ fontFamily: FONT.mono }}>SENTIMENT</span>
      <div className="relative w-24 h-2 bg-zinc-800 rounded-sm overflow-hidden">
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-zinc-600" />
        <div
          className={`absolute top-0 bottom-0 ${positive ? "bg-emerald-500 left-1/2" : "bg-red-500 right-1/2"}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className={`text-xs font-medium ${positive ? "text-emerald-400" : "text-red-400"}`} style={{ fontFamily: FONT.mono }}>
        {positive ? "+" : ""}{score}
      </span>
    </div>
  );
}

function StoryCard({ story, isNew }) {
  const sentiment = SENTIMENT_STYLES[story.sentiment];
  const barWidth = IMPACT_WIDTH[story.impact];

  return (
    <div
      className="flex bg-zinc-900 border border-zinc-800 rounded-md overflow-hidden hover:border-zinc-700 transition-colors"
      style={isNew ? { animation: "slideInFade 0.4s ease-out, flashAmber 1.6s ease-out" } : undefined}
    >
      <div className={`${barWidth} ${sentiment.bar} shrink-0`} />
      <div className="flex-1 px-4 py-3">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[11px] tracking-wide text-zinc-500" style={{ fontFamily: FONT.mono }}>
            {story.time.toUpperCase() === "JUST NOW" ? story.time : `${story.time} AGO`}
          </span>
          <span className="text-zinc-700">·</span>
          <span className="text-[11px] text-zinc-500" style={{ fontFamily: FONT.mono }}>{story.source}</span>
          <span className={`ml-auto text-[10px] font-semibold tracking-wider px-1.5 py-0.5 rounded ${sentiment.text} bg-zinc-800`} style={{ fontFamily: FONT.mono }}>
            {sentiment.label} · {story.impact.toUpperCase()}
          </span>
        </div>

        <h3
          className="text-zinc-100 font-semibold leading-snug mb-1"
          style={{ fontFamily: FONT.display, fontSize: "17px" }}
        >
          {story.headline}
        </h3>

        <p className="text-sm text-zinc-400 mb-3" style={{ fontFamily: FONT.body }}>
          {story.snippet}
        </p>

        <div className="flex items-center justify-between flex-wrap gap-y-2">
          <div className="flex flex-wrap gap-1.5">
            {story.tickers.map((t) => (
              <TickerChip key={t.sym} sym={t.sym} delta={t.delta} />
            ))}
          </div>
          <SentimentMeter score={story.score} />
        </div>
      </div>
    </div>
  );
}

function FilterPill({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded-full text-xs font-medium transition-colors border
        ${active ? "bg-amber-500 border-amber-500 text-zinc-950" : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"}`}
      style={{ fontFamily: FONT.mono }}
    >
      {children}
    </button>
  );
}

export default function NewsWire() {
  const [stories, setStories] = useState(SEED_STORIES);
  const [newIds, setNewIds] = useState(new Set());
  const [sentimentFilter, setSentimentFilter] = useState("all");
  const [impactFilter, setImpactFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [syncTime, setSyncTime] = useState(new Date());
  const queueRef = useRef([...QUEUE]);

  useEffect(() => {
    const interval = setInterval(() => {
      if (queueRef.current.length === 0) return;
      const next = queueRef.current.shift();
      setStories((prev) => [next, ...prev]);
      setNewIds((prev) => new Set(prev).add(next.id));
      setSyncTime(new Date());
      setTimeout(() => {
        setNewIds((prev) => {
          const copy = new Set(prev);
          copy.delete(next.id);
          return copy;
        });
      }, 1800);
    }, 9000);
    return () => clearInterval(interval);
  }, []);

  const filtered = stories.filter((s) => {
    if (sentimentFilter !== "all" && s.sentiment !== sentimentFilter) return false;
    if (impactFilter !== "all" && s.impact !== impactFilter) return false;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      const inHeadline = s.headline.toLowerCase().includes(q);
      const inTicker = s.tickers.some((t) => t.sym.toLowerCase().includes(q));
      if (!inHeadline && !inTicker) return false;
    }
    return true;
  });

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100" style={{ fontFamily: FONT.body }}>
      <style>{FONT_IMPORT}</style>

      {/* Header */}
      <div className="sticky top-0 z-20 bg-zinc-950/95 backdrop-blur border-b border-zinc-800">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Radio className="w-4 h-4 text-amber-500" />
            <span className="font-bold tracking-tight" style={{ fontFamily: FONT.display, fontSize: "18px" }}>
              IROS WIRE
            </span>
          </div>
          <span className="flex items-center gap-1.5 text-xs text-emerald-400 font-medium" style={{ fontFamily: FONT.mono }}>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            LIVE
          </span>
          <span className="ml-auto text-xs text-zinc-500" style={{ fontFamily: FONT.mono }}>
            {stories.length} stories · synced {syncTime.toLocaleTimeString("en-IN", { hour12: false })} IST
          </span>
        </div>

        {/* Filters */}
        <div className="max-w-3xl mx-auto px-4 pb-3 flex flex-wrap items-center gap-2">
          <FilterPill active={sentimentFilter === "all"} onClick={() => setSentimentFilter("all")}>ALL</FilterPill>
          <FilterPill active={sentimentFilter === "bullish"} onClick={() => setSentimentFilter("bullish")}>BULLISH</FilterPill>
          <FilterPill active={sentimentFilter === "bearish"} onClick={() => setSentimentFilter("bearish")}>BEARISH</FilterPill>
          <FilterPill active={sentimentFilter === "neutral"} onClick={() => setSentimentFilter("neutral")}>NEUTRAL</FilterPill>
          <span className="w-px h-4 bg-zinc-800 mx-1" />
          <FilterPill active={impactFilter === "all"} onClick={() => setImpactFilter("all")}>ANY IMPACT</FilterPill>
          <FilterPill active={impactFilter === "high"} onClick={() => setImpactFilter("high")}>HIGH</FilterPill>
          <FilterPill active={impactFilter === "medium"} onClick={() => setImpactFilter("medium")}>MED</FilterPill>
          <FilterPill active={impactFilter === "low"} onClick={() => setImpactFilter("low")}>LOW</FilterPill>

          <div className="relative ml-auto">
            <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="ticker or keyword"
              className="pl-7 pr-3 py-1 bg-zinc-900 border border-zinc-700 rounded-full text-xs text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-amber-500 w-40"
              style={{ fontFamily: FONT.mono }}
            />
          </div>
        </div>
      </div>

      {/* Feed */}
      <div className="max-w-3xl mx-auto px-4 py-4 flex flex-col gap-3">
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-zinc-500">
            <p style={{ fontFamily: FONT.display, fontSize: "16px" }}>No stories match this filter.</p>
            <p className="text-sm mt-1" style={{ fontFamily: FONT.body }}>
              The tape's not silent — just narrower than you're looking. Try widening the sentiment or impact filter.
            </p>
          </div>
        ) : (
          filtered.map((s) => <StoryCard key={s.id} story={s} isNew={newIds.has(s.id)} />)
        )}
      </div>
    </div>
  );
}
