import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function findCatalogPackage() {
  let dir = path.dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 8; i += 1) {
    const candidate = path.join(dir, "packages", "xflows-catalog");
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error("packages/xflows-catalog not found from vite.config.js");
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@xflows-catalog": findCatalogPackage(),
    },
  },
  server: {
    port: 5173,
    fs: {
      allow: ["..", "../.."],
    },
  },
});
