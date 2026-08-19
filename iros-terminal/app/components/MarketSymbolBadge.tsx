"use client";

import React, { useMemo, useState } from "react";

function MissingLogoIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-1/2 w-1/2 text-slate-400" fill="none" aria-hidden>
      <path d="M4.5 19.5h15M6.5 19.5V9.25L12 5l5.5 4.25V19.5M9.25 19.5v-5h5.5v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
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
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const cleanSymbol = symbol.trim();
  const dimensions = size === "sm" ? "h-6 w-6" : size === "lg" ? "h-11 w-11" : "h-8 w-8";
  const logoUrl = useMemo(() => {
    const params = new URLSearchParams({ symbol: cleanSymbol });
    if (kind) params.set("kind", kind);
    return `/api/symbol-logo?${params.toString()}`;
  }, [cleanSymbol, kind]);

  const failed = failedUrl === logoUrl;

  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm ${dimensions} ${className}`}
      title={failed ? `${cleanSymbol} logo unavailable` : `${cleanSymbol} market logo`}
      aria-label={failed ? `${cleanSymbol} logo unavailable` : `${cleanSymbol} market logo`}
    >
      {failed || !cleanSymbol ? (
        <MissingLogoIcon />
      ) : (
        <img
          key={logoUrl}
          src={logoUrl}
          alt=""
          className="h-full w-full object-contain p-0.5"
          loading="lazy"
          decoding="async"
          onError={() => setFailedUrl(logoUrl)}
        />
      )}
    </span>
  );
}
