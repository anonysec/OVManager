import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The panel serves at a configurable prefix (e.g. /dashboard/), but the
// frontend NEVER needs to know it at build time: the backend injects a
// <base href> into the served index.html and the app reads it at runtime.
// So: absolute asset paths, no VITE_URLPATH define, no .env coupling.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
  },
  build: {
    outDir: 'dist',
  },
  test: {
    include: ['src/**/*.{test,spec}.{js,jsx,ts,tsx}'],
    exclude: ['e2e', 'node_modules', 'dist'],
  },
})
