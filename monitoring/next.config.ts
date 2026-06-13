import type { NextConfig } from "next";

// The API rewrite proxy must read the SAME env var as src/lib/api.ts so the
// browser-side fetch and the server-side proxy always agree on the backend.
// NEXT_PUBLIC_CELESTE_API_URL is the canonical name; NEXT_PUBLIC_API_URL is
// accepted as a legacy fallback for older deployments.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_CELESTE_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BASE_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
