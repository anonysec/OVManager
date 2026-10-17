// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/*
 * OVManager static-shell service worker.
 *
 * Caches ONLY the app shell (HTML, manifest, icons and the hashed build
 * assets fetched at runtime). API responses, subscription links and health
 * probes are always passed straight to the network: the panel is a live
 * control surface, so a stale cached answer would be worse than no answer.
 *
 * Bump CACHE_VERSION on every release; the old cache is deleted on activate.
 */
const CACHE_VERSION = 'v1';
const CACHE_NAME = `ovmanager-static-${CACHE_VERSION}`;

// Paths are resolved against this script's location, so the worker works at
// the panel root and under a URLPATH prefix (e.g. /dashboard/) alike.
const SHELL_URL = new URL('./', self.location).href; // the built index.html
const PRECACHE_URLS = [
  SHELL_URL,
  new URL('./manifest.webmanifest', self.location).href,
  new URL('./icons/icon.svg', self.location).href,
  new URL('./icons/icon-maskable.svg', self.location).href,
  new URL('./icons/apple-touch-icon.png', self.location).href,
];

// Never intercepted: authenticated data, subscription pages, health checks.
const BYPASS_PREFIXES = ['/api', '/sub', '/health'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      // Individually so one missing optional file cannot fail the install.
      await Promise.all(
        PRECACHE_URLS.map((url) => cache.add(url).catch(() => {})),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

// Navigation: network-first, so a new build is picked up as soon as the user
// is online; the cached shell is only the offline fallback.
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(SHELL_URL, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(SHELL_URL);
    return cached || Response.error();
  }
}

// Same-origin static GET: cache-first (build assets carry hashed names).
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok && response.type === 'basic') {
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // never cache cross-origin
  if (BYPASS_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return;
  if (request.headers.get('range')) return;

  event.respondWith(request.mode === 'navigate' ? networkFirst(request) : cacheFirst(request));
});
