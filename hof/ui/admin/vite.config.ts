import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api": "http://localhost:8001",
      "/ws": { target: "ws://localhost:8001", ws: true },
      "/user-ui": "http://localhost:8001",
    },
  },
});
