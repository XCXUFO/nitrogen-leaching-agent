import type { NextConfig } from "next";
import { literaturePdfLimitMb } from "./src/lib/literature-config";

const nextConfig: NextConfig = {
  // Rewrites also use Next's cloned request body. The default 10 MB buffer
  // truncates PDFs before the backend can validate their contents.
  experimental: {
    proxyClientMaxBodySize: (literaturePdfLimitMb() + 1) * 1024 * 1024,
    // Allow the backend to return its bounded model timeout through rewrites.
    proxyTimeout: 300_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/:path*` }];
  },
  // Build candidate UI without replacing the directory used by the live service.
  distDir: [".next-candidate", ".next-workbench", ".next-demo", ".next-chat-p00"].includes(process.env.NITROGEN_NEXT_DIST_DIR ?? "")
    ? process.env.NITROGEN_NEXT_DIST_DIR : ".next",
};

export default nextConfig;
