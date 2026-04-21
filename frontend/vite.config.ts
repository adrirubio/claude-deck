import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'

const packageJson = JSON.parse(
  readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8')
)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    APP_VERSION: JSON.stringify(packageJson.version),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    // Accept any Host header. Vite 7 blocks unknown hostnames by default
    // (DNS-rebinding protection), which rejects access via LAN/tailnet
    // hostnames like `ubuntu1804`. The backend enforces its own same-origin
    // check on WebSocket upgrades, so this is safe on a trusted network.
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        // Preserve the browser's Host header so the backend can enforce
        // same-origin on WebSocket upgrades (cc-bridge terminal). With
        // changeOrigin:true, vite would rewrite Host to localhost:8000
        // and the same-origin check would fail for LAN/tailnet access.
        changeOrigin: false,
        ws: true,
      },
    },
  },
})
