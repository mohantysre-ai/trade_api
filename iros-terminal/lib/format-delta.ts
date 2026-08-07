/** Format absolute pts + percentage for desk cards, e.g. ``201.52 (0.16%)``. */

function parseNum(raw: string | number | null | undefined): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (raw == null) return null;
  const cleaned = String(raw).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  if (!cleaned) return null;
  const n = Number(cleaned[0]);
  return Number.isFinite(n) ? n : null;
}

function fmtPts(pts: number): string {
  return Math.abs(pts).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** True when delta already includes absolute change + ``(x.xx%)``. */
export function isAbsPctDelta(delta: string): boolean {
  return /^-?\+?[\d,]+\.?\d*\s*\([+\-]?\d+(?:\.\d+)?%\)$/.test(delta.trim());
}

/**
 * Prefer backend ``pts (pct%)`` string; if only ``+0.16%`` is present,
 * derive pts from LTP when possible.
 */
export function formatDeskDelta(
  value: string | number | null | undefined,
  delta: string | null | undefined,
): string | undefined {
  if (delta == null) return undefined;
  const d = String(delta).trim();
  if (!d) return undefined;
  if (isAbsPctDelta(d)) {
    return d.replace(/^\+/, "");
  }
  const pctOnly = d.match(/^([+\-]?\d+(?:\.\d+)?)\s*%$/);
  if (pctOnly) {
    const pct = Number(pctOnly[1]);
    const price = parseNum(value);
    if (price != null && Number.isFinite(pct)) {
      const denom = 100 + pct;
      if (Math.abs(denom) > 1e-9) {
        const pts = (price * pct) / denom;
        return `${fmtPts(pts)} (${Math.abs(pct).toFixed(2)}%)`;
      }
    }
    return d;
  }
  return d;
}

/** Day / period change from known price + pct. */
export function formatPtsPctLabel(price: number | null, pct: number): string {
  if (price != null && Number.isFinite(price) && Number.isFinite(pct)) {
    const denom = 100 + pct;
    if (Math.abs(denom) > 1e-9) {
      const pts = (price * pct) / denom;
      return `${fmtPts(pts)} (${Math.abs(pct).toFixed(2)}%)`;
    }
  }
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

/** Spark / series endpoints → abs move + pct. */
export function formatSeriesDelta(first: number, last: number): {
  label: string;
  pct: number;
  positive: boolean;
} {
  const pct = ((last - first) / first) * 100;
  const pts = last - first;
  return {
    pct,
    positive: pct >= 0,
    label: `${fmtPts(pts)} (${Math.abs(pct).toFixed(1)}%)`,
  };
}
