import { proxyJson } from "../../../_proxy";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ date: string; ticker: string }> };

/** GET /api/eod/timeline/{date}/{ticker} */
export async function GET(_request: Request, context: Ctx) {
  const { date, ticker } = await context.params;
  return proxyJson(
    `/api/eod/timeline/${encodeURIComponent(date)}/${encodeURIComponent(ticker)}`
  );
}
