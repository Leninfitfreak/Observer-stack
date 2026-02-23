import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/static/history/",
  build: {
    outDir: "../app/static/history",
    emptyOutDir: true
  }
});
