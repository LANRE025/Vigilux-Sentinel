import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Vite config for the Vigilux Sentinel "Signal Console".
// When VITE_PROXY=true, the dev server proxies /health and /fleet/* to
// VITE_API_URL. This lets the browser hit the backend same-origin in dev —
// which sidesteps CORS while the hosted backend still lacks the middleware.
// For the production build, VITE_API_URL is the direct base URL.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_URL
  const proxy = target ? { '/health': target, '/fleet': target } : {}

  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: true,
      proxy,
    },
  }
})
