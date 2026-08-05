import { NextResponse } from "next/server";

export const runtime = "nodejs";

const MAIN_API_URL =
  process.env.MARKET_API_URL ||
  process.env.NEXT_PUBLIC_MARKET_API_URL ||
  "http://127.0.0.1:8000";

export async function GET(request: Request) {
  try {
    const requestUrl = new URL(request.url);
    const ticker = requestUrl.searchParams.get("ticker");
    if (!ticker) {
      return NextResponse.json(
        { success: false, error: "Missing required parameter: ticker" },
        { status: 400 }
      );
    }

    const params = new URLSearchParams();
    params.set("ticker", ticker);
    if (requestUrl.searchParams.get("force")) {
      params.set("force", requestUrl.searchParams.get("force")!);
    }

    const backendUrl = new URL("/api/desk-ic", MAIN_API_URL);
    backendUrl.search = params.toString();

    const res = await fetch(backendUrl.toString(), {
      cache: "no-store",
      signal: AbortSignal.timeout(120_000),
    });

    const data = await res.json().catch(() => null);
    if (!res.ok) {
      return NextResponse.json(
        {
          success: false,
          error: (data && (data.detail || data.error)) || `Upstream ${res.status}`,
        },
        { status: res.status >= 400 ? res.status : 502 }
      );
    }

    return NextResponse.json(data ?? { success: false, error: "Empty Desk IC response" });
  } catch (err) {
    return NextResponse.json(
      {
        success: false,
        error: err instanceof Error ? err.message : "Desk IC proxy failed",
      },
      { status: 502 }
    );
  }
}
