import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import pkg from "./package.json";

// Mirrors the CI rule: branch release/X.Y.Z gives X.Y.Z+<commit count>, any
// other branch gives 0.0.0-<branch>+<commit count>. Returns null outside a git checkout.
function gitVersion(): string | null {
  try {
    const git = (args: string) => execSync(`git ${args}`, { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
    const count = git("rev-list --count HEAD");
    const branch = git("rev-parse --abbrev-ref HEAD");
    const release = /^release\/(\d+)\.(\d+)(?:\.(\d+))?/.exec(branch);
    return release
      ? `${release[1]}.${release[2]}.${release[3] ?? 0}+${count}`
      : `0.0.0-${branch.replace(/[^0-9A-Za-z-]/g, "-")}+${count}`;
  } catch {
    return null;
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    // APP_VERSION is passed in by the Docker build, where there is no .git.
    __APP_VERSION__: JSON.stringify(process.env.APP_VERSION || gitVersion() || pkg.version),
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        // Container console runs over a WebSocket under /api.
        ws: true,
      },
    },
  },
});
