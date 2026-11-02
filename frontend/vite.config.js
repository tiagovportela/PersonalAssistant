import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The service serves dist/ with a strict Content-Security-Policy: no inline code or data URIs.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, assetsInlineLimit: 0, sourcemap: false },
});
