'use client';

import { useEffect } from 'react';
import useSWR from 'swr';

export type LiveDeskKey = 'live-prices' | 'intraday-session' | 'swing-session';
export type LiveDeskSnapshot = { sequence: number; receivedAt: string; 'live-prices': Record<string, unknown>; 'intraday-session': Record<string, unknown>; 'swing-session': Record<string, unknown>; };
const LIVE_KEYS: LiveDeskKey[] = ['live-prices', 'intraday-session', 'swing-session'];
const urls: Record<LiveDeskKey, string> = { 'live-prices': '/api/live-prices', 'intraday-session': '/api/intraday-session', 'swing-session': '/api/swing-session?live=1' };
const OPEN_POLL_MS = 5_000;
const LOCKED_SWING_POLL_MS = 1_000;
const CLOSED_POLL_MS = 30_000;
const OPEN_CACHE_MS = 4_500;
const LOCKED_SWING_CACHE_MS = 850;
const CLOSED_CACHE_MS = 29_500;
const lastGood = new Map<LiveDeskKey, Record<string, unknown>>();
const listeners = new Set<(snapshot: LiveDeskSnapshot) => void>();
let lastSnapshot: LiveDeskSnapshot | null = null, lastSnapshotAt = 0, pendingSnapshot: Promise<LiveDeskSnapshot> | null = null, pollTimer: number | null = null, sequence = 0;

function marketIsOpen(snapshot = lastSnapshot): boolean {
  const prices = snapshot?.['live-prices'] as { marketOpen?: boolean; sessionClosed?: boolean } | undefined;
  return prices?.marketOpen !== false && prices?.sessionClosed !== true;
}
function hasLockedSwing(snapshot = lastSnapshot): boolean {
  const swing = snapshot?.['swing-session'] as { locked?: boolean; long?: unknown[] } | undefined;
  return Boolean(swing?.locked && Array.isArray(swing.long) && swing.long.length > 0);
}
function pollingPeriod(): number { return marketIsOpen() ? (hasLockedSwing() ? LOCKED_SWING_POLL_MS : OPEN_POLL_MS) : CLOSED_POLL_MS; }
function cachePeriod(): number { return marketIsOpen() ? (hasLockedSwing() ? LOCKED_SWING_CACHE_MS : OPEN_CACHE_MS) : CLOSED_CACHE_MS; }
function notifySnapshot(snapshot: LiveDeskSnapshot): void { for (const listener of listeners) { try { listener(snapshot); } catch {} } }
async function fetchDeskKey(key: LiveDeskKey): Promise<Record<string, unknown>> {
  try { const response = await fetch(urls[key], { cache: 'no-store' }); if (!response.ok) throw new Error(`${key} HTTP ${response.status}`); const data = await response.json() as Record<string, unknown>; lastGood.set(key, data); return data; }
  catch (error) { const fallback = lastGood.get(key); if (fallback) return fallback; throw error; }
}
export async function fetchLiveDeskSnapshot(force = false): Promise<LiveDeskSnapshot> {
  const maxAge = cachePeriod();
  if (!force && lastSnapshot && Date.now() - lastSnapshotAt < maxAge) return lastSnapshot;
  if (pendingSnapshot) return pendingSnapshot;
  pendingSnapshot = Promise.allSettled(LIVE_KEYS.map((key) => fetchDeskKey(key))).then((results) => {
    const resources = {} as Record<LiveDeskKey, Record<string, unknown>>;
    LIVE_KEYS.forEach((key, index) => { const result = results[index]; resources[key] = result.status === 'fulfilled' ? result.value : lastGood.get(key) ?? {}; });
    const snapshot: LiveDeskSnapshot = { sequence: ++sequence, receivedAt: new Date().toISOString(), 'live-prices': resources['live-prices'], 'intraday-session': resources['intraday-session'], 'swing-session': resources['swing-session'] };
    lastSnapshot = snapshot; lastSnapshotAt = Date.now(); notifySnapshot(snapshot); return snapshot;
  }).finally(() => { pendingSnapshot = null; });
  return pendingSnapshot;
}
export async function fetchLiveDesk<T = Record<string, unknown>>(key: LiveDeskKey): Promise<T> { const snapshot = await fetchLiveDeskSnapshot(); return snapshot[key] as T; }
function scheduleSharedPoll(): void {
  if (typeof window === 'undefined' || listeners.size === 0) return;
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  const period = pollingPeriod(), remainder = Date.now() % period, delay = Math.max(200, period - remainder);
  pollTimer = window.setTimeout(async () => { pollTimer = null; if (document.visibilityState === 'visible' && navigator.onLine) { try { await fetchLiveDeskSnapshot(true); } catch {} } scheduleSharedPoll(); }, delay);
}
export function subscribeLiveDesk(listener: (snapshot: LiveDeskSnapshot) => void): () => void {
  listeners.add(listener);
  if (lastSnapshot) queueMicrotask(() => { try { listener(lastSnapshot as LiveDeskSnapshot); } catch {} });
  if (listeners.size === 1) void fetchLiveDeskSnapshot().finally(scheduleSharedPoll);
  return () => { listeners.delete(listener); if (listeners.size === 0 && pollTimer !== null) { window.clearTimeout(pollTimer); pollTimer = null; } };
}
export function useLiveDesk<T = Record<string, unknown>>(key: LiveDeskKey) {
  const swr = useSWR<T>(`live-desk:${key}`, () => fetchLiveDesk<T>(key), { dedupingInterval: LOCKED_SWING_CACHE_MS, keepPreviousData: true, revalidateOnFocus: true, revalidateOnReconnect: true, refreshWhenHidden: false, refreshWhenOffline: false, refreshInterval: 0 });
  const mutate = swr.mutate;
  useEffect(() => subscribeLiveDesk((snapshot) => { void mutate(snapshot[key] as T, false); }), [key, mutate]);
  return swr;
}
