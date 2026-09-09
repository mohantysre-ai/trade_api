const TICKER_PATTERN = /^[A-Z0-9][A-Z0-9&._-]{0,29}$/;
const SPARKLINE_FLAGS = new Set(["1D", "1M", "1Y"]);

export function normalizeTicker(raw: string | null): string | null {
  const ticker = raw?.trim().toUpperCase() ?? "";
  return TICKER_PATTERN.test(ticker) ? ticker : null;
}

export function normalizeSparklineFlag(raw: string | null): string | null {
  const flag = (raw || "1M").trim().toUpperCase();
  return SPARKLINE_FLAGS.has(flag) ? flag : null;
}

export function normalizeBooleanParam(raw: string | null): string | null {
  if (raw === null) return null;
  const value = raw.trim().toLowerCase();
  if (["1", "true", "yes"].includes(value)) return "true";
  if (["0", "false", "no"].includes(value)) return "false";
  return null;
}
