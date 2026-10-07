import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/:path*` }];
  },
  // Build candidate UI without replacing the directory used by the live service.
  distDir: [".next-candidate", ".next-workbench", ".next-demo", ".next-chat-p00"].includes(process.env.NITROGEN_NEXT_DIST_DIR ?? "")
    ? process.env.NITROGEN_NEXT_DIST_DIR : ".next",
};

export default nextConfig;
