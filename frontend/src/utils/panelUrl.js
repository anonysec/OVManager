// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/**
 * Runtime panel-URL helpers — single source: the <base href> tag.
 *
 * The backend injects <base href="/{urlpath}/"> into the served HTML on every
 * request, so these helpers always reflect the CURRENT panel prefix without
 * any build-time constant (VITE_URLPATH) or injected global
 * (window.__OV_URLPATH__). The frontend is fully prefix-agnostic.
 */

/** Read the <base href> as a path, e.g. "/dashboard/" or "/". */
const baseHref = () => {
  const el = typeof document !== 'undefined' ? document.querySelector('base') : null;
  const href = el?.getAttribute('href');
  if (href) {
    // Keep only the path portion (strip any protocol/host if a full URL is used).
    try {
      const url = new URL(href, window.location.origin);
      return url.pathname;
    } catch {
      return href.startsWith('/') ? href : `/${href}`;
    }
  }
  // Fallback when hosted on GitHub Pages (*.github.io) without an explicit <base> tag:
  // use the first pathname segment (the repository name) as the subpath.
  if (typeof window !== 'undefined' && window.location.hostname?.endsWith('.github.io')) {
    const segments = window.location.pathname.split('/').filter(Boolean);
    if (segments.length > 0) {
      return `/${segments[0]}/`;
    }
  }
  return '/';
};

/** Current URLPATH prefix, e.g. "dashboard" or "" (panel at root). */
export const getUrlPath = () => baseHref().replace(/^\/+|\/+$/g, '');

/** Base path prefix for the router, e.g. "/dashboard" or "" at root. */
export const getPanelBase = () => {
  const path = getUrlPath();
  return path ? `/${path}` : '';
};

/** Origin + prefix, e.g. "https://panel.example.com/dashboard". */
export const getPanelOrigin = () => `${window.location.origin}${getPanelBase()}`;
