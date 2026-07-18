import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import dotenv from 'dotenv'
import path from 'path'

// Load .env from the project root (parent of frontend)
// During Docker build, .env is copied to frontend dir, so check both locations
const envPath = path.resolve(__dirname, '../.env')
const localEnvPath = path.resolve(__dirname, '.env')

// Try loading from project root first, then from local dir
try {
    dotenv.config({ path: envPath })
} catch {
    dotenv.config({ path: localEnvPath })
}

const rawPath = (process.env.VITE_URLPATH || process.env.URLPATH || '').trim()
const urlPath = rawPath.replace(/^\/+|\/+$/g, '') || ''
const base = urlPath ? `/${urlPath}/` : '/'

export default defineConfig({
  plugins: [react()],
  base,
  define: {
    'import.meta.env.VITE_URLPATH': JSON.stringify(urlPath),
  },
  build: {
    outDir: 'dist',
  },
})