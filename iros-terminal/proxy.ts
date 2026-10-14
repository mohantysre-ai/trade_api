import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "sigq_session";

function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname.startsWith("/api/auth/") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico" ||
    pathname === "/manifest.webmanifest" ||
    pathname === "/theme-boot.js" ||
    pathname === "/sw.js" ||
    pathname.startsWith("/icon-") ||
    pathname.startsWith("/apple-touch-icon") ||
    pathname.startsWith("/alphix-logo")
  );
}

async function validateSession(token: string) {
  const backend = (
    process.env.MARKET_API_URL ??
    process.env.NEXT_PUBLIC_BACKEND_URL ??
    "http://127.0.0.1:8000"
  ).replace(/\/$/, "");
  const res = await fetch(`${backend}/api/auth/session`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  const body = await res.json().catch(() => null);
  return body?.authenticated ? body?.user ?? null : null;
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get(COOKIE_NAME)?.value;

  if (isPublicPath(pathname)) {
    if (pathname === "/login" && token) {
      try {
        const user = await validateSession(token);
        if (user) return NextResponse.redirect(new URL("/", request.url));
      } catch {
        // Login remains available if the auth service is temporarily unavailable.
      }
    }
    return NextResponse.next();
  }

  if (!token) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ detail: "Authentication required." }, { status: 401 });
    }
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }

  try {
    const user = await validateSession(token);
    if (!user) throw new Error("invalid session");
    if (pathname.startsWith("/admin") && !user.isAdmin) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next();
  } catch {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ detail: "Authentication required." }, { status: 401 });
    }
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.set(COOKIE_NAME, "", { path: "/", maxAge: 0 });
    return response;
  }
}

export const config = {
  matcher: ["/:path*"],
};
