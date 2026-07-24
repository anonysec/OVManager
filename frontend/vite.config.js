/* global __dirname, process */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import dotenv from 'dotenv'
import path from 'path'

// Load .env from the project root (parent of frontend)
// During Docker build, .env is copied to frontend dir, so check both locations
const envPath = path.resolve(__dirname, '../.env')
const localEnvPath = path.resolve(__dirname, '.env')

// Try loading from local dir first (Docker copy), then from project root
const loadDotenv = (p) => { try { const r = dotenv.config({ path: p }); if (r.error) throw r.error; } catch { /* skip */ } };
loadDotenv(localEnvPath);
loadDotenv(envPath);

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