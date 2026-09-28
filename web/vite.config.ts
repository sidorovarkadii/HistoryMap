import { defineConfig } from "vite";

export default defineConfig({
  server: { port: 5173 },
  // maplibre-gl v6 loads its web worker by URL; Vite's dependency pre-bundling breaks that URL.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  test: { environment: "node" },
} as never);
