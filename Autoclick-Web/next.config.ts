import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Allows a production verification build without replacing the running dev cache.
  distDir: process.env.NEXT_DIST_DIR || '.next',
  output: "standalone",
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
