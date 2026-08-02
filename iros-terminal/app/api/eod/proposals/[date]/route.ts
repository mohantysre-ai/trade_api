import { proxyJson } from "../../_proxy";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ date: string }> };

/** GET /api/eod/proposals/{date} */
export async function GET(_request: Request, context: Ctx) {
  const { date } = await context.params;
  return proxyJson(`/api/eod/proposals/${encodeURIComponent(date)}`);
}
