import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: [
    "localhost",
    "127.0.0.1",
    "localhost:3000",
    "127.0.0.1:3000",
    "*.replit.dev",
    "*.sisko.replit.dev",
    "*.repl.co",
    "*.replit.app",
    "*.id.repl.co",
    "*.replit.co",
  ],
};

export default nextConfig;
