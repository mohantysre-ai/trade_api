type Entry = {
  value?: unknown;
  storedAt?: number;
  expiresAt: number;
  staleUntil: number;
  pending?: Promise<unknown>;
};

const entries = new Map<string, Entry>();
const MAX_STALE_IF_ERROR_MS = 5 * 60_000;

export async function cachedBackendJson<T>(
  key: string,
  url: string,
  freshMs: number,
  staleMs = 30_000,
  timeoutMs = 60_000,
): Promise<{ data: T; cacheStatus: "HIT" | "MISS" | "STALE" | "STALE_IF_ERROR" }> {
  const now = Date.now();
  const entry = entries.get(key);
  const fetchJson = () =>
    fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    }).then(async (response) => {
      if (!response.ok) throw new Error(`Backend HTTP ${response.status}`);
      return response.json() as Promise<T>;
    });
  if (entry?.value !== undefined && now < entry.expiresAt) {
    return { data: entry.value as T, cacheStatus: "HIT" };
  }
  if (entry?.value !== undefined && now < entry.staleUntil) {
    if (!entry.pending) {
      const refresh = fetchJson();
      entries.set(key, { ...entry, pending: refresh });
      void refresh.then((value) => {
        const storedAt = Date.now();
        entries.set(key, { value, storedAt, expiresAt: storedAt + freshMs, staleUntil: storedAt + staleMs });
      }).catch(() => {
        entries.set(key, { ...entry, pending: undefined });
      });
    }
    return { data: entry.value as T, cacheStatus: "STALE" };
  }
  if (entry?.pending) {
    return { data: (await entry.pending) as T, cacheStatus: "HIT" };
  }

  const pending = fetchJson();
  entries.set(key, { ...entry, expiresAt: entry?.expiresAt ?? 0, staleUntil: entry?.staleUntil ?? 0, pending });

  try {
    const value = await pending;
    const storedAt = Date.now();
    entries.set(key, { value, storedAt, expiresAt: storedAt + freshMs, staleUntil: storedAt + staleMs });
    return { data: value, cacheStatus: "MISS" };
  } catch (error) {
    if (
      entry?.value !== undefined &&
      entry.storedAt !== undefined &&
      now - entry.storedAt <= MAX_STALE_IF_ERROR_MS
    ) {
      // A transient backend stall must not turn a usable live screen into a
      // 503. Keep the last known value in process and make the fallback
      // explicit in response headers. The browser/CDN is still forbidden from
      // caching it, so recovery is visible on the very next request.
      entries.set(key, { ...entry, pending: undefined });
      return { data: entry.value as T, cacheStatus: "STALE_IF_ERROR" };
    }
    entries.delete(key);
    throw error;
  }
}

export const liveCacheHeaders = (status: string) => ({
  "Cache-Control": "private, no-store, max-age=0, must-revalidate",
  "CDN-Cache-Control": "no-store",
  "Cloudflare-CDN-Cache-Control": "no-store",
  "Vary": "Cookie, Authorization",
  "X-Live-Cache": status,
});
