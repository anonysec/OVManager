// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The panel always serves the subscription page at <origin>/<subscription_path>/<uuid>,
 * outside the panel's own path prefix. The optional `subscription_url_prefix`
 * setting is an EXTERNAL host to point subscribers at (a CDN, a second
 * instance); when it is empty the link is the panel's own page. Before this
 * existed the link was empty on a default install, so no subscriber could
 * ever be given a configuration URL.
 */
export const buildSubscriptionLink = (
  origin: string,
  prefix: string,
  path: string,
  uuid: string,
): string => {
  if (!uuid) return '';
  const rawPath = (path || 'sub').replace(/^\/+|\/+$/g, '') || 'sub';
  const base = prefix
    ? (prefix.endsWith('/') ? prefix : `${prefix}/`)
    : (origin.endsWith('/') ? origin : `${origin}/`);
  return `${base}${rawPath}/${uuid}`;
};
