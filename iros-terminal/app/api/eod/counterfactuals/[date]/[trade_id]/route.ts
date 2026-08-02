import { proxyJson } from "../../../_proxy";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ date: string; trade_id: string }> };

/** GET /api/eod/counterfactuals/{date}/{trade_id} */
export async function GET(_request: Request, context: Ctx) {
  const { date, trade_id } = await context.params;
  return proxyJson(
    `/api/eod/counterfactuals/${encodeURIComponent(date)}/${encodeURIComponent(trade_id)}`
  );
}
