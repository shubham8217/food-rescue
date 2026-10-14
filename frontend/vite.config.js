import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: /api -> FastAPI on :8000 (the same prefix nginx uses in the container)
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true, rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
