// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { gzipSync } from 'node:zlib'
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

// The panel serves at a configurable prefix (e.g. /dashboard/): the backend
// injects a <base href> into the served index.html and the URLPathMiddleware
// strips the prefix before routing, so relative asset paths resolve
// correctly. Relative paths also make the built site work as a GitHub Pages
// subpath deployment (https://<user>.github.io/OVManager/), which an
// absolute "/assets/..." base would break.

// Emit a .gz sibling next to every compressible build asset. The backend
// serves them to gzip-capable clients (AssetCacheMiddleware), cutting first
// load bytes roughly in half with zero runtime CPU.
function precompress() {
  const walk = (dir, files = []) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name)
      if (statSync(p).isDirectory()) walk(p, files)
      else files.push(p)
    }
    return files
  }
  const COMPRESS = new Set(['.js', '.css', '.svg', '.html', '.json', '.map'])
  return {
    name: 'write-precompressed-gz',
    apply: 'build',
    closeBundle() {
      for (const file of walk('dist')) {
        const ext = file.slice(file.lastIndexOf('.'))
        if (!COMPRESS.has(ext)) continue
        writeFileSync(file + '.gz', gzipSync(readFileSync(file), { level: 9 }))
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), precompress()],
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
    // Component tests need a DOM; pure-logic tests are unaffected by it.
    environment: 'jsdom',
    // jsdom denies localStorage on opaque origins (no url) — the app reads
    // it at import time (i18n, theme, timezone), so give tests a real origin.
    environmentOptions: { jsdom: { url: 'http://localhost/' } },
    setupFiles: ['./src/test-setup.js'],
  },
})
