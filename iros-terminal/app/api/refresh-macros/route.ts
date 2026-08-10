import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_URL = process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";

export async function POST() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/refresh-macros`, {
      method: "POST",
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: body?.detail || body?.error || `Upstream ${res.status}` },
        { status: res.status },
      );
    }
    return NextResponse.json(body);
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    );
  }
}
