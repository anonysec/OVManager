// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The panel serves at a configurable prefix (e.g. /dashboard/): the backend
// injects a <base href> into the served index.html and the URLPathMiddleware
// strips the prefix before routing, so relative asset paths resolve
// correctly. Relative paths also make the built site work as a GitHub Pages
// subpath deployment (https://<user>.github.io/OVManager/), which an
// absolute "/assets/..." base would break.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
  },
  build: {
    outDir: 'dist',
  },
  test: {
    include: ['src/**/*.{test,spec}.{js,jsx,ts,tsx}'],
    exclude: ['node_modules', 'dist'],
  },
})
