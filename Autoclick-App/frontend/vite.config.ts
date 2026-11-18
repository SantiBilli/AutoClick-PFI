import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  resolve: {
    alias: {
      "@": path.resolve(root, "src"),
      "@action-registry": path.resolve(root, "../desktop/autoclick_desktop/data/action_registry.json"),
      "@ai-contract": path.resolve(root, "../desktop/autoclick_desktop/data/ai_contract.json"),
    },
  },
});
