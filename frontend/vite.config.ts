import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')

  // Shared by the dev server (`npm run dev`) and the production preview
  // (`npm run preview`). Both proxy /api to the local backend so the frontend
  // talks to it same-origin — no CORS, and the cross-origin guard is satisfied.
  const proxy = {
    '/api': {
      target: env.VITE_BACKEND_URL || 'http://localhost:8000',
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api/, ''),
    },
  }

  return {
    envDir: __dirname,
    base: '/',
    plugins: [react()],
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
    },
    server: { proxy },
    preview: { proxy },
  }
})
