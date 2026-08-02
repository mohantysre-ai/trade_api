import { NextRequest } from "next/server";
import { proxyJson } from "../../_proxy";

export const runtime = "nodejs";

/** GET /api/eod/llm-status/:date — whether PM LLM already cached for the day */
export async function GET(
  _request: NextRequest,
  ctx: { params: Promise<{ date: string }> }
) {
  const { date } = await ctx.params;
  return proxyJson(`/api/eod/llm-status/${encodeURIComponent(date)}`);
}
