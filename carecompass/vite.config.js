import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Local dev and preview mirror vercel.json: the data service and the price files are reached through this origin.
const CLOUD = 'https://ratecommons-cloud.vercel.app'
const proxy = {
  '/api/tool': { target: CLOUD, changeOrigin: true },
  '/api/tools': { target: CLOUD, changeOrigin: true },
  '/api/health': { target: CLOUD, changeOrigin: true },
  '/mcp': { target: CLOUD, changeOrigin: true },
  '/data/shop': {
    target: 'https://huggingface.co', changeOrigin: true, followRedirects: true,
    rewrite: (p) => p.replace(/^\/data\/shop/, '/buckets/ratecommons/work/resolve/shop/v2'),
  },
}

export default defineConfig({ plugins: [react()], server: { proxy }, preview: { proxy } })
