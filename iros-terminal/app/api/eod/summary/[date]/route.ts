import { proxyJson } from "../../_proxy";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ date: string }> };

/** GET /api/eod/summary/{date} → master_eod_payload.json */
export async function GET(_request: Request, context: Ctx) {
  const { date } = await context.params;
  return proxyJson(`/api/eod/summary/${encodeURIComponent(date)}`);
}
