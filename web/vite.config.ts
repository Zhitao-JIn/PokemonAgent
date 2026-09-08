import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 后端默认跑在 127.0.0.1:8000（POKEMON_API_HOST/PORT 可改）。
// dev 代理把 /runs 和 /health 转发到后端：前端代码里只写相对路径，
// 不用关心后端 host——也避免浏览器 CORS 噪音。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/runs": "http://127.0.0.1:8000",
    },
  },
});
