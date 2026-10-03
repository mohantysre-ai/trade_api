export type EodSortKey =
  | 'symbol' | 'side' | 'qty' | 'entry' | 'mark' | 'exit' | 'status' | 'exitType'
  | 'economicR' | 'pathR' | 'movePct' | 'maeR' | 'mfeR' | 'rootCause' | 'pnl'
  | 'pnlPct' | 'deployed' | 'weight' | 'flags' | 'scaleTrail' | 'srcRank' | 'contract'
  | 'kind' | 'index';

export type EodSortDir = 'asc' | 'desc';
export type EodSort = { key: EodSortKey; dir: EodSortDir };
export type EodSortValue = string | number | null | undefined;

const ENUM_RANK: Record<string, number> = {
  LOSS: 0, FLAT: 1, WIN: 2, SKIPPED: 3,
  SL_HIT: 0, INITIAL_SL: 0, TRAIL_STOP: 1, TRAIL_SL_HIT: 1,
  CLOSED_TIME: 2, EOD_SQUAREOFF: 2, PARTIAL_SCALE: 3, RUNNING: 4, OPEN: 4,
  NOT_TRIGGERED: 5, NO_MARK: 6,
};

export function sortEodRows<T>(
  rows: readonly T[],
  sort: EodSort | null,
  get: (row: T, key: EodSortKey) => EodSortValue,
  symbol: (row: T) => string,
): T[] {
  if (!sort) return [...rows];
  if (!rows.some((row) => {
    const value = get(row, sort.key);
    return value != null && !(typeof value === 'number' && !Number.isFinite(value));
  })) return [...rows];
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const av = get(a.row, sort.key);
      const bv = get(b.row, sort.key);
      const aNull = av == null || (typeof av === 'number' && !Number.isFinite(av));
      const bNull = bv == null || (typeof bv === 'number' && !Number.isFinite(bv));
      if (aNull !== bNull) return aNull ? 1 : -1;
      let compared = 0;
      if (!aNull && !bNull) {
        const ar = ENUM_RANK[String(av).toUpperCase()];
        const br = ENUM_RANK[String(bv).toUpperCase()];
        compared = ar != null && br != null
          ? ar - br
          : typeof av === 'number' && typeof bv === 'number'
            ? av - bv
            : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
      }
      if (compared !== 0) return sort.dir === 'asc' ? compared : -compared;
      const symbolCompared = symbol(a.row).localeCompare(symbol(b.row));
      return symbolCompared || a.index - b.index;
    })
    .map(({ row }) => row);
}
