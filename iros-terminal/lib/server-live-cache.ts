type Entry = { value?: unknown; expiresAt: number; staleUntil: number; pending?: Promise<unknown> };

const entries = new Map<string, Entry>();

export async function cachedBackendJson<T>(
  key: string,
  url: string,
  freshMs: number,
  staleMs = 30_000,
): Promise<{ data: T; cacheStatus: "HIT" | "MISS" | "STALE" }> {
  const now = Date.now();
  const entry = entries.get(key);
  if (entry?.value !== undefined && now < entry.expiresAt) {
    return { data: entry.value as T, cacheStatus: "HIT" };
  }
  if (entry?.value !== undefined && now < entry.staleUntil) {
    if (!entry.pending) {
      const refresh = fetch(url, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(12_000),
      }).then(async (response) => {
        if (!response.ok) throw new Error(`Backend HTTP ${response.status}`);
        return response.json() as Promise<T>;
      });
      entries.set(key, { ...entry, pending: refresh });
      void refresh.then((value) => {
        entries.set(key, { value, expiresAt: Date.now() + freshMs, staleUntil: Date.now() + staleMs });
      }).catch(() => {
        entries.set(key, { ...entry, pending: undefined });
      });
    }
    return { data: entry.value as T, cacheStatus: "STALE" };
  }
  if (entry?.pending) {
    return { data: (await entry.pending) as T, cacheStatus: "HIT" };
  }

  const pending = fetch(url, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(12_000),
  }).then(async (response) => {
    if (!response.ok) throw new Error(`Backend HTTP ${response.status}`);
    return response.json() as Promise<T>;
  });
  entries.set(key, { ...entry, expiresAt: entry?.expiresAt ?? 0, staleUntil: entry?.staleUntil ?? 0, pending });

  try {
    const value = await pending;
    entries.set(key, { value, expiresAt: Date.now() + freshMs, staleUntil: Date.now() + staleMs });
    return { data: value, cacheStatus: "MISS" };
  } catch (error) {
    entries.delete(key);
    if (entry?.value !== undefined && now < entry.staleUntil) {
      return { data: entry.value as T, cacheStatus: "STALE" };
    }
    throw error;
  }
}

export const liveCacheHeaders = (status: string) => ({
  "Cache-Control": "public, max-age=2, s-maxage=4, stale-while-revalidate=30",
  "Cloudflare-CDN-Cache-Control": "public, max-age=4, stale-while-revalidate=30",
  "X-Live-Cache": status,
});
