import { NextResponse } from "next/server";
import { ACCESS_COOKIE, authBackendFetch } from "@/lib/access-auth";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const res = await authBackendFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({ detail: "Sign in failed." }));
    if (!res.ok || !data?.token) {
      return NextResponse.json(data, { status: res.status });
    }

    const response = NextResponse.json({
      success: true,
      user: data.user,
      expiresAt: data.expiresAt,
    });
    response.cookies.set(ACCESS_COOKIE, String(data.token), {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 14,
    });
    return response;
  } catch (err) {
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Sign in failed." },
      { status: 502 },
    );
  }
}
