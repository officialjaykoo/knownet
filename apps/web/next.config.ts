import type { NextConfig } from "next";

const apiInternal = process.env.KNOWNET_API_INTERNAL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiInternal}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${apiInternal}/health`,
      },
      {
        source: "/health/:path*",
        destination: `${apiInternal}/health/:path*`,
      },
    ];
  },
};

export default nextConfig;
