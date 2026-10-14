import { NextResponse } from "next/server";
import { authBackendFetch, currentAccessToken } from "@/lib/access-auth";

export async function GET() {
  const token = await currentAccessToken();
  if (!token) return NextResponse.json({ detail: "Authentication required." }, { status: 401 });
  try {
    const res = await authBackendFetch("/api/auth/admin/users", { method: "GET" }, token);
    const data = await res.json().catch(() => ({ detail: "Failed to load users." }));
    return NextResponse.json(data, { status: res.status, headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Failed to load users." },
      { status: 502 },
    );
  }
}
