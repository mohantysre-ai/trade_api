import { proxyJson } from "../../../../_proxy";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ date: string; id: string }> };

/** POST /api/eod/proposals/{date}/{id}/review  body: { action: APPROVE|REJECT } */
export async function POST(request: Request, context: Ctx) {
  const { date, id } = await context.params;
  const body = await request.text();
  return proxyJson(
    `/api/eod/proposals/${encodeURIComponent(date)}/${encodeURIComponent(id)}/review`,
    { method: "POST", body: body || "{}" }
  );
}
