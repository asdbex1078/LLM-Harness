import { defineConfig } from 'vite'

// 独立小应用：构建到 dist/，由 FastAPI 挂在 /3d 下。base 用相对路径。
export default defineConfig({
  base: './',
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 3000 },
  server: { port: 5174, proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } } },
})
