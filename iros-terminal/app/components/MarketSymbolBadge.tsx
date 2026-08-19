import React from "react";

const INDEX_MARKS: Array<[RegExp, string]> = [
  [/INDIA\s*VIX|\bVIX\b/i, "VIX"],
  [/BANK\s*NIFTY|NIFTY\s*BANK/i, "BN"],
  [/NIFTY\s*50|^NIFTY$/i, "N50"],
  [/NIFTY/i, "N"],
  [/SENSEX/i, "SX"],
  [/NASDAQ/i, "NDQ"],
  [/DOW|DJIA/i, "DJ"],
  [/S&P/i, "SP"],
  [/GOLD/i, "AU"],
  [/SILVER/i, "AG"],
  [/USD.*INR|INR.*USD/i, "₹/$"],
];

function badgeText(symbol: string, kind?: "stock" | "index") {
  const clean = symbol.trim().toUpperCase();
  if (kind === "index" || INDEX_MARKS.some(([pattern]) => pattern.test(clean))) {
    return INDEX_MARKS.find(([pattern]) => pattern.test(clean))?.[1] ?? clean.slice(0, 3);
  }
  const chunks = clean.split(/[^A-Z0-9]+/).filter(Boolean);
  if (chunks.length > 1) return chunks.slice(0, 2).map((part) => part[0]).join("");
  return clean.replace(/[^A-Z0-9]/g, "").slice(0, clean.length <= 4 ? 2 : 3) || "—";
}

function palette(symbol: string) {
  const hash = [...symbol].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const hue = (hash * 37) % 360;
  return {
    background: `linear-gradient(145deg, hsl(${hue} 78% 96%), hsl(${hue} 72% 88%))`,
    borderColor: `hsl(${hue} 55% 76%)`,
    color: `hsl(${hue} 58% 30%)`,
  };
}

export default function MarketSymbolBadge({
  symbol,
  kind,
  size = "md",
  className = "",
}: {
  symbol: string;
  kind?: "stock" | "index";
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const dimensions = size === "sm" ? "h-6 w-6 text-[7px]" : size === "lg" ? "h-11 w-11 text-[10px]" : "h-8 w-8 text-[8px]";
  const isIndex = kind === "index" || INDEX_MARKS.some(([pattern]) => pattern.test(symbol));
  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-lg border font-black tracking-tight shadow-sm ${dimensions} ${className}`}
      style={palette(symbol)}
      title={`${symbol} ${isIndex ? "index" : "symbol"}`}
      aria-label={`${symbol} ${isIndex ? "index" : "symbol"}`}
    >
      {badgeText(symbol, kind)}
      <svg className="absolute inset-x-0 bottom-0 h-2 w-full opacity-30" viewBox="0 0 32 8" preserveAspectRatio="none" aria-hidden>
        <path d="M0 7 L7 5 L12 6 L18 2 L23 4 L32 0" fill="none" stroke="currentColor" strokeWidth="1.2" />
      </svg>
    </span>
  );
}
