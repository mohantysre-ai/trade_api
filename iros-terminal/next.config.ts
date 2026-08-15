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
};

export default nextConfig;
