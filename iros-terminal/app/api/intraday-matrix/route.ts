import { NextResponse } from "next/server";

export const runtime = "nodejs";
const BACKEND_URL =
  process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";

export async function GET(request: Request) {
  try {
    const backendUrl = new URL(`${BACKEND_URL}/api/intraday-matrix`);
    const requestUrl = new URL(request.url);
    // Forward any query params from the frontend request to the backend
    requestUrl.searchParams.forEach((value, key) => {
      backendUrl.searchParams.set(key, value);
    });

    const res = await fetch(backendUrl.toString(), {
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
        error: `${message}. Ensure Market API backend is running on port 8000.`,
      },
      { status: 503 }
    );
  }
}