'use client';

/**
 * Desk activity alerts — animated toast stack for book picks + trade hits.
 * Sources: /api/live-prices, /api/intraday-session, /api/swing-session?live=1
 * Facts only from API fields (symbol, action, price, time, label).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';

export type DeskActivityAlert = {
  id: string;
  symbol: string;
  action: 'BUY' | 'SELL' | 'PARTIAL' | 'LOCK';
  direction?: string;
  hitLevel?: string;
  label: string;
  price: number | null;
  entryPrice?: number | null;
  book?: string;
  firedAt: string;
  planDate?: string;
};

type RawAlert = {
  key?: string;
  symbol?: string;
  direction?: string;
  hitLevel?: string;
  label?: string;
  ltp?: number;
  entryPrice?: number | null;
  planDate?: string;
  firedAt?: string;
  book?: string;
  action?: string;
};

const SEEN_KEY = 'alphix.deskActivitySeen.v1';
const MAX_VISIBLE = 4;
const AUTO_MS = 9000;
const POLL_MS = 15_000;

function loadSeen(): Set<string> {
  try {
    const raw = sessionStorage.getItem(SEEN_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(Array.isArray(arr) ? arr.slice(-200) : []);
  } catch {
    return new Set();
  }
}

function persistSeen(seen: Set<string>) {
  try {
    sessionStorage.setItem(SEEN_KEY, JSON.stringify([...seen].slice(-200)));
  } catch {
    /* ignore */
  }
}

function resolveAction(raw: RawAlert): DeskActivityAlert['action'] {
  const hit = String(raw.hitLevel || '').toLowerCase();
  if (hit === 'partial') return 'PARTIAL';
  if (hit === 'buy' || hit === 'lock') return hit === 'lock' ? 'LOCK' : 'BUY';
  if (hit === 'sell') return 'SELL';
  const a = String(raw.action || '').toUpperCase();
  if (a === 'BUY' || a === 'SELL' || a === 'PARTIAL' || a === 'LOCK') return a;
  if (hit === 't1' || hit === 't2' || hit === 'sl') {
    return String(raw.direction || 'LONG').toUpperCase() === 'LONG' ? 'SELL' : 'BUY';
  }
  return 'LOCK';
}

function normalize(raw: RawAlert): DeskActivityAlert | null {
  const symbol = String(raw.symbol || '').toUpperCase().trim();
  if (!symbol) return null;
  const firedAt = raw.firedAt || new Date().toISOString();
  const id = String(raw.key || `${symbol}:${raw.hitLevel}:${firedAt}`);
  const price =
    typeof raw.ltp === 'number' && Number.isFinite(raw.ltp)
      ? raw.ltp
      : typeof raw.entryPrice === 'number' && Number.isFinite(raw.entryPrice)
        ? raw.entryPrice
        : null;
  return {
    id,
    symbol,
    action: resolveAction(raw),
    direction: raw.direction,
    hitLevel: raw.hitLevel,
    label: String(raw.label || raw.hitLevel || 'ACTIVITY').trim(),
    price,
    entryPrice: raw.entryPrice ?? null,
    book: raw.book,
    firedAt,
    planDate: raw.planDate,
  };
}

function formatIstTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '--:--:--';
  }
}

