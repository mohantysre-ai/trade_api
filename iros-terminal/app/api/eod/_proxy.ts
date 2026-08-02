import { NextResponse } from "next/server";

export const runtime = "nodejs";

export function backendBase(): string {
  return (
    process.env.MARKET_API_URL ??
    process.env.NEXT_PUBLIC_BACKEND_URL ??
    "http://127.0.0.1:8000"
  );
}

export async function proxyJson(
  backendPath: string,
  init?: RequestInit
): Promise<NextResponse> {
  try {
    const res = await fetch(`${backendBase()}${backendPath}`, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
      ...init,
    });

    const text = await res.text();
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { error: text };
      }
    }

    if (!res.ok) {
      const errBody =
        data && typeof data === "object"
          ? data
          : { error: `Backend returned ${res.status}` };
      return NextResponse.json(errBody, { status: res.status });
    }

    return NextResponse.json(data ?? {});
  } catch (err) {
    return NextResponse.json(
      {
        error: err instanceof Error ? err.message : "Backend unreachable",
      },
      { status: 502 }
    );
  }
}
