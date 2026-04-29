import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  preview: {
    allowedHosts: ["swingswing-production-90b1.up.railway.app"],
  },
});