function formatInr(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n) || n <= 0) return '—';
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function toneFor(action: DeskActivityAlert['action']): {
  rail: string;
  badge: string;
  glow: string;
} {
  switch (action) {
    case 'BUY':
      return {
        rail: 'bg-emerald-500',
        badge: 'bg-emerald-500/15 text-emerald-800 border-emerald-400/40',
        glow: 'shadow-emerald-500/20',
      };
    case 'SELL':
      return {
        rail: 'bg-rose-500',
        badge: 'bg-rose-500/15 text-rose-800 border-rose-400/40',
        glow: 'shadow-rose-500/20',
      };
    case 'PARTIAL':
      return {
        rail: 'bg-amber-500',
        badge: 'bg-amber-500/15 text-amber-900 border-amber-400/45',
        glow: 'shadow-amber-500/20',
      };
    case 'LOCK':
      return {
        rail: 'bg-cyan-600',
        badge: 'bg-cyan-500/15 text-cyan-900 border-cyan-400/40',
        glow: 'shadow-cyan-500/20',
      };
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
}

function AlertCard({
  alert,
  onDismiss,
  reduced,
}: {
  alert: DeskActivityAlert;
  onDismiss: (id: string) => void;
  reduced: boolean;
}) {
  const tone = toneFor(alert.action);
  const hit = String(alert.hitLevel || '').toLowerCase();
  const subtitle =
    hit === 'partial'
      ? 'Partial book'
      : hit === 't1'
        ? 'Target 1'
        : hit === 't2'
          ? 'Target 2'
          : hit === 'sl'
            ? 'Stop loss'
            : hit === 'buy' || hit === 'sell'
              ? 'Book pick'
              : alert.label;

  return (
    <motion.div
      layout
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: -28, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, x: 48, scale: 0.96 }}
      transition={{ type: 'spring', stiffness: 420, damping: 28, mass: 0.7 }}
      className={`desk-activity-alert relative overflow-hidden rounded-xl border border-slate-200/90 bg-white/95 backdrop-blur-md shadow-xl ${tone.glow}`}
      role="status"
      aria-live="polite"
    >
      <div className={`absolute left-0 top-0 bottom-0 w-[4px] ${tone.rail}`} aria-hidden />
      {!reduced && <div className="desk-activity-alert-sheen" aria-hidden />}
      <div className="pl-3.5 pr-3 py-2.5 flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-1.5 py-0.5 rounded-md border text-[10px] font-black tracking-wider ${tone.badge}`}>
              {alert.action}
            </span>
            {alert.book && (
              <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-400">
                {alert.book}
              </span>
            )}
            {alert.direction && (
              <span className="text-[9px] font-semibold text-slate-500">{alert.direction}</span>
            )}
          </div>
          <div className="mt-1 flex items-baseline gap-2 min-w-0">
            <span className="text-[15px] font-black text-slate-900 tracking-tight truncate">
              {alert.symbol}
            </span>
            <span className="text-[11px] text-slate-500 truncate">{subtitle}</span>
          </div>
          <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] tabular-nums">
            <div>
              <span className="text-slate-400 uppercase tracking-wider font-semibold">Price </span>
              <span className="font-bold text-slate-800">{formatInr(alert.price)}</span>
            </div>
            <div>
              <span className="text-slate-400 uppercase tracking-wider font-semibold">Time </span>
              <span className="font-bold text-slate-800">{formatIstTime(alert.firedAt)} IST</span>
            </div>
            {alert.entryPrice != null && alert.entryPrice > 0 && (
              <div className="col-span-2">
                <span className="text-slate-400 uppercase tracking-wider font-semibold">Entry </span>
                <span className="font-bold text-slate-700">{formatInr(alert.entryPrice)}</span>
              </div>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={() => onDismiss(alert.id)}
          className="shrink-0 w-6 h-6 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 text-sm font-bold leading-none"
          aria-label="Dismiss alert"
        >
          ×
        </button>
      </div>
      {!reduced && <div className="desk-activity-alert-progress" style={{ animationDuration: `${AUTO_MS}ms` }} />}
    </motion.div>
  );
}

