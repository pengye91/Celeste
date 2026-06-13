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
  // In Next.js 16 the dev server blocks cross-origin requests to dev
  // resources (HMR, source maps) by default. When the API is on
  // 127.0.0.1:8000 and CMC is on 127.0.0.1:3000, the browser treats
  // the cross-origin policy strictly, which prevents client-side
  // hydration from completing and silently kills React Query fetches.
  // Allowing both loopback hostnames keeps hydration working in dev.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
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
