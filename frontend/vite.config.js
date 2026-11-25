import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api 요청을 LangGraph dev 서버(127.0.0.1:2024)로 넘겨 CORS 문제를 피한다
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:2024",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
