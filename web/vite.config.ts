import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, the Vite server forwards /api to the FastAPI process (aml ui --api-only).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
