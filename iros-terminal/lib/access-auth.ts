import { cookies } from "next/headers";

export const ACCESS_COOKIE = "sigq_session";

export function authBackendBase(): string {
  return (
    process.env.MARKET_API_URL ??
    process.env.NEXT_PUBLIC_BACKEND_URL ??
    "http://127.0.0.1:8000"
  ).replace(/\/$/, "");
}

export async function authBackendFetch(
  path: string,
  init: RequestInit = {},
  token?: string | null,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${authBackendBase()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

export async function currentAccessToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(ACCESS_COOKIE)?.value ?? null;
}

export async function currentAccessSession(): Promise<{
  authenticated: boolean;
  user?: {
    id: number;
    identifier: string;
    identifierType: string;
    status: string;
    isAdmin: boolean;
    expiresAt?: string;
  } | null;
}> {
  const token = await currentAccessToken();
  if (!token) return { authenticated: false, user: null };
  try {
    const res = await authBackendFetch("/api/auth/session", { method: "GET" }, token);
    if (!res.ok) return { authenticated: false, user: null };
    return (await res.json()) as {
      authenticated: boolean;
      user?: {
        id: number;
        identifier: string;
        identifierType: string;
        status: string;
        isAdmin: boolean;
        expiresAt?: string;
      } | null;
    };
  } catch {
    return { authenticated: false, user: null };
  }
}
