import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    allowedHosts: ['.app.github.dev'],
    proxy: { '/api': { target: process.env.LIFEOS_API_ORIGIN || 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
