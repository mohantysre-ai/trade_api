import { NextResponse } from "next/server";
import { authBackendFetch } from "@/lib/access-auth";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const res = await authBackendFetch("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({ detail: "Registration failed." }));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Registration failed." },
      { status: 502 },
    );
  }
}
