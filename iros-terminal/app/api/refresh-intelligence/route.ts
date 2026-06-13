import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL =
  process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";

async function proxyBackend(path: string): Promise<Response> {
  const url = new URL(path, `${BACKEND_URL}/`);
  const res = await fetch(url.toString(), {
    method: "GET",
    cache: "no-store",
  });
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") || "application/json" },
  });
}

export async function POST(request: Request) {
  try {
    const backendUrl = new URL("/api/refresh-intelligence", BACKEND_URL);
    const requestUrl = new URL(request.url);
    const pool = requestUrl.searchParams.get("pool");
    const prompt = requestUrl.searchParams.get("prompt");
    if (pool) {
      backendUrl.searchParams.set("pool", pool);
    }
    if (prompt) {
      backendUrl.searchParams.set("prompt", prompt);
    }

    const res = await fetch(backendUrl.toString(), {
      method: "POST",
      cache: "no-store",
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { success: false, error: detail || `Backend HTTP ${res.status}` },
        { status: 502 }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json(
      {
        success: false,
        error: `${message}. Start the feed: cd backend && python angel_one_feed.py --serve`,
      },
      { status: 503 }
    );
  }
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const taskId = url.searchParams.get("taskId");
    if (!taskId) {
      return NextResponse.json(
        { success: false, error: "Missing taskId parameter." },
        { status: 400 }
      );
    }
    return proxyBackend(`/api/refresh-intelligence/status?taskId=${encodeURIComponent(taskId)}`);
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json(
      {
        success: false,
        error: `${message}. Start the feed: cd backend && python angel_one_feed.py --serve`,
      },
      { status: 503 }
    );
  }
}
