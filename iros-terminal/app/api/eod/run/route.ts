import { NextRequest } from "next/server";
import { proxyJson } from "../_proxy";

export const runtime = "nodejs";

/** POST /api/eod/run?date=&force=&use_llm= → trigger EOD engine */
export async function POST(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  const params = new URLSearchParams();
  const date = sp.get("date");
  const force = sp.get("force");
  const useLlm = sp.get("use_llm");
  if (date) params.set("date", date);
  if (force) params.set("force", force);
  if (useLlm) params.set("use_llm", useLlm);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return proxyJson(`/api/eod/run${qs}`, { method: "POST" });
}
