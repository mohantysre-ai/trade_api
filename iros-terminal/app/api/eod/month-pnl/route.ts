import { NextRequest } from "next/server";
import { proxyJson } from "../_proxy";

export const runtime = "nodejs";

/** GET /api/eod/month-pnl?month=YYYY-MM → archived daily Book P&L for the month */
export async function GET(request: NextRequest) {
  const month = request.nextUrl.searchParams.get("month");
  const qs = month ? `?month=${encodeURIComponent(month)}` : "";
  return proxyJson(`/api/eod/month-pnl${qs}`);
}
