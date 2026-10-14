import { NextResponse } from "next/server";
import { ACCESS_COOKIE, authBackendFetch, currentAccessToken } from "@/lib/access-auth";

export async function POST() {
  const token = await currentAccessToken();
  try {
    if (token) {
      await authBackendFetch("/api/auth/logout", { method: "POST" }, token);
    }
  } catch {
    // Local cookie removal is still authoritative for the browser session.
  }
  const response = NextResponse.json({ success: true });
  response.cookies.set(ACCESS_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
