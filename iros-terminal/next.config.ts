import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Slim production image via `node server.js` (see iros-terminal/Dockerfile)
  output: "standalone",
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
        // Trading shell must not stay stale: old HTML can keep rendering an
        // obsolete desk while live APIs continue updating underneath it.
        source: "/",
        headers: [
          {
            key: "Cache-Control",
            value: "no-store, max-age=0",
          },
          {
            key: "CDN-Cache-Control",
            value: "no-store",
          },
          {
            key: "Cloudflare-CDN-Cache-Control",
            value: "no-store",
          },
          { key: "X-IROS-Homepage-Cache", value: "no-store-trading-shell" },
        ],
      },
      {
        // Hashed Next chunks are content-addressed — safe to cache immutably.
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
