import path from "node:path";
import type { NextConfig } from "next";

const cwd = process.cwd();
const repoRoot = path.basename(cwd) === "web" ? path.dirname(cwd) : cwd;

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: repoRoot,
};

export default nextConfig;
