import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_URL = process.env.MARKET_API_URL ?? "http://127.0.0.1:8000";

export async function GET(request: Request) {
  try {
    const backendUrl = new URL(`${BACKEND_URL}/api/nse-symbols`);
    const requestUrl = new URL(request.url);
    const universe = requestUrl.searchParams.get("universe");
    if (universe) backendUrl.searchParams.set("universe", universe);

    const res = await fetch(backendUrl.toString(), { cache: "no-store" });
    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { success: false, error: detail || `Upstream ${res.status}` },
        { status: res.status },
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    );
  }
}
