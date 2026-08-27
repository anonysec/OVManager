// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function githubPagesPlugin() {
  return {
    name: 'ovmanager-github-pages',
    closeBundle() {
      const distDir = path.resolve(__dirname, 'dist')
      const rootDir = path.resolve(__dirname, '..')
      const installSh = path.resolve(rootDir, 'install.sh')

      if (!fs.existsSync(distDir)) return

      // Copy install.sh to dist/ so curl -sSL https://<user>.github.io/OVManager/install.sh works
      if (fs.existsSync(installSh)) {
        fs.copyFileSync(installSh, path.resolve(distDir, 'install.sh'))
      }

      // Add .nojekyll to disable Jekyll filtering on GitHub Pages
      fs.writeFileSync(path.resolve(distDir, '.nojekyll'), '')

      // Generate 404.html from index.html for SPA routing fallback on GitHub Pages
      const indexPath = path.resolve(distDir, 'index.html')
      if (fs.existsSync(indexPath)) {
        let html = fs.readFileSync(indexPath, 'utf-8')
        const repo = process.env.GITHUB_REPOSITORY
          ? process.env.GITHUB_REPOSITORY.split('/')[1]
          : 'OVManager'
        const baseHref = `/${repo}/`
        if (!html.includes('<base ')) {
          html = html.replace('<head>', `<head>\n    <base href="${baseHref}" />`)
        }
        fs.writeFileSync(path.resolve(distDir, '404.html'), html, 'utf-8')
      }
    },
  }
}

// The panel serves at a configurable prefix (e.g. /dashboard/): the backend
// injects a <base href> into the served index.html and the URLPathMiddleware
// strips the prefix before routing, so relative asset paths resolve
// correctly. Relative paths also make the built site work as a GitHub Pages
// subpath deployment (https://<user>.github.io/OVManager/), which an
// absolute "/assets/..." base would break.
export default defineConfig({
  plugins: [react(), githubPagesPlugin()],
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
    setupFiles: ['./src/test-setup.js'],
  },
})
