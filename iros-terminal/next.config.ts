import type { NextConfig } from "next";

const isProduction = process.env.NODE_ENV === "production";
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProduction ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  `connect-src 'self' https: wss:${isProduction ? "" : " http: ws:"}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=()",
  },
  ...(isProduction
    ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  // Slim production image via `node server.js` (see iros-terminal/Dockerfile)
  output: "standalone",
  poweredByHeader: false,
  // Hide the floating Next.js Dev Tools "N" badge in development
  devIndicators: false,
  allowedDevOrigins: [
    "localhost",
    "127.0.0.1",
    "localhost:3000",
    "127.0.0.1:3000",
    "sigq.in",
    "*.replit.dev",
    "*.sisko.replit.dev",
    "*.repl.co",
    "*.replit.app",
    "*.id.repl.co",
    "*.replit.co",
  ],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
      {
        source: "/",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=60, s-maxage=300, stale-while-revalidate=3600, stale-if-error=86400",
          },
          {
            key: "CDN-Cache-Control",
            value: "public, max-age=300, stale-while-revalidate=3600, stale-if-error=86400",
          },
          {
            key: "Cloudflare-CDN-Cache-Control",
            value: "public, max-age=300, stale-while-revalidate=3600, stale-if-error=86400",
          },
          { key: "X-IROS-Homepage-Cache", value: "edge-ready" },
        ],
      },
    ];
  },
};

export default nextConfig;
