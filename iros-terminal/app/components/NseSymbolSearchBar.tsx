'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

type NseSymbol = { ticker: string; name: string };

type NseSymbolSearchBarProps = {
  onSelect: (ticker: string) => void;
  selectedTicker?: string;
};

const MAX_RESULTS = 12;

function normalizeRows(rows: unknown): NseSymbol[] {
  if (!Array.isArray(rows)) return [];
  return rows
    .map((r) => {
      const row = r as NseSymbol;
      const ticker = String(row?.ticker || '').toUpperCase().trim();
      const name = String(row?.name || ticker).trim() || ticker;
      return { ticker, name };
    })
    .filter((r) => r.ticker);
}

export default function NseSymbolSearchBar({ onSelect, selectedTicker }: NseSymbolSearchBarProps) {
  const [query, setQuery] = useState('');
  const [symbols, setSymbols] = useState<NseSymbol[]>([]);
  const [source, setSource] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const fullLoadedRef = useRef(false);
  const fullAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        // Fast path first so typing works immediately
        const fast = await fetch('/api/nse-symbols?universe=nifty500', { cache: 'no-store' });
        const fastData = await fast.json();
        if (cancelled) return;
        if (fast.ok && fastData?.success) {
          setSymbols(normalizeRows(fastData.symbols));
          setSource(String(fastData.source || 'nifty500'));
          setLoading(false);
        }
        if (!fast.ok) setError(String(fastData?.error || 'Symbol list unavailable'));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Symbol list unavailable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadFullUniverse = useCallback(async () => {
    if (fullLoadedRef.current || fullAbortRef.current) return;
    const controller = new AbortController();
    fullAbortRef.current = controller;
    try {
      const response = await fetch('/api/nse-symbols?universe=all', {
        cache: 'no-store', signal: controller.signal,
      });
      const data = await response.json();
      if (response.ok && data?.success && Array.isArray(data.symbols) && data.symbols.length) {
        setSymbols(normalizeRows(data.symbols));
        setSource(String(data.source || 'nse'));
        fullLoadedRef.current = true;
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        // Nifty 500 remains usable when the optional full universe is unavailable.
      }
    } finally {
      if (fullAbortRef.current === controller) fullAbortRef.current = null;
    }
  }, []);

  useEffect(() => () => fullAbortRef.current?.abort(), []);

  useEffect(() => {
    if (open && query.trim().length >= 2) void loadFullUniverse();
  }, [loadFullUniverse, open, query]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return symbols.slice(0, MAX_RESULTS);
    const starts: NseSymbol[] = [];
    const contains: NseSymbol[] = [];
    for (const s of symbols) {
      const t = s.ticker;
      const n = s.name.toUpperCase();
      if (t.startsWith(q) || n.startsWith(q)) starts.push(s);
      else if (t.includes(q) || n.includes(q)) contains.push(s);
      if (starts.length + contains.length >= MAX_RESULTS * 3) break;
    }
    return [...starts, ...contains].slice(0, MAX_RESULTS);
  }, [query, symbols]);

  useEffect(() => {
    setActiveIdx(0);
  }, [query, open]);

  const pick = useCallback(
    (ticker: string) => {
      const t = ticker.toUpperCase().trim();
      if (!t) return;
      setQuery('');
      setOpen(false);
      onSelect(t);
    },
    [onSelect],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) {
      setOpen(true);
      return;
    }
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, Math.max(0, filtered.length - 1)));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const hit = filtered[activeIdx];
      if (hit) pick(hit.ticker);
      else if (query.trim()) pick(query.trim());
    }
  };

  return (
    <div ref={rootRef} className={`desk-nse-search${open ? ' is-open' : ''}`}>
      {open ? (
        <button
          type="button"
          className="desk-nse-search-scrim"
          aria-label="Dismiss symbol search"
          onMouseDown={(e) => {
            e.preventDefault();
            setOpen(false);
          }}
        />
      ) : null}
      <div className="desk-nse-search-inner">
        <span className="desk-nse-search-icon" aria-hidden>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <circle cx="11" cy="11" r="6.5" />
            <path strokeLinecap="round" d="M16.2 16.2L21 21" />
          </svg>
        </span>
        <input
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            void loadFullUniverse();
          }}
          onKeyDown={onKeyDown}
          placeholder={
            loading
              ? 'Loading NSE symbols…'
              : error
                ? 'Type ticker, then Enter'
                : `Search NSE · ${symbols.length || '—'} symbols`
          }
          className="desk-nse-search-input"
          aria-label="Search NSE symbols"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls="desk-nse-search-listbox"
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="search"
        />
        {query ? (
          <button
            type="button"
            className="desk-nse-search-clear"
            aria-label="Clear search"
            onMouseDown={(e) => {
              e.preventDefault();
              setQuery('');
              setOpen(true);
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
              <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        ) : null}
        {selectedTicker ? (
          <button
            type="button"
            className="desk-nse-search-chip"
            onMouseDown={(e) => {
              e.preventDefault();
              pick(selectedTicker);
            }}
            title="Re-open drawer"
          >
            {selectedTicker}
          </button>
        ) : null}
      </div>
      {open && (filtered.length > 0 || error) ? (
        <ul id="desk-nse-search-listbox" className="desk-nse-search-menu" role="listbox">
          {filtered.map((s, i) => (
            <li key={s.ticker} role="option" aria-selected={i === activeIdx}>
              <button
                type="button"
                className={`desk-nse-search-option ${i === activeIdx ? 'is-active' : ''}`}
                onMouseEnter={() => setActiveIdx(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(s.ticker);
                }}
              >
                <span className="desk-nse-search-ticker">{s.ticker}</span>
                {s.name && s.name !== s.ticker ? (
                  <span className="desk-nse-search-name">{s.name}</span>
                ) : null}
              </button>
            </li>
          ))}
          {error ? (
            <li className="desk-nse-search-meta">{error}</li>
          ) : source ? (
            <li className="desk-nse-search-meta" aria-hidden>
              {source.replace(/_/g, ' ')} · {symbols.length} symbols
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