export default function DeskActivityAlerts({ paused = false }: { paused?: boolean }) {
  const [mounted, setMounted] = useState(false);
  const [queue, setQueue] = useState<DeskActivityAlert[]>([]);
  const seenRef = useRef<Set<string>>(new Set());
  const timersRef = useRef<Map<string, number>>(new Map());
  const reduced = Boolean(useReducedMotion());

  useEffect(() => {
    setMounted(true);
    seenRef.current = loadSeen();
  }, []);

  const dismiss = useCallback((id: string) => {
    const t = timersRef.current.get(id);
    if (t) {
      window.clearTimeout(t);
      timersRef.current.delete(id);
    }
    setQueue((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const pushMany = useCallback(
    (incoming: DeskActivityAlert[]) => {
      if (!incoming.length) return;
      const fresh: DeskActivityAlert[] = [];
      for (const a of incoming) {
        if (seenRef.current.has(a.id)) continue;
        seenRef.current.add(a.id);
        fresh.push(a);
      }
      if (!fresh.length) return;
      persistSeen(seenRef.current);
      setQueue((prev) => {
        const merged = [...fresh, ...prev];
        const dedup = new Map<string, DeskActivityAlert>();
        for (const a of merged) dedup.set(a.id, a);
        return [...dedup.values()].slice(0, MAX_VISIBLE);
      });
      for (const a of fresh) {
        const existing = timersRef.current.get(a.id);
        if (existing) window.clearTimeout(existing);
        const tid = window.setTimeout(() => dismiss(a.id), AUTO_MS);
        timersRef.current.set(a.id, tid);
      }
    },
    [dismiss],
  );

  useEffect(() => {
    let cancelled = false;

    const ingest = (rawList: unknown) => {
      if (!Array.isArray(rawList) || cancelled) return;
      const normalized = rawList
        .map((r) => normalize(r as RawAlert))
        .filter((a): a is DeskActivityAlert => a != null);
      pushMany(normalized);
    };

    const ingestSessionEvents = (payload: {
      events?: Array<Record<string, unknown>>;
      newAlerts?: RawAlert[];
      locked?: boolean;
      sessionDate?: string;
      committedAt?: string;
      long?: Array<Record<string, unknown>>;
      short?: Array<Record<string, unknown>>;
      book?: string;
    }, bookDefault: string) => {
      ingest(payload.newAlerts);
      if (!payload.locked || !payload.committedAt) return;
      const book = String(payload.book || bookDefault).toUpperCase();
      const commitId = `commit:${book}:${payload.sessionDate || ''}:${payload.committedAt}`;
      if (seenRef.current.has(commitId)) return;
      seenRef.current.add(commitId);
      persistSeen(seenRef.current);

      // Only toast fresh locks (avoid replaying today's basket on every visit)
      const committedMs = Date.parse(payload.committedAt);
      if (!Number.isFinite(committedMs) || Date.now() - committedMs > 3 * 60 * 1000) {
        return;
      }

      const alerts: DeskActivityAlert[] = [];
      const at = payload.committedAt;
      for (const row of payload.long || []) {
        const sym = String(row.symbol || row.ticker || '').toUpperCase().trim();
        if (!sym) continue;
        const entry = typeof row.entryPrice === 'number' ? row.entryPrice
          : typeof row.buyAbove === 'number' ? row.buyAbove
          : typeof row.ltp === 'number' ? row.ltp
          : null;
        alerts.push({
          id: `${book}:LONG:lock:${sym}:${payload.sessionDate || ''}`,
          symbol: sym,
          action: 'BUY',
          direction: 'LONG',
          hitLevel: 'buy',
          label: `${book} PICK · BUY`,
          price: entry,
          entryPrice: entry,
          book,
          firedAt: at,
          planDate: payload.sessionDate,
        });
      }
      for (const row of payload.short || []) {
        const sym = String(row.symbol || row.ticker || '').toUpperCase().trim();
        if (!sym) continue;
        const entry = typeof row.entryPrice === 'number' ? row.entryPrice
          : typeof row.ltp === 'number' ? row.ltp
          : null;
        alerts.push({
          id: `${book}:SHORT:lock:${sym}:${payload.sessionDate || ''}`,
          symbol: sym,
          action: 'SELL',
          direction: 'SHORT',
          hitLevel: 'sell',
          label: `${book} PICK · SELL`,
          price: entry,
          entryPrice: entry,
          book,
          firedAt: at,
          planDate: payload.sessionDate,
        });
      }
      pushMany(alerts);
    };

    const poll = async () => {
      if (document.visibilityState !== 'visible') return;
      try {
        const [liveRes, intraRes, swingRes] = await Promise.all([
          fetch('/api/live-prices', { cache: 'no-store' }),
          fetch('/api/intraday-session', { cache: 'no-store' }),
          fetch('/api/swing-session?live=1', { cache: 'no-store' }),
        ]);
        if (liveRes.ok) {
          const live = await liveRes.json();
          ingest(live.newAlerts);
        }
        if (intraRes.ok) {
          const intra = await intraRes.json();
          ingestSessionEvents(intra, 'INTRADAY');
        }
        if (swingRes.ok) {
          const swing = await swingRes.json();
          ingestSessionEvents(swing, 'SWING');
        }
      } catch {
        /* network blip — next poll */
      }
    };

    void poll();
    const id = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      timersRef.current.forEach((t) => window.clearTimeout(t));
      timersRef.current.clear();
    };
  }, [pushMany]);

  if (!mounted || typeof document === 'undefined' || paused) return null;

  return createPortal(
    <div
      className="desk-activity-alert-stack pointer-events-none fixed z-[60] top-[max(0.75rem,env(safe-area-inset-top))] right-[max(0.75rem,env(safe-area-inset-right))] w-[min(22rem,calc(100vw-1.5rem))] flex flex-col gap-2"
      aria-label="Desk activity alerts"
    >
      <AnimatePresence mode="popLayout">
        {queue.map((a) => (
          <div key={a.id} className="pointer-events-auto">
            <AlertCard alert={a} onDismiss={dismiss} reduced={reduced} />
          </div>
        ))}
      </AnimatePresence>
    </div>,
    document.body,
  );
}
