'use client';
import useSWR from 'swr';

export type LiveDeskKey = 'live-prices' | 'intraday-session' | 'swing-session';
const urls: Record<LiveDeskKey, string> = { 'live-prices': '/api/live-prices', 'intraday-session': '/api/intraday-session', 'swing-session': '/api/swing-session?live=1' };
const pending = new Map<LiveDeskKey, Promise<unknown>>();
const lastGood = new Map<LiveDeskKey, unknown>();
const lastGoodAt = new Map<LiveDeskKey, number>();

export async function fetchLiveDesk<T = Record<string, unknown>>(key: LiveDeskKey): Promise<T> {
  const age = Date.now() - (lastGoodAt.get(key) ?? 0);
  if (lastGood.has(key) && age < 4_500) return lastGood.get(key) as T;
  const existing = pending.get(key);
  if (existing) return existing as Promise<T>;
  const request = fetch(urls[key], { cache: 'no-store' }).then(async (response) => {
    if (!response.ok) throw new Error(`${key} HTTP ${response.status}`);
    const data = await response.json(); lastGood.set(key, data); lastGoodAt.set(key, Date.now()); return data;
  }).catch((error) => { if (lastGood.has(key)) return lastGood.get(key); throw error; }).finally(() => pending.delete(key));
  pending.set(key, request); return request as Promise<T>;
}

export function useLiveDesk<T = Record<string, unknown>>(key: LiveDeskKey) {
  return useSWR<T>(`live-desk:${key}`, () => fetchLiveDesk<T>(key), {
    dedupingInterval: 4_500, keepPreviousData: true, revalidateOnFocus: true, revalidateOnReconnect: true,
    refreshWhenHidden: false, refreshWhenOffline: false,
    refreshInterval: (data) => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return 0;
      if (typeof navigator !== 'undefined' && !navigator.onLine) return 0;
      const state = data as { marketOpen?: boolean; sessionClosed?: boolean } | undefined;
      return state?.sessionClosed || state?.marketOpen === false ? 30_000 : 5_000;
    },
  });
}
