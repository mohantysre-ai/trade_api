import { proxyJson } from "../_proxy";

export const runtime = "nodejs";

/** GET /api/eod/dates → backend available analysis dates */
export async function GET() {
  return proxyJson("/api/eod/dates");
}
