import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL = process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";
const REFRESH_POLL_MS = 3_000;
const REFRESH_MAX_WAIT_MS = 20 * 60 * 1_000;
const REQUEST_TIMEOUT_MS = 60_000;

async function pollRefreshStatus(statusUrl: string): Promise<Record<string, unknown>> {
  const deadline = Date.now() + REFRESH_MAX_WAIT_MS;
  while (Date.now() < deadline) {
    const res = await fetch(statusUrl, {
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `Status poll HTTP ${res.status}`);
    }
    const data = (await res.json()) as Record<string, unknown>;
    const status = String(data.status ?? "");
    if (status === "done" && data.result) {
      return data.result as Record<string, unknown>;
    }
    if (status === "error" || status === "failed") {
      throw new Error(String(data.error ?? "Refresh failed"));
    }
    if (status === "expired") {
      throw new Error("Refresh task expired");
    }
    await new Promise((resolve) => setTimeout(resolve, REFRESH_POLL_MS));
  }
  throw new Error("Refresh timed out after 20 minutes");
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const requestUrl = new URL(request.url);
    const pool = requestUrl.searchParams.get("pool") || body?.pool;
    const prompt = requestUrl.searchParams.get("prompt") || body?.prompt;
    const backendUrl = new URL("/api/refresh-data-on-demand", BACKEND_URL);

    const poolValue = typeof pool === "string" ? pool : undefined;
    const promptValue = typeof prompt === "string" ? prompt : undefined;

    if (poolValue) backendUrl.searchParams.set("pool", poolValue);
    if (promptValue) backendUrl.searchParams.set("prompt", promptValue);

    const res = await fetch(backendUrl.toString(), {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { success: false, error: detail || `Backend HTTP ${res.status}` },
        { status: 502 }
      );
    }

    const data = (await res.json()) as Record<string, unknown>;
    if (data.payload) {
      return NextResponse.json(data);
    }

    const statusPath = typeof data.statusUrl === "string" ? data.statusUrl : null;
    if (!statusPath) {
      return NextResponse.json(
        { success: false, error: "Backend refresh did not return statusUrl" },
        { status: 502 }
      );
    }

    const statusUrl = new URL(statusPath, BACKEND_URL).toString();
    const result = await pollRefreshStatus(statusUrl);
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json(
      {
        success: false,
        error: `${message}. Start the feed: cd backend && python angel_one_feed.py --serve`,
      },
      { status: 503 }
    );
  }
}
