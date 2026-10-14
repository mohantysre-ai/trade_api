import { NextResponse } from "next/server";
import { authBackendFetch, currentAccessToken } from "@/lib/access-auth";

export async function POST(request: Request) {
  const token = await currentAccessToken();
  if (!token) return NextResponse.json({ detail: "Authentication required." }, { status: 401 });
  try {
    const body = await request.json();
    const action = body?.action === "approve" ? "approve" : body?.action === "reject" ? "reject" : null;
    const userId = Number(body?.userId);
    if (!action || !Number.isInteger(userId) || userId <= 0) {
      return NextResponse.json({ detail: "Invalid approval action." }, { status: 400 });
    }
    const res = await authBackendFetch(`/api/auth/admin/${action}`, {
      method: "POST",
      body: JSON.stringify({ userId }),
    }, token);
    const data = await res.json().catch(() => ({ detail: "Approval action failed." }));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Approval action failed." },
      { status: 502 },
    );
  }
}
