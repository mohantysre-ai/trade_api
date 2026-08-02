import { NextRequest } from "next/server";
import { proxyJson } from "../_proxy";

export const runtime = "nodejs";

/** POST /api/eod/pm-llm?date=YYYY-MM-DD — PM commentary LLM once per day */
export async function POST(request: NextRequest) {
  const date = request.nextUrl.searchParams.get("date");
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return proxyJson(`/api/eod/pm-llm${qs}`, { method: "POST" });
}
