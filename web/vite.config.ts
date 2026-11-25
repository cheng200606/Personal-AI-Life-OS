import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const { CODESPACE_NAME, GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN } = process.env
const codespaceHost = CODESPACE_NAME && GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN
  ? `${CODESPACE_NAME}-5173.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}`
  : undefined

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    allowedHosts: codespaceHost ? [codespaceHost] : [],
    proxy: { '/api': { target: process.env.LIFEOS_API_ORIGIN || 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
