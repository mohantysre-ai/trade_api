/** Quotes and P&L fields are not execution evidence. Explicit skips win. */
export type ExecutionEvidence = {
  skipped?: boolean | null;
  triggered?: boolean | null;
  status?: string | null;
  executionStatus?: string | null;
};

export function isExplicitNonFill(mark: ExecutionEvidence | null | undefined): boolean {
  if (!mark) return false;
  return mark.skipped === true || mark.triggered === false ||
    [mark.status, mark.executionStatus].some((value) =>
      ['NOT_TRIGGERED', 'SKIPPED'].includes(String(value || '').trim().toUpperCase()),
    );
}

export function isLiveSessionFill(mark: ExecutionEvidence | null | undefined): boolean {
  if (!mark || isExplicitNonFill(mark)) return false;
  return mark.triggered === true ||
    ['TRIGGERED', 'EXECUTED', 'FILLED'].includes(String(mark.executionStatus || '').trim().toUpperCase());
}

export function canOverlayIntradayBook(phase: string | undefined, marketOpen: boolean): boolean {
  // Finalised reports must not be revalued by the quote stream after close.
  return phase === 'OPEN' && marketOpen;
}
