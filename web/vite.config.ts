import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api is proxied to the FastAPI server (scripts/run_demo.sh starts both)
export default defineConfig({
  plugins: [react()],
  server: { port: 5175, proxy: { '/api': 'http://localhost:8000' } },
})
