import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物入库（web/dist），由 FastAPI 同源托管，运行期不需要 Node。
// 开发期 npm run dev 起 5173，/api 代理到本地服务。
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1200 },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
})
