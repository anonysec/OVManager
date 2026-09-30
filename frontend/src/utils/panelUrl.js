// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Single source for the panel URL prefix: the <base href> the backend injects
// on every served HTML response. Reading it at runtime (rather than a
// build-time VITE_URLPATH or a window global) keeps the frontend fully
// prefix-agnostic.

const baseHref = () => {
  const el = typeof document !== 'undefined' ? document.querySelector('base') : null;
  const href = el?.getAttribute('href');
  if (!href) return '/';
  // Keep only the path portion (strip any protocol/host if a full URL is used).
  try {
    const url = new URL(href, window.location.origin);
    return url.pathname;
  } catch {
    return href.startsWith('/') ? href : `/${href}`;
  }
};

/** Current URLPATH prefix, e.g. "dashboard" or "" (panel at root). */
export const getUrlPath = () => baseHref().replace(/^\/+|\/+$/g, '');
