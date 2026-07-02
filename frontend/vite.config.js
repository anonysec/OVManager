import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import dotenv from 'dotenv'
import path from 'path'

// Load .env from the project root
dotenv.config({ path: path.resolve(__dirname, '../.env') })

const rawPath = (process.env.VITE_URLPATH || process.env.URLPATH || '').trim();
const urlPath = rawPath.replace(/^\/+|\/+$/g, '') || '';
const base = urlPath ? `/${urlPath}/` : '/';

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